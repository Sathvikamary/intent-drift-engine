"""
Phase 3 integration tests — FastAPI endpoints (v0.3.0).
Uses httpx AsyncClient for full ASGI request testing.
"""
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

from src.api.main import app


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac


@pytest.mark.asyncio
async def test_health_endpoint(client: AsyncClient):
    resp = await client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["version"] == "0.3.0"
    assert "system_health" in data


@pytest.mark.asyncio
async def test_metrics_endpoint_returns_prometheus_format(client: AsyncClient):
    resp = await client.get("/metrics")
    assert resp.status_code == 200
    text = resp.text
    assert "intent_compilation_total" in text or "# HELP" in text


@pytest.mark.asyncio
async def test_compile_intent_endpoint(client: AsyncClient):
    resp = await client.post("/intents/compile", json={
        "intent_text": "Ensure API gateway p99 latency < 50ms with SLA threshold = 99.9%",
        "role": "network-ops",
        "domain": "api-gateway",
        "required_actions": ["read_metrics"],
        "closure_threshold": 0.3,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "decision" in data
    assert "gap_vector" in data
    assert data["decision"] in ["proceed", "defer", "reject", "overclose_risk"]


@pytest.mark.asyncio
async def test_llm_resolve_endpoint_heuristic(client: AsyncClient):
    """With no LLM_PROVIDER set, should fall back to heuristic gracefully."""
    resp = await client.post("/intents/llm-resolve", json={
        "intent_text": "Make the network faster and better",
        "provider": "none",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "c_sem_resolved" in data
    assert 0.0 <= data["c_sem_resolved"] <= 1.0
    assert data["fallback_used"] is True


@pytest.mark.asyncio
async def test_drift_ingest_endpoint(client: AsyncClient):
    resp = await client.post("/drift/ingest", json={
        "intent": "I_tel",
        "kpi_name": "queue_depth",
        "value": 15.0,
        "baseline_mean": 10.0,
        "baseline_std": 2.0,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "system_health" in data
    assert "most_severe" in data


@pytest.mark.asyncio
async def test_drift_ingest_invalid_intent(client: AsyncClient):
    resp = await client.post("/drift/ingest", json={
        "intent": "INVALID",
        "kpi_name": "latency",
        "value": 100.0,
        "baseline_mean": 50.0,
        "baseline_std": 5.0,
    })
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_mild_status_endpoint(client: AsyncClient):
    resp = await client.get("/mild/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "system_health" in data
    assert "intents" in data
    assert "I_tel" in data["intents"]
    assert "I_anl" in data["intents"]
    assert "I_api" in data["intents"]


@pytest.mark.asyncio
async def test_scm_summary_endpoint(client: AsyncClient):
    resp = await client.get("/scm/summary")
    assert resp.status_code == 200
    data = resp.json()
    assert data["nodes"] == 9
    assert data["is_dag"] is True
    assert len(data["edges"]) > 0


@pytest.mark.asyncio
async def test_scm_intervene_endpoint(client: AsyncClient):
    resp = await client.post("/scm/intervene", json={
        "node_id": "tel_queue_depth",
        "delta": 2.5,
        "propagation_decay": 0.6,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["intervened_node"] == "tel_queue_depth"
    assert isinstance(data["predicted_effects"], dict)
    assert len(data["explanation"]) > 0


@pytest.mark.asyncio
async def test_scm_intervene_invalid_node(client: AsyncClient):
    resp = await client.post("/scm/intervene", json={
        "node_id": "nonexistent",
        "delta": 1.0,
    })
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delegation_request_granted(client: AsyncClient):
    resp = await client.post("/delegation/request", json={
        "role": "network-ops",
        "domain": "routing",
        "requested_actions": ["read_metrics"],
        "risk_tier": "low",
        "max_duration_seconds": 120,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["granted"] is True
    assert data["envelope"] is not None
    assert data["envelope"]["state"] == "active"


@pytest.mark.asyncio
async def test_delegation_request_denied_bad_role(client: AsyncClient):
    resp = await client.post("/delegation/request", json={
        "role": "sre-tier1",
        "domain": "routing",
        "requested_actions": ["update_routing_policy"],
        "risk_tier": "low",
        "max_duration_seconds": 120,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["granted"] is False


@pytest.mark.asyncio
async def test_full_cascade_pipeline(client: AsyncClient):
    """End-to-end: compile intent → ingest KPIs → check MILD → delegation."""
    # 1. Compile intent
    compile_resp = await client.post("/intents/compile", json={
        "intent_text": "Ensure telemetry queue depth < 50 with SLA = 99%",
        "role": "network-ops",
        "domain": "telemetry",
        "required_actions": ["read_telemetry"],
        "closure_threshold": 0.4,
    })
    assert compile_resp.status_code == 200

    # 2. Ingest nominal KPI
    for _ in range(3):
        await client.post("/drift/ingest", json={
            "intent": "I_tel",
            "kpi_name": "queue_depth",
            "value": 12.0,
            "baseline_mean": 10.0,
            "baseline_std": 2.0,
        })

    # 3. Ingest critical KPI
    await client.post("/drift/ingest", json={
        "intent": "I_tel",
        "kpi_name": "queue_depth",
        "value": 100.0,
        "baseline_mean": 10.0,
        "baseline_std": 2.0,
    })

    # 4. Check MILD
    mild_resp = await client.get("/mild/status")
    assert mild_resp.status_code == 200
    mild_data = mild_resp.json()
    tel_state = mild_data["intents"]["I_tel"]["state"]
    assert tel_state != "initializing"

    # 5. Request delegation
    deleg_resp = await client.post("/delegation/request", json={
        "role": "network-ops",
        "domain": "telemetry",
        "requested_actions": ["read_telemetry"],
        "risk_tier": "low",
        "max_duration_seconds": 60,
    })
    assert deleg_resp.status_code == 200
    assert deleg_resp.json()["granted"] is True
