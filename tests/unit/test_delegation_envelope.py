"""
Unit tests — Delegation Envelope.
"""
import time
import pytest
from src.delegation.envelope import (
    ActionBudget,
    DelegationEnvelope,
    EnvelopeState,
    RiskTier,
)


@pytest.fixture
def active_envelope() -> DelegationEnvelope:
    env = DelegationEnvelope(
        role="network-ops",
        domain="routing",
        permitted_actions=["read_metrics", "update_routing_policy"],
        risk_tier=RiskTier.MEDIUM,
        max_duration_seconds=60.0,
    )
    env.activate()
    return env


def test_envelope_starts_active(active_envelope: DelegationEnvelope):
    assert active_envelope.state == EnvelopeState.ACTIVE
    assert active_envelope.is_valid


def test_can_perform_permitted_action(active_envelope: DelegationEnvelope):
    ok, reason = active_envelope.can_perform("read_metrics")
    assert ok
    assert reason == "permitted"


def test_cannot_perform_unlisted_action(active_envelope: DelegationEnvelope):
    ok, reason = active_envelope.can_perform("delete_config")
    assert not ok
    assert "not in permitted action set" in reason


def test_revoke_makes_invalid(active_envelope: DelegationEnvelope):
    active_envelope.revoke("test")
    assert active_envelope.state == EnvelopeState.REVOKED
    assert not active_envelope.is_valid


def test_action_budget_exhaustion():
    env = DelegationEnvelope(
        role="sre-tier1",
        domain="telemetry",
        permitted_actions=["read_metrics"],
        action_budgets={"read_metrics": ActionBudget("read_metrics", max_invocations=2)},
        max_duration_seconds=300.0,
    )
    env.activate()
    assert env.consume_action("read_metrics")
    assert env.consume_action("read_metrics")
    assert not env.consume_action("read_metrics")  # Budget exhausted


def test_sub_delegation_restricts_actions(active_envelope: DelegationEnvelope):
    child = active_envelope.delegate(
        sub_role="analytics-agent",
        sub_actions=["read_metrics"],
        max_duration_seconds=30.0,
    )
    assert child.role == "analytics-agent"
    assert child.permitted_actions == ["read_metrics"]
    assert child.parent_envelope_id == active_envelope.envelope_id


def test_sub_delegation_cannot_exceed_parent_permissions(active_envelope: DelegationEnvelope):
    with pytest.raises(ValueError, match="Cannot delegate actions not in parent envelope"):
        active_envelope.delegate("other", ["delete_config"])


def test_audit_log_populated(active_envelope: DelegationEnvelope):
    active_envelope.consume_action("read_metrics")
    active_envelope.revoke("test")
    events = [entry["event"] for entry in active_envelope.audit_log]
    assert "activated" in events
    assert "action_consumed" in events
    assert "revoked" in events


def test_remaining_seconds_decreases(active_envelope: DelegationEnvelope):
    r1 = active_envelope.remaining_seconds
    time.sleep(0.1)
    r2 = active_envelope.remaining_seconds
    assert r1 is not None and r2 is not None
    assert r1 > r2
