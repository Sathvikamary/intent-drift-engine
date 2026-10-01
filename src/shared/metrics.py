"""
Prometheus Metrics — FastAPI middleware + custom gauges and counters.

Instruments the intent-drift-engine with:
  - intent_compilation_total          (counter, labels: decision)
  - intent_compilation_duration_ms    (histogram)
  - closure_gap_score                 (gauge, labels: dimension, intent_id)
  - kpi_drift_events_total            (counter, labels: intent, severity)
  - intent_state_current              (gauge, labels: intent, state)
  - delegation_envelopes_active       (gauge)
  - delegation_requests_total         (counter, labels: granted)
  - causal_links_detected_total       (counter)
  - system_health_numeric             (gauge, 0=NOMINAL 1=WARNING 2=DEGRADED 3=CRITICAL)
"""

from __future__ import annotations

from prometheus_client import (
    Counter,
    Gauge,
    Histogram,
    CollectorRegistry,
    make_asgi_app,
    CONTENT_TYPE_LATEST,
    generate_latest,
)
from fastapi import Response
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
import time

# ── Registry ────────────────────────────────────────────────────────────────
REGISTRY = CollectorRegistry(auto_describe=True)

# ── Counters ─────────────────────────────────────────────────────────────────
INTENT_COMPILE_TOTAL = Counter(
    "intent_compilation_total",
    "Total intent compilations by decision",
    ["decision"],
    registry=REGISTRY,
)

KPI_DRIFT_EVENTS_TOTAL = Counter(
    "kpi_drift_events_total",
    "Total KPI drift events by intent and severity",
    ["intent", "severity"],
    registry=REGISTRY,
)

DELEGATION_REQUESTS_TOTAL = Counter(
    "delegation_requests_total",
    "Total delegation requests by grant outcome",
    ["granted"],
    registry=REGISTRY,
)

CAUSAL_LINKS_TOTAL = Counter(
    "causal_links_detected_total",
    "Total significant Granger-causal links detected",
    registry=REGISTRY,
)

HTTP_REQUESTS_TOTAL = Counter(
    "http_requests_total",
    "Total HTTP requests by method, path, and status",
    ["method", "path", "status"],
    registry=REGISTRY,
)

# ── Histograms ────────────────────────────────────────────────────────────────
COMPILE_DURATION = Histogram(
    "intent_compilation_duration_ms",
    "Intent compilation duration in milliseconds",
    buckets=[1, 5, 10, 25, 50, 100, 250, 500, 1000],
    registry=REGISTRY,
)

HTTP_LATENCY = Histogram(
    "http_request_duration_ms",
    "HTTP request latency in milliseconds",
    ["method", "path"],
    buckets=[5, 10, 25, 50, 100, 250, 500, 1000],
    registry=REGISTRY,
)

# ── Gauges ────────────────────────────────────────────────────────────────────
CLOSURE_GAP = Gauge(
    "closure_gap_score",
    "Current closure gap score per dimension",
    ["dimension"],
    registry=REGISTRY,
)

INTENT_STATE = Gauge(
    "intent_state_current",
    "Current state of a macro-intent (1=active, 0=other)",
    ["intent", "state"],
    registry=REGISTRY,
)

DELEGATION_ACTIVE = Gauge(
    "delegation_envelopes_active",
    "Number of currently active delegation envelopes",
    registry=REGISTRY,
)

SYSTEM_HEALTH_NUMERIC = Gauge(
    "system_health_numeric",
    "System health as a number: 0=NOMINAL 1=WARNING 2=DEGRADED 3=CRITICAL",
    registry=REGISTRY,
)

WS_CONNECTIONS = Gauge(
    "websocket_connections_active",
    "Number of active WebSocket connections",
    registry=REGISTRY,
)

# ── Health mapping ─────────────────────────────────────────────────────────
HEALTH_TO_NUM = {"NOMINAL": 0, "WARNING": 1, "DEGRADED": 2, "CRITICAL": 3}
STATE_LIST = ["initializing", "active", "drifting", "remediating", "violated", "failed"]


# ── Recording helpers ────────────────────────────────────────────────────────

def record_compilation(decision: str, duration_ms: float, gap_vector: dict) -> None:
    INTENT_COMPILE_TOTAL.labels(decision=decision).inc()
    COMPILE_DURATION.observe(duration_ms)
    for dim in ("c_sem", "c_evid", "c_proc", "c_inst"):
        if dim in gap_vector:
            CLOSURE_GAP.labels(dimension=dim).set(gap_vector[dim])


def record_drift_event(intent: str, severity: str) -> None:
    KPI_DRIFT_EVENTS_TOTAL.labels(intent=intent, severity=severity).inc()


def record_delegation(granted: bool) -> None:
    DELEGATION_REQUESTS_TOTAL.labels(granted=str(granted)).inc()


def record_causal_link() -> None:
    CAUSAL_LINKS_TOTAL.inc()


def record_system_snapshot(snapshot: dict) -> None:
    """Update gauges from a MILD state machine snapshot."""
    health = snapshot.get("system_health", "NOMINAL")
    SYSTEM_HEALTH_NUMERIC.set(HEALTH_TO_NUM.get(health, 0))

    intents = snapshot.get("intents", {})
    for intent_key, record in intents.items():
        current_state = record.get("state", "initializing")
        for s in STATE_LIST:
            INTENT_STATE.labels(intent=intent_key, state=s).set(
                1 if s == current_state else 0
            )

    causal = snapshot.get("causal_links", 0)
    if causal > 0:
        CAUSAL_LINKS_TOTAL.inc(causal)


def update_active_envelopes(count: int) -> None:
    DELEGATION_ACTIVE.set(count)


def update_ws_connections(count: int) -> None:
    WS_CONNECTIONS.set(count)


# ── FastAPI metrics endpoint ──────────────────────────────────────────────────

async def metrics_endpoint(request: Request) -> Response:
    """Expose Prometheus metrics at /metrics."""
    data = generate_latest(REGISTRY)
    return Response(content=data, media_type=CONTENT_TYPE_LATEST)


# ── HTTP instrumentation middleware ──────────────────────────────────────────

class PrometheusMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        t0 = time.perf_counter()
        response = await call_next(request)
        duration_ms = (time.perf_counter() - t0) * 1000

        path = request.url.path
        method = request.method
        status = str(response.status_code)

        # Skip metrics endpoint itself to avoid cardinality explosion
        if path != "/metrics":
            HTTP_REQUESTS_TOTAL.labels(method=method, path=path, status=status).inc()
            HTTP_LATENCY.labels(method=method, path=path).observe(duration_ms)

        return response
