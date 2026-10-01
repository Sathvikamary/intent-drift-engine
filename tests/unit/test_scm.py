"""
Unit tests — Structural Causal Model (SCM) builder.
"""
import pytest
from src.drift.scm import SCMBuilder, CausalNode, CausalEdge, NodeType, build_network_scm


@pytest.fixture
def network_scm() -> SCMBuilder:
    return build_network_scm()


def test_scm_has_correct_node_count(network_scm: SCMBuilder):
    assert network_scm.node_count() == 9


def test_scm_is_dag(network_scm: SCMBuilder):
    assert network_scm.is_acyclic()


def test_ancestors_of_api_latency_includes_telemetry(network_scm: SCMBuilder):
    ancestors = network_scm.ancestors_of("api_p99_latency")
    assert "tel_queue_depth" in ancestors or "tel_ingest_lag" in ancestors


def test_causal_path_tel_to_api(network_scm: SCMBuilder):
    path = network_scm.causal_path("tel_ingest_lag", "api_p99_latency")
    assert path is not None
    assert path[0] == "tel_ingest_lag"
    assert path[-1] == "api_p99_latency"


def test_root_cause_candidates_identifies_upstream(network_scm: SCMBuilder):
    drifted = ["tel_queue_depth", "anl_inference_tput", "api_p99_latency"]
    candidates = network_scm.root_cause_candidates(drifted)
    assert "tel_queue_depth" in candidates


def test_intervention_propagates_downstream(network_scm: SCMBuilder):
    result = network_scm.intervene("tel_ingest_lag", delta=2.0)
    assert result.intervened_node == "tel_ingest_lag"
    assert len(result.predicted_effects) > 0
    # Downstream nodes should be affected
    assert any("anl" in k or "api" in k for k in result.predicted_effects)


def test_intervention_explanation_non_empty(network_scm: SCMBuilder):
    result = network_scm.intervene("tel_queue_depth", delta=1.5)
    assert len(result.explanation) > 10


def test_invalid_node_raises(network_scm: SCMBuilder):
    with pytest.raises(ValueError, match="not in SCM graph"):
        network_scm.intervene("nonexistent_node", delta=1.0)


def test_topological_order_has_all_nodes(network_scm: SCMBuilder):
    order = network_scm.topological_order()
    assert len(order) == network_scm.node_count()
