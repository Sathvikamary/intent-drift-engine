"""
Multi-Intent State Machine — MILD-style control loop.

Models the lifecycle of the three self-driving network macro-intents:
    I_tel  (Telemetry)
    I_anl  (Analytics)
    I_api  (API Gateway)

Each macro-intent progresses through states:
    INITIALIZING → ACTIVE → DRIFTING → REMEDIATING → ACTIVE
                                     ↘ VIOLATED (SLA breach)
                                     ↘ FAILED (unrecoverable)

The MILDStateMachine orchestrates causal co-drift propagation:
    If I_tel enters DRIFTING, it triggers DRIFTING assessment in I_anl,
    which may cascade to I_api.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Any

from src.drift.detector import DriftDetector, DriftEvent, DriftSeverity, KPIObservation, MacroIntent
from src.drift.scm import SCMBuilder, build_network_scm


class IntentState(str, Enum):
    INITIALIZING = "initializing"   # Not yet active
    ACTIVE = "active"               # Within nominal KPI bounds
    DRIFTING = "drifting"           # Deviation detected, within SLA
    REMEDIATING = "remediating"     # Remediation action in progress
    VIOLATED = "violated"           # SLA breach — escalation required
    FAILED = "failed"               # Unrecoverable state


# State transition rules: current → allowed next states
VALID_TRANSITIONS: dict[IntentState, set[IntentState]] = {
    IntentState.INITIALIZING: {IntentState.ACTIVE, IntentState.FAILED},
    IntentState.ACTIVE:        {IntentState.DRIFTING, IntentState.FAILED},
    IntentState.DRIFTING:      {IntentState.ACTIVE, IntentState.REMEDIATING, IntentState.VIOLATED},
    IntentState.REMEDIATING:   {IntentState.ACTIVE, IntentState.VIOLATED, IntentState.FAILED},
    IntentState.VIOLATED:      {IntentState.REMEDIATING, IntentState.FAILED},
    IntentState.FAILED:        set(),  # Terminal
}


@dataclass
class IntentStateRecord:
    """Full state record for a single macro-intent."""
    intent: MacroIntent
    state: IntentState = IntentState.INITIALIZING
    history: list[tuple[IntentState, float, str]] = field(default_factory=list)
    active_drift_events: list[DriftEvent] = field(default_factory=list)
    remediation_attempts: int = 0
    last_updated: float = field(default_factory=time.time)

    def transition(self, new_state: IntentState, reason: str = "") -> bool:
        """Perform a state transition. Returns True if successful."""
        if new_state not in VALID_TRANSITIONS.get(self.state, set()):
            return False
        self.history.append((self.state, time.time(), reason))
        self.state = new_state
        self.last_updated = time.time()
        return True

    def to_dict(self) -> dict[str, Any]:
        return {
            "intent": self.intent.value,
            "state": self.state.value,
            "remediation_attempts": self.remediation_attempts,
            "active_drift_count": len(self.active_drift_events),
            "last_updated": self.last_updated,
            "history": [
                {"from": s.value, "at": t, "reason": r}
                for s, t, r in self.history[-5:]   # Last 5 transitions
            ],
        }


# Remediation handler type
RemediationHandler = Callable[[MacroIntent, list[DriftEvent]], bool]


class MILDStateMachine:
    """
    Multi-Intent Lifecycle Director (MILD) State Machine.

    Runs continuous closed-loop assurance across all three macro-intents.
    Propagates causal co-drift from root-cause intent to downstream intents.
    Triggers remediation and escalates SLA violations.

    Causal propagation order (from SCM):
        I_tel → I_anl → I_api
    """

    # Causal propagation order
    PROPAGATION_ORDER = [MacroIntent.TELEMETRY, MacroIntent.ANALYTICS, MacroIntent.API_GATEWAY]

    def __init__(
        self,
        drift_detector: DriftDetector | None = None,
        scm: SCMBuilder | None = None,
        remediation_handler: RemediationHandler | None = None,
        max_remediation_attempts: int = 3,
    ) -> None:
        self.drift_detector = drift_detector or DriftDetector()
        self.scm = scm or build_network_scm()
        self.remediation_handler = remediation_handler
        self.max_remediation_attempts = max_remediation_attempts
        self.event_log: list[dict[str, Any]] = []

        # Initialize all intent states
        self._states: dict[MacroIntent, IntentStateRecord] = {
            intent: IntentStateRecord(intent=intent)
            for intent in MacroIntent
        }

        # Activate all intents immediately
        for record in self._states.values():
            record.transition(IntentState.ACTIVE, "system initialization")

    # ------------------------------------------------------------------ #
    # Core control loop tick                                               #
    # ------------------------------------------------------------------ #

    def tick(self, observations: list[KPIObservation]) -> dict[str, Any]:
        """
        Single control loop iteration:
          1. Ingest KPI observations into drift detector.
          2. Run drift detection.
          3. Map drift events to intents.
          4. Apply state transitions (with causal propagation).
          5. Trigger remediation if needed.
          6. Return system snapshot.
        """
        t_start = time.perf_counter()
        drift_result = self.drift_detector.detect(observations)
        log_entries: list[str] = []

        # ── Map drift events to their intents ───────────────────────────
        intent_events: dict[MacroIntent, list[DriftEvent]] = {i: [] for i in MacroIntent}
        for event in drift_result.events:
            intent_events[event.affected_intent].append(event)

        # ── State machine transitions (in causal propagation order) ─────
        for intent in self.PROPAGATION_ORDER:
            record = self._states[intent]
            events = intent_events.get(intent, [])

            if events:
                worst = max(events, key=lambda e: list(DriftSeverity).index(e.severity))
                record.active_drift_events = events
                entry = self._handle_drift(record, worst, log_entries)
            else:
                # Clear drift if resolved
                if record.state == IntentState.DRIFTING:
                    record.transition(IntentState.ACTIVE, "drift resolved")
                    log_entries.append(f"[{intent.value}] Drift resolved → ACTIVE")
                    record.active_drift_events = []

            # Causal co-drift propagation: if upstream is drifting, flag downstream
            self._propagate_causal_pressure(intent, record, log_entries)

        elapsed_ms = (time.perf_counter() - t_start) * 1000
        snapshot = self._snapshot(drift_result, elapsed_ms, log_entries)
        self.event_log.append(snapshot)
        return snapshot

    # ------------------------------------------------------------------ #
    # State transition logic                                               #
    # ------------------------------------------------------------------ #

    def _handle_drift(
        self,
        record: IntentStateRecord,
        worst_event: DriftEvent,
        log: list[str],
    ) -> None:
        intent = record.intent
        severity = worst_event.severity

        if severity == DriftSeverity.CRITICAL and record.state != IntentState.VIOLATED:
            if record.state == IntentState.REMEDIATING:
                record.transition(IntentState.VIOLATED, "remediation failed — SLA breached")
                log.append(f"[{intent.value}] 🔴 VIOLATED — SLA breach")
            else:
                record.transition(IntentState.DRIFTING, f"critical drift: {worst_event.kpi_name}")
                log.append(f"[{intent.value}] ⚠️ CRITICAL drift on {worst_event.kpi_name}")

        elif severity in (DriftSeverity.DRIFT, DriftSeverity.WARNING):
            if record.state == IntentState.ACTIVE:
                record.transition(IntentState.DRIFTING, f"drift: {worst_event.kpi_name}")
                log.append(f"[{intent.value}] ⚠️ Drift detected on {worst_event.kpi_name}")

        # Trigger remediation if drifting and not already remediating
        if record.state == IntentState.DRIFTING:
            self._attempt_remediation(record, log)

    def _attempt_remediation(self, record: IntentStateRecord, log: list[str]) -> None:
        intent = record.intent
        if record.remediation_attempts >= self.max_remediation_attempts:
            record.transition(IntentState.FAILED, "max remediation attempts exceeded")
            log.append(f"[{intent.value}] 💀 FAILED — remediation exhausted")
            return

        record.transition(IntentState.REMEDIATING, "auto-remediation triggered")
        record.remediation_attempts += 1
        log.append(f"[{intent.value}] 🔧 Remediating (attempt {record.remediation_attempts})")

        if self.remediation_handler:
            success = self.remediation_handler(intent, record.active_drift_events)
            if success:
                record.transition(IntentState.ACTIVE, "remediation successful")
                record.remediation_attempts = 0
                log.append(f"[{intent.value}] ✅ Remediation successful")
            else:
                log.append(f"[{intent.value}] ❌ Remediation handler returned failure")

    def _propagate_causal_pressure(
        self,
        upstream_intent: MacroIntent,
        upstream_record: IntentStateRecord,
        log: list[str],
    ) -> None:
        """
        If an upstream intent is drifting, add causal pressure to
        its downstream dependents (from the SCM graph).
        """
        if upstream_record.state not in (IntentState.DRIFTING, IntentState.VIOLATED):
            return

        upstream_node = upstream_intent.value
        downstream_nodes = self.scm.descendants_of(upstream_node)

        for intent in self.PROPAGATION_ORDER:
            if intent == upstream_intent:
                continue
            if intent.value in downstream_nodes:
                downstream_record = self._states[intent]
                if downstream_record.state == IntentState.ACTIVE:
                    # Causal pressure: pre-emptively move to DRIFTING
                    ok = downstream_record.transition(
                        IntentState.DRIFTING,
                        f"causal co-drift from {upstream_intent.value}",
                    )
                    if ok:
                        log.append(
                            f"[{intent.value}] ⛓️ Causal co-drift from {upstream_intent.value}"
                        )

    # ------------------------------------------------------------------ #
    # State queries                                                        #
    # ------------------------------------------------------------------ #

    def get_state(self, intent: MacroIntent) -> IntentStateRecord:
        return self._states[intent]

    def system_health(self) -> str:
        """Quick overall system health label."""
        states = [r.state for r in self._states.values()]
        if any(s == IntentState.FAILED for s in states):
            return "CRITICAL"
        if any(s == IntentState.VIOLATED for s in states):
            return "DEGRADED"
        if any(s in (IntentState.DRIFTING, IntentState.REMEDIATING) for s in states):
            return "WARNING"
        return "NOMINAL"

    def _snapshot(
        self,
        drift_result: Any,
        elapsed_ms: float,
        log: list[str],
    ) -> dict[str, Any]:
        return {
            "timestamp": time.time(),
            "elapsed_ms": round(elapsed_ms, 2),
            "system_health": self.system_health(),
            "intents": {
                intent.value: self._states[intent].to_dict()
                for intent in MacroIntent
            },
            "drift_events": len(drift_result.events),
            "causal_links": len(drift_result.causal_links),
            "most_severe": drift_result.most_severe.value,
            "log": log,
        }
