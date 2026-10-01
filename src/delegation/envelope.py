"""
Adaptive Delegation Envelope — core data model.

A Delegation Envelope defines a time-bounded, role-scoped authorization
window that constrains the set of permissible actions an agent may take
within a given operational context.

Key properties:
  - Temporal bounding  : Envelope expires after max_duration_seconds.
  - Action scoping     : Only whitelisted actions are permitted.
  - Domain partitioning: Envelope is valid for a single resource domain.
  - Revocability       : Envelope can be revoked before expiry.
  - Nesting            : Sub-envelopes can be delegated from a parent.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class EnvelopeState(str, Enum):
    PENDING = "pending"       # Created but not yet activated
    ACTIVE = "active"         # Currently valid and in scope
    EXPIRED = "expired"       # Past max_duration without revocation
    REVOKED = "revoked"       # Explicitly revoked before expiry
    EXHAUSTED = "exhausted"   # Action budget consumed


class RiskTier(str, Enum):
    """Risk classification governing allowed action reversibility."""
    LOW = "low"           # Read-only or fully reversible
    MEDIUM = "medium"     # Partially reversible with rollback
    HIGH = "high"         # Irreversible or wide-blast-radius


@dataclass
class ActionBudget:
    """Per-action invocation limits within the envelope lifecycle."""
    action: str
    max_invocations: int
    used_invocations: int = 0

    @property
    def remaining(self) -> int:
        return max(0, self.max_invocations - self.used_invocations)

    @property
    def exhausted(self) -> bool:
        return self.used_invocations >= self.max_invocations

    def consume(self) -> bool:
        """Consume one invocation. Returns True if successful."""
        if self.exhausted:
            return False
        self.used_invocations += 1
        return True


@dataclass
class DelegationEnvelope:
    """
    A time-bounded, role-scoped authorization window.

    Prevents misdelegation errors by bounding the action space and
    lifecycle of each delegation event to explicit institutional policy.
    """

    envelope_id: str = field(default_factory=lambda: f"env-{uuid.uuid4().hex[:8]}")
    role: str = ""
    domain: str = ""
    permitted_actions: list[str] = field(default_factory=list)
    action_budgets: dict[str, ActionBudget] = field(default_factory=dict)
    risk_tier: RiskTier = RiskTier.LOW
    max_duration_seconds: float = 300.0       # 5 minutes default
    created_at: float = field(default_factory=time.time)
    activated_at: float | None = None
    revoked_at: float | None = None
    parent_envelope_id: str | None = None     # For nested delegation
    constraints: dict[str, Any] = field(default_factory=dict)
    audit_log: list[dict[str, Any]] = field(default_factory=list)
    _state: EnvelopeState = field(default=EnvelopeState.PENDING, repr=False)

    # ------------------------------------------------------------------ #
    # Lifecycle                                                            #
    # ------------------------------------------------------------------ #

    def activate(self) -> None:
        """Activate the envelope — starts the lifecycle timer."""
        if self._state != EnvelopeState.PENDING:
            raise ValueError(f"Cannot activate envelope in state '{self._state}'.")
        self.activated_at = time.time()
        self._state = EnvelopeState.ACTIVE
        self._log("activated")

    def revoke(self, reason: str = "explicit revocation") -> None:
        """Revoke the envelope before expiry."""
        self.revoked_at = time.time()
        self._state = EnvelopeState.REVOKED
        self._log("revoked", reason=reason)

    def refresh_state(self) -> EnvelopeState:
        """Recalculate and update state based on time and budgets."""
        if self._state in (EnvelopeState.REVOKED, EnvelopeState.EXHAUSTED):
            return self._state
        if self._state == EnvelopeState.ACTIVE:
            if self.activated_at and (time.time() - self.activated_at) > self.max_duration_seconds:
                self._state = EnvelopeState.EXPIRED
                self._log("expired")
            elif all(b.exhausted for b in self.action_budgets.values()) and self.action_budgets:
                self._state = EnvelopeState.EXHAUSTED
                self._log("exhausted")
        return self._state

    @property
    def state(self) -> EnvelopeState:
        return self.refresh_state()

    @property
    def is_valid(self) -> bool:
        return self.state == EnvelopeState.ACTIVE

    @property
    def elapsed_seconds(self) -> float | None:
        if self.activated_at is None:
            return None
        return time.time() - self.activated_at

    @property
    def remaining_seconds(self) -> float | None:
        elapsed = self.elapsed_seconds
        if elapsed is None:
            return None
        return max(0.0, self.max_duration_seconds - elapsed)

    # ------------------------------------------------------------------ #
    # Action authorization                                                 #
    # ------------------------------------------------------------------ #

    def can_perform(self, action: str) -> tuple[bool, str]:
        """
        Check whether action is permitted within this envelope.
        Returns (allowed: bool, reason: str).
        """
        if not self.is_valid:
            return False, f"Envelope is not active (state={self.state.value})"
        if action not in self.permitted_actions:
            return False, f"Action '{action}' not in permitted action set"
        if action in self.action_budgets and self.action_budgets[action].exhausted:
            return False, f"Action '{action}' budget exhausted"
        return True, "permitted"

    def consume_action(self, action: str, actor: str = "agent") -> bool:
        """
        Record an action invocation. Returns True if permitted & logged.
        """
        allowed, reason = self.can_perform(action)
        if not allowed:
            self._log("action_denied", action=action, actor=actor, reason=reason)
            return False
        if action in self.action_budgets:
            self.action_budgets[action].consume()
        self._log("action_consumed", action=action, actor=actor)
        return True

    # ------------------------------------------------------------------ #
    # Sub-delegation                                                       #
    # ------------------------------------------------------------------ #

    def delegate(
        self,
        sub_role: str,
        sub_actions: list[str],
        max_duration_seconds: float | None = None,
    ) -> DelegationEnvelope:
        """
        Create a child envelope from this one — restricted sub-delegation.

        Sub-envelope constraints:
          - Can only delegate actions this envelope already permits.
          - Duration cannot exceed remaining time of parent.
          - Risk tier cannot exceed parent tier.
        """
        invalid = [a for a in sub_actions if a not in self.permitted_actions]
        if invalid:
            raise ValueError(
                f"Cannot delegate actions not in parent envelope: {invalid}"
            )
        parent_remaining = self.remaining_seconds
        if parent_remaining is None:
            raise ValueError("Parent envelope is not activated — cannot sub-delegate.")

        duration = min(
            max_duration_seconds or parent_remaining,
            parent_remaining,
        )

        child = DelegationEnvelope(
            role=sub_role,
            domain=self.domain,
            permitted_actions=sub_actions,
            risk_tier=self.risk_tier,
            max_duration_seconds=duration,
            parent_envelope_id=self.envelope_id,
        )
        self._log("sub_delegated", child_id=child.envelope_id, sub_role=sub_role)
        return child

    # ------------------------------------------------------------------ #
    # Audit                                                                #
    # ------------------------------------------------------------------ #

    def _log(self, event: str, **kwargs: Any) -> None:
        self.audit_log.append({"event": event, "ts": time.time(), **kwargs})

    def to_dict(self) -> dict[str, Any]:
        return {
            "envelope_id": self.envelope_id,
            "role": self.role,
            "domain": self.domain,
            "state": self.state.value,
            "risk_tier": self.risk_tier.value,
            "permitted_actions": self.permitted_actions,
            "remaining_seconds": self.remaining_seconds,
            "parent_envelope_id": self.parent_envelope_id,
            "audit_log_size": len(self.audit_log),
            "budgets": {
                k: {"remaining": v.remaining, "max": v.max_invocations}
                for k, v in self.action_budgets.items()
            },
        }
