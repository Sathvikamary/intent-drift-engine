"""
Integration tests — Intent Compiler end-to-end.
"""

import pytest
from src.compiler.compiler import (
    CompilationDecision,
    IntentCompilationRequest,
    IntentCompiler,
)
from src.compiler.evidentiary import ContextSource
from src.compiler.institutional import AuthorizationLevel, PolicyClearance
from src.compiler.procedural import ExecutionPath, ExecutionStep, ToolStatus
import time


@pytest.fixture
def compiler() -> IntentCompiler:
    return IntentCompiler()


def _fresh_source(source_id: str, content: str) -> ContextSource:
    src = ContextSource(
        source_id=source_id,
        content=content,
        timestamp=time.time(),
        admissible=True,
        max_age_seconds=300.0,
    )
    src.checksum = src.compute_checksum()
    return src


def _compliant_path(path_id: str) -> ExecutionPath:
    return ExecutionPath(
        path_id=path_id,
        steps=[
            ExecutionStep(
                step_id="s1",
                tool_name="metric_reader",
                tool_status=ToolStatus.AVAILABLE,
                policy_compliant=True,
                auditable=True,
                estimated_risk=0.05,
            )
        ],
        policy_validated=True,
        requires_side_channel=False,
    )


def _full_clearance(role: str, domain: str, actions: list[str]) -> PolicyClearance:
    return PolicyClearance(
        clearance_id="clr-001",
        role=role,
        domain=domain,
        actions=actions,
        level=AuthorizationLevel.FULL,
    )


def test_compile_proceeds_with_all_gaps_closed(compiler: IntentCompiler):
    request = IntentCompilationRequest(
        intent_id="test-001",
        intent_text="Ensure API gateway p99 latency < 50ms with SLA threshold = 99%",
        role="network-ops",
        domain="api-gateway",
        required_actions=["read_metrics"],
        context_sources=[_fresh_source("telemetry-feed", "latency data")],
        candidate_paths=[_compliant_path("path-A")],
        clearances=[_full_clearance("network-ops", "api-gateway", ["read_metrics"])],
        closure_threshold=0.4,
    )
    result = compiler.compile(request)
    assert result.decision in (CompilationDecision.PROCEED, CompilationDecision.DEFER)
    assert result.gap_vector.c_sem <= 1.0
    assert result.compilation_time_ms > 0


def test_compile_rejects_on_denied_clearance(compiler: IntentCompiler):
    denied = PolicyClearance(
        clearance_id="clr-denied",
        role="read-only",
        domain="api-gateway",
        actions=[],
        level=AuthorizationLevel.DENIED,
    )
    request = IntentCompilationRequest(
        intent_id="test-002",
        intent_text="Modify routing table for api-gateway",
        role="read-only",
        domain="api-gateway",
        required_actions=["update_routing_policy"],
        clearances=[denied],
        closure_threshold=0.2,
    )
    result = compiler.compile(request)
    assert result.decision == CompilationDecision.REJECT


def test_compile_overclose_risk_when_vague_but_path_available(compiler: IntentCompiler):
    """Vague intent + no context + available path → OVERCLOSE_RISK."""
    request = IntentCompilationRequest(
        intent_id="test-003",
        intent_text="Make the network better",  # Very vague
        role="network-ops",
        domain="routing",
        required_actions=["update_routing_policy"],
        context_sources=[],     # No evidence
        candidate_paths=[_compliant_path("path-B")],
        clearances=[_full_clearance("network-ops", "routing", ["update_routing_policy"])],
        closure_threshold=0.2,
    )
    result = compiler.compile(request)
    assert result.decision in (
        CompilationDecision.OVERCLOSE_RISK,
        CompilationDecision.DEFER,
    )


def test_gap_vector_components_in_bounds(compiler: IntentCompiler):
    request = IntentCompilationRequest(
        intent_id="test-004",
        intent_text="Ensure SLA threshold = 99.9% for telemetry pipeline",
        role="sre",
        domain="telemetry",
        required_actions=["read_telemetry"],
        closure_threshold=0.3,
    )
    result = compiler.compile(request)
    gv = result.gap_vector
    assert 0.0 <= gv.c_sem <= 1.0
    assert 0.0 <= gv.c_evid <= 1.0
    assert 0.0 <= gv.c_proc <= 1.0
    assert 0.0 <= gv.c_inst <= 1.0
