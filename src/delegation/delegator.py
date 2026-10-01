"""
Adaptive Delegator — orchestrates delegation envelope issuance
and adaptive adjustment in response to runtime conditions.

Responsibilities:
  1. Issue new delegation envelopes after policy evaluation.
  2. Adaptively shrink / revoke envelopes when risk signals escalate.
  3. Emit delegation events to an audit sink.
  4. Prevent misdelegation through gap-vector gating.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from src.delegation.envelope import (
    ActionBudget,
    DelegationEnvelope,
    EnvelopeState,
    RiskTier,
)
from src.delegation.policy import PolicyDecision, PolicyEffect, PolicyEngine
from src.compiler.gap_vector import ClosureGapVector


@dataclass
class DelegationRequest:
    """A request to issue a delegation envelope."""
    requester_role: str
    domain: str
    requested_actions: list[str]
    gap_vector: ClosureGapVector | None = None
    max_duration_seconds: float = 300.0
    risk_tier: RiskTier = RiskTier.LOW
    context: dict[str, Any] = field(default_factory=dict)
    action_budgets: dict[str, int] | None = None   # action → max invocations


@dataclass
class DelegationResponse:
    """Result of a delegation request."""
    granted: bool
    envelope: DelegationEnvelope | None
    denied_actions: list[str]
    policy_decisions: dict[str, PolicyDecision]
    gap_block_reason: str | None
    notes: list[str]


class AdaptiveDelegator:
    """
    Issues and manages delegation envelopes with:
      - Policy gating (via PolicyEngine)
      - Closure-gap vector gating (blocks delegation if gaps too high)
      - Adaptive envelope shrinkage under escalating risk
      - Full audit trail
    """

    # Closure gap thresholds per risk tier
    GAP_THRESHOLDS: dict[RiskTier, float] = {
        RiskTier.LOW:    0.6,   # Permissive — allow with moderate gaps
        RiskTier.MEDIUM: 0.35,  # Moderate — require reasonable closure
        RiskTier.HIGH:   0.15,  # Strict — near-fully closed gaps required
    }

    def __init__(
        self,
        policy_engine: PolicyEngine,
        gap_threshold_override: dict[RiskTier, float] | None = None,
    ) -> None:
        self._policy = policy_engine
        self._active_envelopes: dict[str, DelegationEnvelope] = {}
        self._audit: list[dict[str, Any]] = []

        if gap_threshold_override:
            self.GAP_THRESHOLDS = {**self.GAP_THRESHOLDS, **gap_threshold_override}

    # ------------------------------------------------------------------ #
    # Envelope issuance                                                    #
    # ------------------------------------------------------------------ #

    def request_envelope(self, req: DelegationRequest) -> DelegationResponse:
        """
        Evaluate a delegation request and issue an envelope if permitted.

        Decision flow:
          1. Check closure-gap vector — block if gaps exceed tier threshold.
          2. Evaluate each requested action against policy engine.
          3. Issue envelope for the allowed action subset.
          4. Activate and register envelope.
        """
        notes: list[str] = []
        denied_actions: list[str] = []

        # ── Gap vector gate ─────────────────────────────────────────────
        if req.gap_vector is not None:
            gap_block = self._check_gap_threshold(req.gap_vector, req.risk_tier)
            if gap_block:
                self._audit_event("delegation_blocked_by_gap", req=req, reason=gap_block)
                return DelegationResponse(
                    granted=False,
                    envelope=None,
                    denied_actions=req.requested_actions,
                    policy_decisions={},
                    gap_block_reason=gap_block,
                    notes=[gap_block],
                )

        # ── Policy evaluation ───────────────────────────────────────────
        decisions = self._policy.bulk_evaluate(
            role=req.requester_role,
            domain=req.domain,
            actions=req.requested_actions,
            context=req.context,
        )
        allowed_actions = [a for a, d in decisions.items() if d.allowed]
        denied_actions = [a for a, d in decisions.items() if not d.allowed]

        if denied_actions:
            notes.append(f"Policy denied actions: {denied_actions}")
        if not allowed_actions:
            self._audit_event("delegation_blocked_by_policy", req=req)
            return DelegationResponse(
                granted=False,
                envelope=None,
                denied_actions=denied_actions,
                policy_decisions=decisions,
                gap_block_reason=None,
                notes=notes + ["All requested actions denied by policy."],
            )

        # ── Build action budgets ────────────────────────────────────────
        budgets: dict[str, ActionBudget] = {}
        if req.action_budgets:
            for action, max_inv in req.action_budgets.items():
                if action in allowed_actions:
                    budgets[action] = ActionBudget(action=action, max_invocations=max_inv)

        # ── Issue envelope ──────────────────────────────────────────────
        duration = self._adaptive_duration(req)
        envelope = DelegationEnvelope(
            role=req.requester_role,
            domain=req.domain,
            permitted_actions=allowed_actions,
            action_budgets=budgets,
            risk_tier=req.risk_tier,
            max_duration_seconds=duration,
        )
        envelope.activate()
        self._active_envelopes[envelope.envelope_id] = envelope

        if duration < req.max_duration_seconds:
            notes.append(
                f"Envelope duration adaptively reduced: "
                f"{req.max_duration_seconds:.0f}s → {duration:.0f}s "
                f"(risk_tier={req.risk_tier.value})"
            )

        self._audit_event(
            "envelope_issued",
            envelope_id=envelope.envelope_id,
            role=req.requester_role,
            allowed=allowed_actions,
            denied=denied_actions,
        )
        notes.append(f"Envelope '{envelope.envelope_id}' issued with {len(allowed_actions)} permitted action(s).")

        return DelegationResponse(
            granted=True,
            envelope=envelope,
            denied_actions=denied_actions,
            policy_decisions=decisions,
            gap_block_reason=None,
            notes=notes,
        )

    # ------------------------------------------------------------------ #
    # Runtime adaptation                                                   #
    # ------------------------------------------------------------------ #

    def shrink_envelope(
        self,
        envelope_id: str,
        new_actions: list[str],
        reason: str = "risk escalation",
    ) -> bool:
        """
        Adaptively shrink an active envelope's permitted action set.
        Used when real-time risk signals elevate (e.g., drift detected).
        """
        env = self._active_envelopes.get(envelope_id)
        if not env or not env.is_valid:
            return False
        removed = [a for a in env.permitted_actions if a not in new_actions]
        env.permitted_actions = [a for a in env.permitted_actions if a in new_actions]
        env._log("shrunk", removed_actions=removed, reason=reason)
        self._audit_event("envelope_shrunk", envelope_id=envelope_id, removed=removed, reason=reason)
        return True

    def revoke_envelope(self, envelope_id: str, reason: str = "explicit revocation") -> bool:
        """Revoke an active envelope immediately."""
        env = self._active_envelopes.get(envelope_id)
        if not env or env.state == EnvelopeState.REVOKED:
            return False
        env.revoke(reason)
        self._audit_event("envelope_revoked", envelope_id=envelope_id, reason=reason)
        return True

    def revoke_all_for_role(self, role: str, reason: str) -> int:
        """Revoke all active envelopes belonging to a role. Returns count revoked."""
        count = 0
        for env in list(self._active_envelopes.values()):
            if env.role == role and env.is_valid:
                env.revoke(reason)
                count += 1
        self._audit_event("bulk_revoke", role=role, count=count, reason=reason)
        return count

    # ------------------------------------------------------------------ #
    # Adaptive duration calculation                                        #
    # ------------------------------------------------------------------ #

    def _adaptive_duration(self, req: DelegationRequest) -> float:
        """
        Compute an adaptive envelope duration based on risk tier and
        gap vector magnitude. Higher risk / larger gaps → shorter windows.
        """
        base = req.max_duration_seconds
        tier_factor = {RiskTier.LOW: 1.0, RiskTier.MEDIUM: 0.7, RiskTier.HIGH: 0.4}
        duration = base * tier_factor[req.risk_tier]

        if req.gap_vector is not None:
            norm = req.gap_vector.l2_norm()          # [0, 2.0]
            gap_penalty = 1.0 - (norm / 2.0) * 0.3  # Max 30% reduction
            duration *= max(gap_penalty, 0.5)

        return max(30.0, duration)   # Minimum 30 seconds

    # ------------------------------------------------------------------ #
    # Gap threshold gate                                                   #
    # ------------------------------------------------------------------ #

    def _check_gap_threshold(
        self,
        gap: ClosureGapVector,
        tier: RiskTier,
    ) -> str | None:
        """Return a block reason string if gap exceeds tier threshold, else None."""
        threshold = self.GAP_THRESHOLDS[tier]
        violations: list[str] = []
        for name, val in [
            ("semantic", gap.c_sem),
            ("evidentiary", gap.c_evid),
            ("procedural", gap.c_proc),
            ("institutional", gap.c_inst),
        ]:
            if val > threshold:
                violations.append(f"{name}={val:.2f}")
        if violations:
            return (
                f"Gap vector exceeds {tier.value}-risk threshold ({threshold}): "
                + ", ".join(violations)
            )
        return None

    # ------------------------------------------------------------------ #
    # Audit & queries                                                      #
    # ------------------------------------------------------------------ #

    def get_active_envelopes(self) -> list[DelegationEnvelope]:
        return [e for e in self._active_envelopes.values() if e.is_valid]

    def get_envelope(self, envelope_id: str) -> DelegationEnvelope | None:
        return self._active_envelopes.get(envelope_id)

    def audit_trail(self) -> list[dict[str, Any]]:
        return list(self._audit)

    def _audit_event(self, event: str, **kwargs: Any) -> None:
        self._audit.append({"event": event, "ts": time.time(), **kwargs})
