"""
Phase 3 tests — LLM Semantic Resolver (heuristic fallback path).
"""
import pytest
import asyncio
from src.compiler.llm.resolver import LLMSemanticResolver


@pytest.fixture
def resolver() -> LLMSemanticResolver:
    # Always use heuristic (no API key in test env)
    return LLMSemanticResolver(provider="none")


@pytest.mark.asyncio
async def test_heuristic_fallback_returns_result(resolver: LLMSemanticResolver):
    result = await resolver.resolve("Make the network better and faster")
    assert result.fallback_used is True
    assert result.provider == "heuristic"
    assert 0.0 <= result.residual_ambiguity_score <= 1.0


@pytest.mark.asyncio
async def test_vague_intent_gets_high_score(resolver: LLMSemanticResolver):
    result = await resolver.resolve("Fix the thing")
    assert result.residual_ambiguity_score > 0.6, (
        f"Expected high ambiguity, got {result.residual_ambiguity_score}"
    )


@pytest.mark.asyncio
async def test_quantitative_intent_gets_lower_score(resolver: LLMSemanticResolver):
    result = await resolver.resolve("Ensure API gateway p99 latency < 50ms with SLA = 99.9%")
    assert result.residual_ambiguity_score < 0.9


@pytest.mark.asyncio
async def test_resolver_score_always_bounded(resolver: LLMSemanticResolver):
    for text in [
        "do something",
        "Ensure p99 < 100ms and throughput > 500mbps",
        "",
        "when KPI target = 99% then trigger failover acceptance criteria: latency < 10ms",
    ]:
        result = await resolver.resolve(text)
        assert 0.0 <= result.residual_ambiguity_score <= 1.0, f"Out of bounds for: '{text}'"


@pytest.mark.asyncio
async def test_vague_terms_populated(resolver: LLMSemanticResolver):
    result = await resolver.resolve("ensure the system is fast and optimal")
    assert len(result.vague_terms) > 0
