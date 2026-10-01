"""
Institutional Gap Analyzer — C_inst,t component.

Captures the absence of explicit role authorization or policy clearance
for the targeted domain, risking irreversible actions outside role boundaries.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class AuthorizationLevel(str, Enum):
    FULL = "full"           # Explicit clearance for all required actions
    SCOPED = "scoped"       # Clearance for a subset of required actions
    PENDING = "pending"     # Authorization request submitted, not yet granted
    DENIED = "denied"       # Explicitly denied
    UNKNOWN = "unknown"     # No authorization record found


@dataclass
class PolicyClearance:
    """A single policy clearance record for a role-domain pair."""
    clearance_id: str
    role: str
    domain: str                   # Target resource domain (e.g., "routing", "telemetry")
    actions: list[str]            # Authorized action verbs
    level: AuthorizationLevel
    expires_at: float | None = None   # Unix epoch — None = no expiry
    constraints: dict[str, Any] | None = None


@dataclass
class InstitutionalAnalysisResult:
    c_inst: float
    authorization_level: AuthorizationLevel
    covered_actions: list[str]
    uncovered_actions: list[str]
    notes: list[str]
    details: dict[str, Any]


class InstitutionalGapAnalyzer:
    """
    Analyzes the institutional closure gap C_inst,t.

    Checks whether the acting role holds the necessary policy clearances
    for all actions required to execute the compiled intent.
    """

    LEVEL_GAP_MAP: dict[AuthorizationLevel, float] = {
        AuthorizationLevel.FULL: 0.0,
        AuthorizationLevel.SCOPED: 0.4,
        AuthorizationLevel.PENDING: 0.7,
        AuthorizationLevel.DENIED: 1.0,
        AuthorizationLevel.UNKNOWN: 0.9,
    }

    def analyze(
        self,
        role: str,
        domain: str,
        required_actions: list[str],
        clearances: list[PolicyClearance],
        current_time: float | None = None,
    ) -> InstitutionalAnalysisResult:
        import time as _time
        now = current_time if current_time is not None else _time.time()
        notes: list[str] = []

        if not clearances:
            notes.append(f"No policy clearances found for role '{role}' in domain '{domain}'.")
            return InstitutionalAnalysisResult(
                c_inst=1.0,
                authorization_level=AuthorizationLevel.UNKNOWN,
                covered_actions=[],
                uncovered_actions=required_actions,
                notes=notes,
                details={"reason": "no_clearances"},
            )

        # Filter: must match role and domain, must not be expired
        valid: list[PolicyClearance] = []
        for clr in clearances:
            if clr.role != role or clr.domain != domain:
                continue
            if clr.expires_at is not None and clr.expires_at < now:
                notes.append(
                    f"Clearance '{clr.clearance_id}' for role '{role}' expired."
                )
                continue
            if clr.level == AuthorizationLevel.DENIED:
                notes.append(f"Clearance '{clr.clearance_id}' is explicitly denied.")
                continue
            valid.append(clr)

        if not valid:
            notes.append(f"No valid clearances for role '{role}' in domain '{domain}'.")
            return InstitutionalAnalysisResult(
                c_inst=1.0,
                authorization_level=AuthorizationLevel.UNKNOWN,
                covered_actions=[],
                uncovered_actions=required_actions,
                notes=notes,
                details={"reason": "no_valid_clearances"},
            )

        # Aggregate authorized actions
        authorized_actions: set[str] = set()
        highest_level = AuthorizationLevel.UNKNOWN
        level_order = [
            AuthorizationLevel.FULL,
            AuthorizationLevel.SCOPED,
            AuthorizationLevel.PENDING,
            AuthorizationLevel.UNKNOWN,
            AuthorizationLevel.DENIED,
        ]
        for clr in valid:
            authorized_actions.update(clr.actions)
            if level_order.index(clr.level) < level_order.index(highest_level):
                highest_level = clr.level

        covered = [a for a in required_actions if a in authorized_actions]
        uncovered = [a for a in required_actions if a not in authorized_actions]

        if uncovered:
            notes.append(f"Unauthorized actions: {uncovered}.")
            # Downgrade effective level if actions uncovered
            if highest_level == AuthorizationLevel.FULL:
                highest_level = AuthorizationLevel.SCOPED

        base_gap = self.LEVEL_GAP_MAP[highest_level]
        # Proportional penalty for uncovered actions
        if required_actions:
            coverage_ratio = len(covered) / len(required_actions)
            gap = base_gap + (1 - coverage_ratio) * 0.3
        else:
            gap = base_gap

        return InstitutionalAnalysisResult(
            c_inst=float(min(gap, 1.0)),
            authorization_level=highest_level,
            covered_actions=covered,
            uncovered_actions=uncovered,
            notes=notes,
            details={
                "valid_clearances": len(valid),
                "authorized_action_set": list(authorized_actions),
            },
        )

    def score(
        self,
        role: str,
        domain: str,
        required_actions: list[str],
        clearances: list[PolicyClearance],
    ) -> float:
        return self.analyze(role, domain, required_actions, clearances).c_inst
