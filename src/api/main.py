"""
FastAPI Application v2 — Intent Drift Engine REST + WebSocket Interface.

Phase 2 additions:
  POST /delegation/request            — Request a delegation envelope
  GET  /delegation/{id}               — Get envelope status
  DELETE /delegation/{id}             — Revoke an envelope
  POST /delegation/{id}/shrink        — Adaptively shrink envelope
  GET  /scm/summary                   — SCM graph summary
  POST /scm/intervene                 — Run do-calculus intervention query
  GET  /mild/status                   — Full MILD state machine snapshot
  POST /mild/tick                     — Run one MILD control loop tick
  WS   /ws/kpi-stream                 — Real-time KPI broadcast stream
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# ── Compiler
from src.compiler.compiler import IntentCompilationRequest, IntentCompiler
from src.compiler.gap_vector import ClosureGapVector

# ── Drift
from src.drift.detector import DriftDetector, KPIObservation, MacroIntent
from src.drift.scm import build_network_scm
from src.drift.state_machine import MILDStateMachine

# ── Delegation
from src.delegation.delegator import AdaptiveDelegator, DelegationRequest
from src.delegation.envelope import RiskTier
from src.delegation.policy import build_baseline_policy_engine

# ── WebSocket
from src.api.websocket import kpi_stream_endpoint, manager

# ── App setup ──────────────────────────────────────────────────────────────

app = FastAPI(
    title="Intent Drift Engine",
    description=(
        "Autonomous Intent Compilation, Multi-Intent Drift Detection, "
        "Adaptive Delegation Envelopes, and MILD State Machine for IBN."
    ),
    version="0.2.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Singletons ─────────────────────────────────────────────────────────────
compiler = IntentCompiler()
drift_detector = DriftDetector()
scm = build_network_scm()
mild = MILDStateMachine(drift_detector=drift_detector, scm=scm)
policy_engine = build_baseline_policy_engine()
delegator = AdaptiveDelegator(policy_engine=policy_engine)

# In-memory stores
_compile_results: dict[str, dict[str, Any]] = {}
_drift_history: list[dict[str, Any]] = []


# ══════════════════════════════════════════════════════════════════════════ #
# Pydantic Schemas                                                           #
# ══════════════════════════════════════════════════════════════════════════ #

class CompileIntentRequest(BaseModel):
    intent_text: str
    role: str
    domain: str
    required_actions: list[str] = []
    closure_threshold: float = Field(default=0.2, ge=0.0, le=1.0)


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

    model_config = {"json_schema_extra": {"examples": [{
        "role": "network-ops",
        "domain": "routing",
        "requested_actions": ["read_metrics", "update_routing_policy"],
        "risk_tier": "medium",
        "max_duration_seconds": 300,
    }]}}


class ShrinkEnvelopeRequest(BaseModel):
    new_actions: list[str]
    reason: str = "risk escalation"


class InterventionRequest(BaseModel):
    node_id: str
    delta: float = Field(..., description="Magnitude of intervention (positive = increase)")
    propagation_decay: float = Field(default=0.6, ge=0.0, le=1.0)


# ══════════════════════════════════════════════════════════════════════════ #
# Health                                                                     #
# ══════════════════════════════════════════════════════════════════════════ #

@app.get("/health")
async def health_check() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "intent-drift-engine",
        "version": "0.2.0",
        "ws_connections": manager.connection_count(),
        "system_health": mild.system_health(),
    }


# ══════════════════════════════════════════════════════════════════════════ #
# Intent Compiler                                                            #
# ══════════════════════════════════════════════════════════════════════════ #

@app.post("/intents/compile")
async def compile_intent(body: CompileIntentRequest) -> dict[str, Any]:
    """Compile a high-level intent — resolves C_t and returns a decision."""
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

    # Broadcast to WebSocket clients
    await manager.broadcast("intent_compiled", serialized)
    return serialized


@app.get("/intents/{intent_id}/status")
async def get_intent_status(intent_id: str) -> dict[str, Any]:
    if intent_id not in _compile_results:
        raise HTTPException(status_code=404, detail=f"Intent '{intent_id}' not found.")
    return _compile_results[intent_id]


@app.get("/intents/")
async def list_intents() -> dict[str, Any]:
    return {"total": len(_compile_results), "intents": list(_compile_results.values())}


# ══════════════════════════════════════════════════════════════════════════ #
# Drift Detection                                                            #
# ══════════════════════════════════════════════════════════════════════════ #

@app.post("/drift/ingest")
async def ingest_kpi(body: KPIIngestRequest) -> dict[str, Any]:
    """Ingest a KPI observation and run drift detection + MILD tick."""
    try:
        macro = MacroIntent(body.intent)
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid intent '{body.intent}'. Must be one of: {[m.value for m in MacroIntent]}",
        )

    obs = KPIObservation(
        intent=macro,
        kpi_name=body.kpi_name,
        value=body.value,
        timestamp=body.timestamp or time.time(),
        baseline_mean=body.baseline_mean,
        baseline_std=body.baseline_std,
    )

    # Run MILD tick (includes drift detection internally)
    snapshot = mild.tick([obs])
    _drift_history.append(snapshot)

    # Broadcast to WebSocket clients
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


# ══════════════════════════════════════════════════════════════════════════ #
# MILD State Machine                                                         #
# ══════════════════════════════════════════════════════════════════════════ #

@app.get("/mild/status")
async def mild_status() -> dict[str, Any]:
    """Full snapshot of MILD state machine across all macro-intents."""
    return {
        "system_health": mild.system_health(),
        "intents": {
            intent.value: mild.get_state(intent).to_dict()
            for intent in MacroIntent
        },
    }


@app.post("/mild/tick")
async def mild_tick(observations: list[KPIIngestRequest]) -> dict[str, Any]:
    """Manually trigger one MILD control loop tick with a batch of KPIs."""
    obs_list: list[KPIObservation] = []
    for body in observations:
        try:
            macro = MacroIntent(body.intent)
        except ValueError:
            raise HTTPException(status_code=422, detail=f"Invalid intent '{body.intent}'")
        obs_list.append(KPIObservation(
            intent=macro,
            kpi_name=body.kpi_name,
            value=body.value,
            timestamp=body.timestamp or time.time(),
            baseline_mean=body.baseline_mean,
            baseline_std=body.baseline_std,
        ))
    snapshot = mild.tick(obs_list)
    await manager.broadcast("state_snapshot", snapshot)
    return snapshot


# ══════════════════════════════════════════════════════════════════════════ #
# SCM — Structural Causal Model                                              #
# ══════════════════════════════════════════════════════════════════════════ #

@app.get("/scm/summary")
async def scm_summary() -> dict[str, Any]:
    """Return SCM graph summary — nodes, edges, topological order."""
    return {
        **scm.summary(),
        "edges": scm.to_edge_list(),
    }


@app.post("/scm/intervene")
async def scm_intervene(body: InterventionRequest) -> dict[str, Any]:
    """
    Run a do-calculus intervention on a SCM node.
    Returns predicted downstream effects and explanation.
    """
    try:
        result = scm.intervene(
            node_id=body.node_id,
            delta=body.delta,
            propagation_decay=body.propagation_decay,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return {
        "intervened_node": result.intervened_node,
        "intervention_value": result.intervention_value,
        "predicted_effects": result.predicted_effects,
        "causal_path": result.causal_path,
        "explanation": result.explanation,
    }


# ══════════════════════════════════════════════════════════════════════════ #
# Delegation Envelopes                                                       #
# ══════════════════════════════════════════════════════════════════════════ #

@app.post("/delegation/request")
async def request_delegation(body: DelegationRequestSchema) -> dict[str, Any]:
    """Request an adaptive delegation envelope for a role-domain-action set."""
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
    """Get the current state of a delegation envelope."""
    env = delegator.get_envelope(envelope_id)
    if not env:
        raise HTTPException(status_code=404, detail=f"Envelope '{envelope_id}' not found.")
    return env.to_dict()


@app.delete("/delegation/{envelope_id}")
async def revoke_envelope(envelope_id: str, reason: str = "api revocation") -> dict[str, Any]:
    """Revoke an active delegation envelope."""
    ok = delegator.revoke_envelope(envelope_id, reason)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Envelope '{envelope_id}' not found or already revoked.")
    await manager.broadcast("envelope_revoked", {"envelope_id": envelope_id, "reason": reason})
    return {"revoked": True, "envelope_id": envelope_id}


@app.post("/delegation/{envelope_id}/shrink")
async def shrink_envelope(envelope_id: str, body: ShrinkEnvelopeRequest) -> dict[str, Any]:
    """Adaptively shrink an envelope's permitted action set."""
    ok = delegator.shrink_envelope(envelope_id, body.new_actions, body.reason)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Envelope '{envelope_id}' not found or inactive.")
    env = delegator.get_envelope(envelope_id)
    return {"shrunk": True, "envelope": env.to_dict() if env else None}


@app.get("/delegation/")
async def list_envelopes() -> dict[str, Any]:
    """List all currently active delegation envelopes."""
    active = delegator.get_active_envelopes()
    return {
        "active_count": len(active),
        "envelopes": [e.to_dict() for e in active],
    }


# ══════════════════════════════════════════════════════════════════════════ #
# WebSocket                                                                  #
# ══════════════════════════════════════════════════════════════════════════ #

@app.websocket("/ws/kpi-stream")
async def websocket_kpi_stream(websocket: WebSocket) -> None:
    """Real-time KPI stream — broadcasts drift events, state snapshots, and alerts."""
    await kpi_stream_endpoint(websocket)
