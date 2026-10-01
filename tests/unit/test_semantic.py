"""
Unit tests for the SemanticGapAnalyzer.
"""

import pytest
from src.compiler.semantic import SemanticGapAnalyzer


@pytest.fixture
def analyzer() -> SemanticGapAnalyzer:
    return SemanticGapAnalyzer()


def test_vague_intent_has_high_gap(analyzer: SemanticGapAnalyzer):
    result = analyzer.analyze("Make the network better and faster")
    assert result.c_sem > 0.7, f"Expected high gap, got {result.c_sem}"


def test_quantitative_intent_has_lower_gap(analyzer: SemanticGapAnalyzer):
    result = analyzer.analyze("Ensure API gateway p99 latency < 50ms")
    assert result.c_sem < 0.8, f"Expected reduced gap, got {result.c_sem}"


def test_specific_intent_with_acceptance_criteria(analyzer: SemanticGapAnalyzer):
    result = analyzer.analyze(
        "When p99 > 100ms then trigger failover. Acceptance criteria: p99 < 50ms within 60s."
    )
    assert result.c_sem < 0.6


def test_gap_bounded_in_0_1(analyzer: SemanticGapAnalyzer):
    for text in [
        "Do something good fast",
        "Reduce p99 below 10ms with 99% SLA",
        "",
        "a",
    ]:
        result = analyzer.analyze(text)
        assert 0.0 <= result.c_sem <= 1.0, f"Out of bounds for: '{text}'"


def test_vague_terms_detected(analyzer: SemanticGapAnalyzer):
    result = analyzer.analyze("ensure network is fast and optimal")
    assert any(t in result.vague_terms_found for t in ["fast", "optimal", "ensure"])


def test_quantitative_matches_found(analyzer: SemanticGapAnalyzer):
    result = analyzer.analyze("Keep latency below 200ms and throughput above 1gbps")
    assert len(result.quantitative_matches) > 0


def test_score_convenience_method(analyzer: SemanticGapAnalyzer):
    score = analyzer.score("Ensure throughput > 500mbps")
    assert isinstance(score, float)
    assert 0.0 <= score <= 1.0
