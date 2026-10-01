"""
FastAPI Application — Intent Drift Engine REST Interface.

Endpoints:
  POST /intents/compile     — Submit an intent for compilation
  GET  /intents/{id}/status — Check compilation result
  POST /drift/ingest        — Ingest KPI observations
  GET  /drift/status        — Current drift state across all macro-intents
  GET  /health              — Health check
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from src.compiler.compiler import (
    IntentCompilationRequest,
    IntentCompiler,
)
from src.compiler.evidentiary import ContextSource
from src.compiler.procedural import ExecutionPath, ExecutionStep, ToolStatus
from src.compiler.institutional import PolicyClearance, AuthorizationLevel
from src.drift.detector import (
    DriftDetectionResult,
    DriftDetector,
    KPIObservation,
    MacroIntent,
)

# ── App setup ──────────────────────────────────────────────────────────────

app = FastAPI(
    title="Intent Drift Engine",
    description=(
        "Autonomous Intent Compilation, Multi-Intent Drift Detection, "
        "and Adaptive Delegation Envelopes for Intent-Based Networking."
    ),
    version="0.1.0",
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

# In-memory result store (replace with Redis in production)
_compile_results: dict[str, dict[str, Any]] = {}
_drift_history: list[dict[str, Any]] = []


# ── Pydantic schemas ───────────────────────────────────────────────────────

class CompileIntentRequest(BaseModel):
    intent_text: str = Field(..., description="High-level declarative intent in natural language")
    role: str = Field(..., description="Acting role (e.g., 'network-ops', 'sre-tier2')")
    domain: str = Field(..., description="Target resource domain (e.g., 'routing', 'telemetry')")
    required_actions: list[str] = Field(default_factory=list)
    closure_threshold: float = Field(default=0.2, ge=0.0, le=1.0)

    model_config = {"json_schema_extra": {"examples": [{
        "intent_text": "Ensure API gateway p99 latency < 50ms during peak hours",
        "role": "network-ops",
        "domain": "api-gateway",
        "required_actions": ["read_metrics", "update_routing_policy"],
        "closure_threshold": 0.2,
    }]}}


class KPIIngestRequest(BaseModel):
    intent: str = Field(..., description="Macro-intent: I_tel, I_anl, or I_api")
    kpi_name: str
    value: float
    baseline_mean: float
    baseline_std: float = Field(..., ge=0.0)
    timestamp: float | None = None


class CompileIntentResponse(BaseModel):
    intent_id: str
    decision: str
    gap_vector: dict[str, Any]
    selected_path_id: str | None
    compilation_time_ms: float
    notes: list[str]
    component_details: dict[str, Any]


# ── Routes ─────────────────────────────────────────────────────────────────

@app.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "ok", "service": "intent-drift-engine", "version": "0.1.0"}


@app.post("/intents/compile", response_model=CompileIntentResponse)
async def compile_intent(body: CompileIntentRequest) -> CompileIntentResponse:
    """
    Submit a high-level intent for compilation.

    The compiler resolves the closure-gap vector C_t and returns a
    compilation decision (PROCEED / DEFER / REJECT / OVERCLOSE_RISK).
    """
    intent_id = str(uuid.uuid4())[:8]

    # Build a minimal request (no external sources/paths for now)
    request = IntentCompilationRequest(
        intent_id=intent_id,
        intent_text=body.intent_text,
        role=body.role,
        domain=body.domain,
        required_actions=body.required_actions,
        closure_threshold=body.closure_threshold,
    )

    result = await compiler.compile_async(request)
    serialized = {
        "intent_id": result.intent_id,
        "decision": result.decision.value,
        "gap_vector": result.gap_vector.to_dict(),
        "selected_path_id": result.selected_path.path_id if result.selected_path else None,
        "compilation_time_ms": result.compilation_time_ms,
        "notes": result.notes,
        "component_details": result.component_details,
    }
    _compile_results[intent_id] = serialized
    return CompileIntentResponse(**serialized)


@app.get("/intents/{intent_id}/status")
async def get_intent_status(intent_id: str) -> dict[str, Any]:
    """Retrieve the compilation result for a previously submitted intent."""
    if intent_id not in _compile_results:
        raise HTTPException(status_code=404, detail=f"Intent '{intent_id}' not found.")
    return _compile_results[intent_id]


@app.get("/intents/")
async def list_intents() -> dict[str, Any]:
    """List all compiled intents."""
    return {"total": len(_compile_results), "intents": list(_compile_results.values())}


@app.post("/drift/ingest")
async def ingest_kpi(body: KPIIngestRequest) -> dict[str, Any]:
    """Ingest a KPI observation and run drift detection."""
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

    result = drift_detector.detect([obs])
    summary = {
        "most_severe": result.most_severe.value,
        "events": [
            {
                "intent": e.affected_intent.value,
                "kpi": e.kpi_name,
                "severity": e.severity.value,
                "z_score": round(e.z_score, 3),
                "root_cause": e.root_cause_intent.value if e.root_cause_intent else None,
            }
            for e in result.events
        ],
        "causal_links": [
            {
                "cause": lk.cause.value,
                "effect": lk.effect.value,
                "f_stat": round(lk.granger_f_statistic, 3),
                "p_value": round(lk.p_value, 4),
                "lag": lk.lag_steps,
                "significant": lk.significant,
            }
            for lk in result.causal_links
        ],
        "notes": result.notes,
    }
    _drift_history.append(summary)
    return summary


@app.get("/drift/status")
async def drift_status() -> dict[str, Any]:
    """Return current drift state across all macro-intents."""
    latest = _drift_history[-1] if _drift_history else {}
    return {
        "total_events_processed": len(_drift_history),
        "latest": latest,
    }
