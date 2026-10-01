"""
Integration tests — MILD State Machine and Adaptive Delegator.
"""
import time
import pytest

from src.drift.state_machine import MILDStateMachine, IntentState
from src.drift.detector import KPIObservation, MacroIntent, DriftSeverity
from src.delegation.delegator import AdaptiveDelegator, DelegationRequest
from src.delegation.envelope import RiskTier
from src.delegation.policy import build_baseline_policy_engine
from src.compiler.gap_vector import ClosureGapVector


# ── MILD State Machine Tests ───────────────────────────────────────────────

@pytest.fixture
def mild() -> MILDStateMachine:
    return MILDStateMachine()


def _obs(intent: MacroIntent, kpi: str, value: float, mean: float, std: float) -> KPIObservation:
    return KPIObservation(
        intent=intent,
        kpi_name=kpi,
        value=value,
        timestamp=time.time(),
        baseline_mean=mean,
        baseline_std=std,
    )


def test_mild_initializes_all_intents_active(mild: MILDStateMachine):
    for intent in MacroIntent:
        assert mild.get_state(intent).state == IntentState.ACTIVE


def test_mild_nominal_observations_stay_active(mild: MILDStateMachine):
    obs = [
        _obs(MacroIntent.TELEMETRY, "queue_depth", 10.0, 10.0, 2.0),
        _obs(MacroIntent.ANALYTICS, "throughput", 500.0, 500.0, 20.0),
        _obs(MacroIntent.API_GATEWAY, "p99_latency", 45.0, 45.0, 5.0),
    ]
    snapshot = mild.tick(obs)
    assert snapshot["system_health"] == "NOMINAL"


def test_mild_critical_drift_triggers_state_change(mild: MILDStateMachine):
    # Queue depth 5 std deviations above baseline → critical
    obs = [_obs(MacroIntent.TELEMETRY, "queue_depth", 110.0, 10.0, 2.0)]
    snapshot = mild.tick(obs)
    tel_state = mild.get_state(MacroIntent.TELEMETRY).state
    assert tel_state in (IntentState.DRIFTING, IntentState.REMEDIATING, IntentState.VIOLATED)


def test_mild_causal_co_drift_propagates(mild: MILDStateMachine):
    """Severe drift in Telemetry should propagate to Analytics (causal co-drift)."""
    for _ in range(3):
        obs = [_obs(MacroIntent.TELEMETRY, "queue_depth", 200.0, 10.0, 2.0)]
        mild.tick(obs)

    # After repeated critical drift in I_tel, I_anl should drift too
    anl_state = mild.get_state(MacroIntent.ANALYTICS).state
    assert anl_state != IntentState.ACTIVE, (
        f"Expected co-drift in Analytics, but state is {anl_state}"
    )


def test_mild_recovery_returns_to_active(mild: MILDStateMachine):
    # Cause drift
    mild.tick([_obs(MacroIntent.API_GATEWAY, "p99", 500.0, 50.0, 5.0)])
    # Recover
    for _ in range(3):
        mild.tick([_obs(MacroIntent.API_GATEWAY, "p99", 52.0, 50.0, 5.0)])
    api_state = mild.get_state(MacroIntent.API_GATEWAY).state
    assert api_state in (IntentState.ACTIVE, IntentState.DRIFTING)


def test_mild_system_health_reflects_worst_state(mild: MILDStateMachine):
    mild.tick([_obs(MacroIntent.TELEMETRY, "q", 1000.0, 10.0, 2.0)])
    health = mild.system_health()
    assert health in ("WARNING", "DEGRADED", "CRITICAL")


# ── Adaptive Delegator Tests ───────────────────────────────────────────────

@pytest.fixture
def delegator() -> AdaptiveDelegator:
    return AdaptiveDelegator(policy_engine=build_baseline_policy_engine())


def test_delegation_granted_for_valid_role(delegator: AdaptiveDelegator):
    req = DelegationRequest(
        requester_role="network-ops",
        domain="routing",
        requested_actions=["read_metrics", "update_routing_policy"],
        risk_tier=RiskTier.MEDIUM,
    )
    resp = delegator.request_envelope(req)
    assert resp.granted
    assert resp.envelope is not None
    assert resp.envelope.is_valid


def test_delegation_denied_for_unauthorized_action(delegator: AdaptiveDelegator):
    req = DelegationRequest(
        requester_role="sre-tier1",
        domain="routing",
        requested_actions=["update_routing_policy"],  # SRE tier-1 read-only
        risk_tier=RiskTier.LOW,
    )
    resp = delegator.request_envelope(req)
    assert not resp.granted
    assert "update_routing_policy" in resp.denied_actions


def test_delegation_blocked_by_high_gap_vector(delegator: AdaptiveDelegator):
    req = DelegationRequest(
        requester_role="network-ops",
        domain="routing",
        requested_actions=["read_metrics"],
        risk_tier=RiskTier.HIGH,
        gap_vector=ClosureGapVector(c_sem=0.9, c_evid=0.8, c_proc=0.7, c_inst=0.6),
    )
    resp = delegator.request_envelope(req)
    assert not resp.granted
    assert resp.gap_block_reason is not None


def test_delegation_low_risk_allows_moderate_gaps(delegator: AdaptiveDelegator):
    req = DelegationRequest(
        requester_role="network-ops",
        domain="routing",
        requested_actions=["read_metrics"],
        risk_tier=RiskTier.LOW,
        gap_vector=ClosureGapVector(c_sem=0.5, c_evid=0.5, c_proc=0.5, c_inst=0.5),
    )
    resp = delegator.request_envelope(req)
    assert resp.granted  # Low risk threshold = 0.6 — gaps of 0.5 pass


def test_envelope_shrink_reduces_actions(delegator: AdaptiveDelegator):
    req = DelegationRequest(
        requester_role="network-ops",
        domain="routing",
        requested_actions=["read_metrics", "update_routing_policy"],
        risk_tier=RiskTier.LOW,
    )
    resp = delegator.request_envelope(req)
    assert resp.envelope is not None
    env_id = resp.envelope.envelope_id

    delegator.shrink_envelope(env_id, ["read_metrics"], reason="drift detected")
    env = delegator.get_envelope(env_id)
    assert env is not None
    assert "update_routing_policy" not in env.permitted_actions


def test_revoke_all_for_role(delegator: AdaptiveDelegator):
    for _ in range(3):
        delegator.request_envelope(DelegationRequest(
            requester_role="network-ops",
            domain="routing",
            requested_actions=["read_metrics"],
            risk_tier=RiskTier.LOW,
        ))
    revoked = delegator.revoke_all_for_role("network-ops", "emergency shutdown")
    assert revoked == 3
    assert len(delegator.get_active_envelopes()) == 0
