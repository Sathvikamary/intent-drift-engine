"""
Multi-Intent Drift Detector — Granger Causality Engine.

Detects causal co-drift across Telemetry (I_tel), Analytics (I_anl),
and API Gateway (I_api) macro-intents using multivariate Granger causality.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import numpy as np


class DriftSeverity(str, Enum):
    NOMINAL = "nominal"        # Within baseline bounds
    WARNING = "warning"        # Approaching threshold
    DRIFT = "drift"            # KPI deviation detected
    CRITICAL = "critical"      # SLA breach imminent


class MacroIntent(str, Enum):
    TELEMETRY = "I_tel"
    ANALYTICS = "I_anl"
    API_GATEWAY = "I_api"


@dataclass
class KPIObservation:
    """A single KPI measurement for a macro-intent."""
    intent: MacroIntent
    kpi_name: str
    value: float
    timestamp: float
    baseline_mean: float
    baseline_std: float

    @property
    def z_score(self) -> float:
        """Deviation in standard deviations from baseline."""
        if self.baseline_std == 0:
            return 0.0
        return (self.value - self.baseline_mean) / self.baseline_std

    @property
    def severity(self) -> DriftSeverity:
        z = abs(self.z_score)
        if z < 1.5:
            return DriftSeverity.NOMINAL
        elif z < 2.5:
            return DriftSeverity.WARNING
        elif z < 3.5:
            return DriftSeverity.DRIFT
        return DriftSeverity.CRITICAL


@dataclass
class CausalLink:
    """A Granger-causal relationship between two macro-intents."""
    cause: MacroIntent
    effect: MacroIntent
    granger_f_statistic: float
    p_value: float
    lag_steps: int
    significant: bool    # p_value < significance_level


@dataclass
class DriftEvent:
    """A detected drift event, with optional causal attribution."""
    affected_intent: MacroIntent
    kpi_name: str
    severity: DriftSeverity
    z_score: float
    timestamp: float
    root_cause_intent: MacroIntent | None = None
    causal_chain: list[MacroIntent] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass
class DriftDetectionResult:
    events: list[DriftEvent]
    causal_links: list[CausalLink]
    most_severe: DriftSeverity
    root_cause_candidates: list[MacroIntent]
    notes: list[str]


class GrangerCausalityEngine:
    """
    Simplified Granger causality engine for real-time multi-intent
    causal co-drift detection.

    In production, this wraps statsmodels.tsa.stattools.grangercausalitytests.
    This implementation provides the structural interface with a heuristic
    fallback for environments without statsmodels installed.
    """

    def __init__(self, significance_level: float = 0.05, max_lag: int = 5) -> None:
        self.significance_level = significance_level
        self.max_lag = max_lag

    def test_causality(
        self,
        cause_series: list[float],
        effect_series: list[float],
        cause: MacroIntent,
        effect: MacroIntent,
    ) -> CausalLink | None:
        """Test whether cause_series Granger-causes effect_series."""
        if len(cause_series) < self.max_lag * 2 + 4:
            return None  # Insufficient data

        try:
            from statsmodels.tsa.stattools import grangercausalitytests
            import warnings

            data = np.column_stack([effect_series, cause_series])
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                results = grangercausalitytests(data, maxlag=self.max_lag, verbose=False)

            # Find best lag (lowest p-value)
            best_lag = min(
                range(1, self.max_lag + 1),
                key=lambda lag: results[lag][0]["ssr_ftest"][1],
            )
            f_stat = results[best_lag][0]["ssr_ftest"][0]
            p_val = results[best_lag][0]["ssr_ftest"][1]

            return CausalLink(
                cause=cause,
                effect=effect,
                granger_f_statistic=float(f_stat),
                p_value=float(p_val),
                lag_steps=best_lag,
                significant=p_val < self.significance_level,
            )
        except ImportError:
            # Fallback heuristic: Pearson correlation with lag shift
            return self._heuristic_causality(cause_series, effect_series, cause, effect)

    def _heuristic_causality(
        self,
        cause_series: list[float],
        effect_series: list[float],
        cause: MacroIntent,
        effect: MacroIntent,
    ) -> CausalLink:
        """Lag-shifted Pearson correlation as a Granger proxy."""
        best_lag = 1
        best_corr = 0.0
        cause_arr = np.array(cause_series)
        effect_arr = np.array(effect_series)

        for lag in range(1, min(self.max_lag + 1, len(cause_arr) - 1)):
            if lag >= len(effect_arr):
                break
            corr = float(np.corrcoef(cause_arr[:-lag], effect_arr[lag:])[0, 1])
            if abs(corr) > abs(best_corr):
                best_corr = corr
                best_lag = lag

        # Map correlation → pseudo F-stat and p-value
        f_stat = abs(best_corr) * 10
        p_val = max(0.001, 1.0 - abs(best_corr))
        return CausalLink(
            cause=cause,
            effect=effect,
            granger_f_statistic=f_stat,
            p_value=p_val,
            lag_steps=best_lag,
            significant=abs(best_corr) > 0.7,
        )


class DriftDetector:
    """
    Real-time multi-intent drift detector.

    Monitors KPI streams across all macro-intents, detects deviations,
    and runs Granger causality analysis to attribute root causes.

    Causal co-drift model for self-driving network:
        I_tel (queue backpressure) → I_anl (throughput ↓) → I_api (latency ↑)
    """

    # Known causal dependency pairs to test (cause → effect)
    CAUSAL_PAIRS: list[tuple[MacroIntent, MacroIntent]] = [
        (MacroIntent.TELEMETRY, MacroIntent.ANALYTICS),
        (MacroIntent.ANALYTICS, MacroIntent.API_GATEWAY),
        (MacroIntent.TELEMETRY, MacroIntent.API_GATEWAY),
    ]

    def __init__(self, granger_engine: GrangerCausalityEngine | None = None) -> None:
        self.granger = granger_engine or GrangerCausalityEngine()
        # Rolling KPI history: intent → kpi_name → list of values
        self._history: dict[MacroIntent, dict[str, list[float]]] = {
            intent: {} for intent in MacroIntent
        }

    def ingest(self, observation: KPIObservation) -> None:
        """Record a KPI observation into rolling history."""
        intent_history = self._history[observation.intent]
        if observation.kpi_name not in intent_history:
            intent_history[observation.kpi_name] = []
        intent_history[observation.kpi_name].append(observation.value)
        # Keep rolling window of 100 samples
        if len(intent_history[observation.kpi_name]) > 100:
            intent_history[observation.kpi_name].pop(0)

    def detect(self, observations: list[KPIObservation]) -> DriftDetectionResult:
        """
        Run drift detection over a batch of current observations.
        Returns drift events with causal attribution.
        """
        for obs in observations:
            self.ingest(obs)

        notes: list[str] = []
        events: list[DriftEvent] = []
        causal_links: list[CausalLink] = []

        # ── Per-intent KPI drift scanning ───────────────────────────────
        for obs in observations:
            if obs.severity != DriftSeverity.NOMINAL:
                event = DriftEvent(
                    affected_intent=obs.intent,
                    kpi_name=obs.kpi_name,
                    severity=obs.severity,
                    z_score=obs.z_score,
                    timestamp=obs.timestamp,
                )
                events.append(event)
                notes.append(
                    f"[{obs.intent.value}] KPI '{obs.kpi_name}' drifted: "
                    f"z={obs.z_score:.2f} ({obs.severity.value})"
                )

        # ── Granger causality sweep ─────────────────────────────────────
        for cause_intent, effect_intent in self.CAUSAL_PAIRS:
            cause_hist = self._history.get(cause_intent, {})
            effect_hist = self._history.get(effect_intent, {})
            if not cause_hist or not effect_hist:
                continue

            # Use first shared KPI or any available series
            for cause_kpi, cause_series in cause_hist.items():
                for effect_kpi, effect_series in effect_hist.items():
                    link = self.granger.test_causality(
                        cause_series, effect_series, cause_intent, effect_intent
                    )
                    if link and link.significant:
                        causal_links.append(link)
                        notes.append(
                            f"Granger causality: {cause_intent.value} → {effect_intent.value} "
                            f"(F={link.granger_f_statistic:.2f}, p={link.p_value:.4f}, lag={link.lag_steps})"
                        )
                    break  # One pair per intent pair is sufficient here
                break

        # ── Root cause attribution ──────────────────────────────────────
        root_causes = self._attribute_root_causes(events, causal_links)
        for event in events:
            if root_causes and event.affected_intent != root_causes[0]:
                event.root_cause_intent = root_causes[0]
                event.causal_chain = root_causes

        most_severe = max(
            (e.severity for e in events),
            default=DriftSeverity.NOMINAL,
            key=lambda s: list(DriftSeverity).index(s),
        )

        return DriftDetectionResult(
            events=events,
            causal_links=causal_links,
            most_severe=most_severe,
            root_cause_candidates=root_causes,
            notes=notes,
        )

    def _attribute_root_causes(
        self,
        events: list[DriftEvent],
        links: list[CausalLink],
    ) -> list[MacroIntent]:
        """
        Simple root-cause attribution:
        The root cause is the intent that appears as a Granger-cause
        but not as a Granger-effect of any other drifting intent.
        """
        drifted = {e.affected_intent for e in events}
        if not drifted:
            return []

        # Intents that are caused by someone else
        effects_in_links = {link.effect for link in links if link.significant}
        # Root candidates: drifted AND not an effect of another drifted intent
        candidates = [i for i in drifted if i not in effects_in_links]
        return candidates if candidates else list(drifted)
