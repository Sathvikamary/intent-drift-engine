"""
Policy Evaluation Engine.

Evaluates incoming action requests against a structured policy store.
Policies define allow/deny rules, conditions, and risk-tier constraints
for role-domain-action triples.

Supports:
  - Attribute-based access control (ABAC) style conditions
  - Risk-tier gating (HIGH-risk requires explicit policy allow)
  - Policy chaining (first-match-wins)
  - Audit-ready decision records
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class PolicyEffect(str, Enum):
    ALLOW = "allow"
    DENY = "deny"


class PolicyConditionOperator(str, Enum):
    EQUALS = "eq"
    NOT_EQUALS = "neq"
    GREATER_THAN = "gt"
    LESS_THAN = "lt"
    IN = "in"
    NOT_IN = "not_in"
    EXISTS = "exists"


@dataclass
class PolicyCondition:
    """A single attribute condition in a policy rule."""
    attribute: str
    operator: PolicyConditionOperator
    value: Any

    def evaluate(self, context: dict[str, Any]) -> bool:
        attr_val = context.get(self.attribute)
        op = self.operator
        if op == PolicyConditionOperator.EXISTS:
            return attr_val is not None
        if attr_val is None:
            return False
        if op == PolicyConditionOperator.EQUALS:
            return attr_val == self.value
        if op == PolicyConditionOperator.NOT_EQUALS:
            return attr_val != self.value
        if op == PolicyConditionOperator.GREATER_THAN:
            return float(attr_val) > float(self.value)
        if op == PolicyConditionOperator.LESS_THAN:
            return float(attr_val) < float(self.value)
        if op == PolicyConditionOperator.IN:
            return attr_val in self.value
        if op == PolicyConditionOperator.NOT_IN:
            return attr_val not in self.value
        return False


@dataclass
class PolicyRule:
    """A single policy rule: if conditions match, apply effect."""
    rule_id: str
    effect: PolicyEffect
    roles: list[str]              # Matching roles (empty = wildcard)
    domains: list[str]            # Matching domains (empty = wildcard)
    actions: list[str]            # Matching actions (empty = wildcard)
    conditions: list[PolicyCondition] = field(default_factory=list)
    priority: int = 100           # Lower = higher priority
    description: str = ""

    def matches(
        self,
        role: str,
        domain: str,
        action: str,
        context: dict[str, Any],
    ) -> bool:
        """Return True if this rule applies to the given request."""
        if self.roles and role not in self.roles:
            return False
        if self.domains and domain not in self.domains:
            return False
        if self.actions and action not in self.actions:
            return False
        return all(cond.evaluate(context) for cond in self.conditions)


@dataclass
class PolicyDecision:
    """Outcome of a policy evaluation."""
    effect: PolicyEffect
    matched_rule_id: str | None
    role: str
    domain: str
    action: str
    context: dict[str, Any]
    timestamp: float = field(default_factory=time.time)
    notes: list[str] = field(default_factory=list)

    @property
    def allowed(self) -> bool:
        return self.effect == PolicyEffect.ALLOW


class PolicyEngine:
    """
    Evaluates action requests against a prioritized rule set.

    First-match-wins: rules are sorted by priority ascending.
    Default effect when no rule matches: DENY.
    """

    def __init__(
        self,
        default_effect: PolicyEffect = PolicyEffect.DENY,
    ) -> None:
        self._rules: list[PolicyRule] = []
        self.default_effect = default_effect

    def add_rule(self, rule: PolicyRule) -> None:
        self._rules.append(rule)
        self._rules.sort(key=lambda r: r.priority)

    def add_rules(self, rules: list[PolicyRule]) -> None:
        for r in rules:
            self.add_rule(r)

    def evaluate(
        self,
        role: str,
        domain: str,
        action: str,
        context: dict[str, Any] | None = None,
    ) -> PolicyDecision:
        ctx = context or {}
        for rule in self._rules:
            if rule.matches(role, domain, action, ctx):
                return PolicyDecision(
                    effect=rule.effect,
                    matched_rule_id=rule.rule_id,
                    role=role,
                    domain=domain,
                    action=action,
                    context=ctx,
                    notes=[f"Matched rule '{rule.rule_id}': {rule.description}"],
                )

        # No rule matched — apply default
        return PolicyDecision(
            effect=self.default_effect,
            matched_rule_id=None,
            role=role,
            domain=domain,
            action=action,
            context=ctx,
            notes=["No matching rule — default effect applied."],
        )

    def bulk_evaluate(
        self,
        role: str,
        domain: str,
        actions: list[str],
        context: dict[str, Any] | None = None,
    ) -> dict[str, PolicyDecision]:
        """Evaluate multiple actions in one call."""
        return {a: self.evaluate(role, domain, a, context) for a in actions}

    def rule_count(self) -> int:
        return len(self._rules)


# ---------------------------------------------------------------------------
# Pre-built baseline policy set for the reference self-driving network
# ---------------------------------------------------------------------------

def build_baseline_policy_engine() -> PolicyEngine:
    """
    Construct the baseline policy engine for the intent-drift-engine.

    Roles:
        network-ops    : Full read + limited write on routing and telemetry
        sre-tier2      : Read-only on all domains; write on telemetry
        sre-tier1      : Read-only everywhere
        analytics-agent: Read-only on analytics and telemetry KPIs
        admin          : Unrestricted
    """
    engine = PolicyEngine(default_effect=PolicyEffect.DENY)
    engine.add_rules([
        PolicyRule(
            rule_id="admin-allow-all",
            effect=PolicyEffect.ALLOW,
            roles=["admin"],
            domains=[],
            actions=[],
            priority=1,
            description="Admin has unrestricted access",
        ),
        PolicyRule(
            rule_id="netops-read-all",
            effect=PolicyEffect.ALLOW,
            roles=["network-ops"],
            domains=[],
            actions=["read_metrics", "read_telemetry", "read_routing", "read_config"],
            priority=10,
            description="Network-ops can read all domains",
        ),
        PolicyRule(
            rule_id="netops-write-routing",
            effect=PolicyEffect.ALLOW,
            roles=["network-ops"],
            domains=["routing", "api-gateway"],
            actions=["update_routing_policy", "restart_service", "scale_replica"],
            priority=11,
            description="Network-ops write on routing and API gateway",
        ),
        PolicyRule(
            rule_id="sre2-read-all",
            effect=PolicyEffect.ALLOW,
            roles=["sre-tier2"],
            domains=[],
            actions=["read_metrics", "read_telemetry", "read_routing", "read_config"],
            priority=20,
            description="SRE Tier-2 read everywhere",
        ),
        PolicyRule(
            rule_id="sre2-write-telemetry",
            effect=PolicyEffect.ALLOW,
            roles=["sre-tier2"],
            domains=["telemetry"],
            actions=["update_telemetry_config", "flush_queue"],
            priority=21,
            description="SRE Tier-2 write on telemetry",
        ),
        PolicyRule(
            rule_id="sre1-read-all",
            effect=PolicyEffect.ALLOW,
            roles=["sre-tier1"],
            domains=[],
            actions=["read_metrics", "read_telemetry", "read_config"],
            priority=30,
            description="SRE Tier-1 read-only",
        ),
        PolicyRule(
            rule_id="analytics-agent-read",
            effect=PolicyEffect.ALLOW,
            roles=["analytics-agent"],
            domains=["analytics", "telemetry"],
            actions=["read_metrics", "read_telemetry", "read_inference_results"],
            priority=40,
            description="Analytics agent read-only on analytics/telemetry",
        ),
        PolicyRule(
            rule_id="deny-all-destructive",
            effect=PolicyEffect.DENY,
            roles=[],
            domains=[],
            actions=["delete_config", "factory_reset", "wipe_telemetry"],
            priority=2,
            description="Destructive actions blocked for all non-admin roles",
            conditions=[
                PolicyCondition(
                    attribute="role",
                    operator=PolicyConditionOperator.NOT_EQUALS,
                    value="admin",
                )
            ],
        ),
    ])
    return engine
