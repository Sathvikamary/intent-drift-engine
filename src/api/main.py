"""
FastAPI Application v0.3.0 — Intent Drift Engine REST + WebSocket Interface.

Phase 3 additions:
  GET  /metrics                       — Prometheus metrics scrape endpoint
  POST /intents/llm-resolve           — LLM-powered semantic gap resolution
  Full Prometheus instrumentation on all routes
  PrometheusMiddleware for HTTP latency tracking
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from fastapi import FastAPI, HTTPException, Request, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# ── Compiler
from src.compiler.compiler import IntentCompilationRequest, IntentCompiler
from src.compiler.gap_vector import ClosureGapVector
from src.compiler.llm.resolver import LLMSemanticResolver

# ── Drift
from src.drift.detector import DriftDetector, KPIObservation, MacroIntent
from src.drift.scm import build_network_scm
from src.drift.state_machine import MILDStateMachine

# ── Delegation
from src.delegation.delegator import AdaptiveDelegator, DelegationRequest
from src.delegation.envelope import RiskTier
from src.delegation.policy import build_baseline_policy_engine

# ── Shared
from src.shared.metrics import (
    PrometheusMiddleware,
    metrics_endpoint,
    record_compilation,
    record_drift_event,
    record_delegation,
    record_system_snapshot,
    update_active_envelopes,
    update_ws_connections,
)

# ── WebSocket
from src.api.websocket import kpi_stream_endpoint, manager

# ═══════════════════════════════════════════════════════════════════════════
# App setup
# ═══════════════════════════════════════════════════════════════════════════
app = FastAPI(
    title="Intent Drift Engine",
    description=(
        "Autonomous Intent Compilation, Multi-Intent Drift Detection, "
        "Adaptive Delegation Envelopes, MILD State Machine, and LLM Semantic "
        "Resolution for Intent-Based Networking."
    ),
    version="0.3.0",
)

app.add_middleware(PrometheusMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Singletons ──────────────────────────────────────────────────────────────
compiler      = IntentCompiler()
llm_resolver  = LLMSemanticResolver()
drift_detector= DriftDetector()
scm           = build_network_scm()
mild          = MILDStateMachine(drift_detector=drift_detector, scm=scm)
policy_engine = build_baseline_policy_engine()
delegator     = AdaptiveDelegator(policy_engine=policy_engine)

# In-memory stores
_compile_results: dict[str, dict[str, Any]] = {}
_drift_history:   list[dict[str, Any]] = []


# ═══════════════════════════════════════════════════════════════════════════
# Pydantic schemas
# ═══════════════════════════════════════════════════════════════════════════

class CompileIntentRequest(BaseModel):
    intent_text: str
    role: str
    domain: str
    required_actions: list[str] = []
    closure_threshold: float = Field(default=0.2, ge=0.0, le=1.0)


class LLMResolveRequest(BaseModel):
    intent_text: str
    provider: str | None = None   # "gemini" | "openai" | None (uses env)
    model: str | None = None

    model_config = {"json_schema_extra": {"examples": [{
        "intent_text": "Make the network faster and more reliable",
        "provider": "gemini",
    }]}}


class KPIIngestRequest(BaseModel):
    intent: str = Field(..., description="I_tel | I_anl | I_api")
    kpi_name: str
    value: float
    baseline_mean: float
    baseline_std: float = Field(..., ge=0.0)
    timestamp: float | None = None


class DelegationRequestSchema(BaseModel):
    role: str
    domain: str
    requested_actions: list[str]
    risk_tier: str = Field(default="low", pattern="^(low|medium|high)$")
    max_duration_seconds: float = Field(default=300.0, ge=30.0, le=3600.0)
    gap_vector: dict[str, float] | None = None
    action_budgets: dict[str, int] | None = None


class ShrinkEnvelopeRequest(BaseModel):
    new_actions: list[str]
    reason: str = "risk escalation"


class InterventionRequest(BaseModel):
    node_id: str
    delta: float
    propagation_decay: float = Field(default=0.6, ge=0.0, le=1.0)


# ═══════════════════════════════════════════════════════════════════════════
# Health & Metrics
# ═══════════════════════════════════════════════════════════════════════════

@app.get("/health")
async def health_check() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "intent-drift-engine",
        "version": "0.3.0",
        "ws_connections": manager.connection_count(),
        "system_health": mild.system_health(),
        "active_envelopes": len(delegator.get_active_envelopes()),
    }


@app.get("/metrics")
async def get_metrics(request: Request):
    """Prometheus metrics scrape endpoint."""
    update_ws_connections(manager.connection_count())
    update_active_envelopes(len(delegator.get_active_envelopes()))
    return await metrics_endpoint(request)


# ═══════════════════════════════════════════════════════════════════════════
# Intent Compiler
# ═══════════════════════════════════════════════════════════════════════════

@app.post("/intents/compile")
async def compile_intent(body: CompileIntentRequest) -> dict[str, Any]:
    """Compile a high-level intent — resolves Ct and returns a decision."""
    intent_id = str(uuid.uuid4())[:8]
    request = IntentCompilationRequest(
        intent_id=intent_id,
        intent_text=body.intent_text,
        role=body.role,
        domain=body.domain,
        required_actions=body.required_actions,
        closure_threshold=body.closure_threshold,
    )
    result = await compiler.compile_async(request)

    # ── Prometheus instrumentation ──
    record_compilation(
        decision=result.decision.value,
        duration_ms=result.compilation_time_ms,
        gap_vector=result.gap_vector.to_dict(),
    )

    serialized: dict[str, Any] = {
        "intent_id": result.intent_id,
        "decision": result.decision.value,
        "gap_vector": result.gap_vector.to_dict(),
        "selected_path_id": result.selected_path.path_id if result.selected_path else None,
        "compilation_time_ms": result.compilation_time_ms,
        "notes": result.notes,
        "component_details": result.component_details,
    }
    _compile_results[intent_id] = serialized
    await manager.broadcast("intent_compiled", serialized)
    return serialized


@app.post("/intents/llm-resolve")
async def llm_resolve_intent(body: LLMResolveRequest) -> dict[str, Any]:
    """
    Use an LLM to auto-resolve semantic ambiguity in the intent text.
    Returns structured acceptance criteria and an updated C_sem,t score.
    
    Set LLM_PROVIDER and LLM_API_KEY environment variables to enable LLM mode.
    Falls back to heuristic analysis if no provider is configured.
    """
    resolver = LLMSemanticResolver(
        provider=body.provider,
        model=body.model,
    )
    result = await resolver.resolve(body.intent_text)

    response = {
        "raw_intent": result.raw_intent,
        "rewritten_intent": result.rewritten_intent,
        "acceptance_criteria": result.acceptance_criteria,
        "vague_terms": result.vague_terms,
        "c_sem_resolved": result.residual_ambiguity_score,
        "reasoning": result.reasoning,
        "provider": result.provider,
        "model": result.model,
        "fallback_used": result.fallback_used,
        "notes": result.notes,
    }
    await manager.broadcast("intent_llm_resolved", response)
    return response


@app.get("/intents/{intent_id}/status")
async def get_intent_status(intent_id: str) -> dict[str, Any]:
    if intent_id not in _compile_results:
        raise HTTPException(status_code=404, detail=f"Intent '{intent_id}' not found.")
    return _compile_results[intent_id]


@app.get("/intents/")
async def list_intents() -> dict[str, Any]:
    return {"total": len(_compile_results), "intents": list(_compile_results.values())}


# ═══════════════════════════════════════════════════════════════════════════
# Drift Detection + MILD
# ═══════════════════════════════════════════════════════════════════════════

@app.post("/drift/ingest")
async def ingest_kpi(body: KPIIngestRequest) -> dict[str, Any]:
    """Ingest a KPI observation, run MILD tick, and broadcast the snapshot."""
    try:
        macro = MacroIntent(body.intent)
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid intent '{body.intent}'. Must be: {[m.value for m in MacroIntent]}",
        )

    obs = KPIObservation(
        intent=macro,
        kpi_name=body.kpi_name,
        value=body.value,
        timestamp=body.timestamp or time.time(),
        baseline_mean=body.baseline_mean,
        baseline_std=body.baseline_std,
    )

    snapshot = mild.tick([obs])
    _drift_history.append(snapshot)

    # ── Prometheus instrumentation ──
    for event in snapshot.get("log", []):
        if "drift" in event.lower() or "⚠️" in event:
            record_drift_event(intent=body.intent, severity=snapshot.get("most_severe", "nominal"))
    record_system_snapshot(snapshot)

    await manager.broadcast("state_snapshot", snapshot)
    if snapshot["most_severe"] in ("drift", "critical"):
        await manager.broadcast("drift_alert", {
            "most_severe": snapshot["most_severe"],
            "system_health": snapshot["system_health"],
            "log": snapshot["log"],
        })
    return snapshot


@app.get("/drift/status")
async def drift_status() -> dict[str, Any]:
    latest = _drift_history[-1] if _drift_history else {}
    return {"total_ticks": len(_drift_history), "latest": latest}


@app.get("/mild/status")
async def mild_status() -> dict[str, Any]:
    return {
        "system_health": mild.system_health(),
        "intents": {
            intent.value: mild.get_state(intent).to_dict()
            for intent in MacroIntent
        },
    }


@app.post("/mild/tick")
async def mild_tick(observations: list[KPIIngestRequest]) -> dict[str, Any]:
    obs_list: list[KPIObservation] = []
    for body in observations:
        try:
            macro = MacroIntent(body.intent)
        except ValueError:
            raise HTTPException(status_code=422, detail=f"Invalid intent '{body.intent}'")
        obs_list.append(KPIObservation(
            intent=macro, kpi_name=body.kpi_name, value=body.value,
            timestamp=body.timestamp or time.time(),
            baseline_mean=body.baseline_mean, baseline_std=body.baseline_std,
        ))
    snapshot = mild.tick(obs_list)
    record_system_snapshot(snapshot)
    await manager.broadcast("state_snapshot", snapshot)
    return snapshot


# ═══════════════════════════════════════════════════════════════════════════
# SCM
# ═══════════════════════════════════════════════════════════════════════════

@app.get("/scm/summary")
async def scm_summary() -> dict[str, Any]:
    return {**scm.summary(), "edges": scm.to_edge_list()}


@app.post("/scm/intervene")
async def scm_intervene(body: InterventionRequest) -> dict[str, Any]:
    try:
        result = scm.intervene(body.node_id, body.delta, body.propagation_decay)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {
        "intervened_node": result.intervened_node,
        "intervention_value": result.intervention_value,
        "predicted_effects": result.predicted_effects,
        "causal_path": result.causal_path,
        "explanation": result.explanation,
    }


# ═══════════════════════════════════════════════════════════════════════════
# Delegation Envelopes
# ═══════════════════════════════════════════════════════════════════════════

@app.post("/delegation/request")
async def request_delegation(body: DelegationRequestSchema) -> dict[str, Any]:
    gap = None
    if body.gap_vector:
        try:
            gap = ClosureGapVector(**body.gap_vector)
        except (TypeError, ValueError) as e:
            raise HTTPException(status_code=422, detail=f"Invalid gap_vector: {e}")

    req = DelegationRequest(
        requester_role=body.role,
        domain=body.domain,
        requested_actions=body.requested_actions,
        gap_vector=gap,
        max_duration_seconds=body.max_duration_seconds,
        risk_tier=RiskTier(body.risk_tier),
        action_budgets=body.action_budgets,
    )
    response = delegator.request_envelope(req)
    record_delegation(granted=response.granted)

    result: dict[str, Any] = {
        "granted": response.granted,
        "gap_block_reason": response.gap_block_reason,
        "denied_actions": response.denied_actions,
        "notes": response.notes,
        "envelope": response.envelope.to_dict() if response.envelope else None,
    }
    if response.granted and response.envelope:
        await manager.broadcast("envelope_issued", result)
    return result


@app.get("/delegation/{envelope_id}")
async def get_envelope(envelope_id: str) -> dict[str, Any]:
    env = delegator.get_envelope(envelope_id)
    if not env:
        raise HTTPException(status_code=404, detail=f"Envelope '{envelope_id}' not found.")
    return env.to_dict()


@app.delete("/delegation/{envelope_id}")
async def revoke_envelope(envelope_id: str, reason: str = "api revocation") -> dict[str, Any]:
    ok = delegator.revoke_envelope(envelope_id, reason)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Envelope '{envelope_id}' not found or already revoked.")
    await manager.broadcast("envelope_revoked", {"envelope_id": envelope_id, "reason": reason})
    return {"revoked": True, "envelope_id": envelope_id}


@app.post("/delegation/{envelope_id}/shrink")
async def shrink_envelope(envelope_id: str, body: ShrinkEnvelopeRequest) -> dict[str, Any]:
    ok = delegator.shrink_envelope(envelope_id, body.new_actions, body.reason)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Envelope '{envelope_id}' not found or inactive.")
    env = delegator.get_envelope(envelope_id)
    return {"shrunk": True, "envelope": env.to_dict() if env else None}


@app.get("/delegation/")
async def list_envelopes() -> dict[str, Any]:
    active = delegator.get_active_envelopes()
    return {"active_count": len(active), "envelopes": [e.to_dict() for e in active]}


# ═══════════════════════════════════════════════════════════════════════════
# WebSocket
# ═══════════════════════════════════════════════════════════════════════════

@app.websocket("/ws/kpi-stream")
async def websocket_kpi_stream(websocket: WebSocket) -> None:
    """Real-time KPI stream — broadcasts drift events, state snapshots, alerts."""
    await kpi_stream_endpoint(websocket)
