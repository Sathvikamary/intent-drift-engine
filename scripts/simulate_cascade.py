"""
Cascade Simulation Runner — Phase 3.

Simulates the real-world scenario of queue backpressure in I_tel
propagating causally through I_anl to I_api as described in the paper.

Scenario phases:
  1. BASELINE     (t=0–10s)   : All KPIs nominal
  2. FAULT INJECT (t=10–20s)  : I_tel queue depth spikes → backpressure
  3. CO-DRIFT     (t=20–35s)  : I_anl throughput drops, I_api latency rises
  4. SLA BREACH   (t=35–45s)  : API p99 > SLA threshold
  5. REMEDIATION  (t=45–60s)  : Auto-heal, KPIs return to baseline

Usage:
    python scripts/simulate_cascade.py [--api-url http://localhost:8000] [--speed 1.0]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any

try:
    import httpx
except ImportError:
    print("httpx not installed. Run: pip install httpx")
    sys.exit(1)


class Phase(str, Enum):
    BASELINE = "BASELINE"
    FAULT_INJECT = "FAULT_INJECT"
    CO_DRIFT = "CO_DRIFT"
    SLA_BREACH = "SLA_BREACH"
    REMEDIATION = "REMEDIATION"
    COMPLETE = "COMPLETE"


@dataclass
class KPITick:
    intent: str
    kpi_name: str
    value: float
    baseline_mean: float
    baseline_std: float
    label: str = ""


# ── Scenario definition ─────────────────────────────────────────────────────

SCENARIO: list[tuple[float, Phase, list[KPITick]]] = [

    # ── BASELINE (nominal) ────────────────────────────────────────────────
    *[
        (t, Phase.BASELINE, [
            KPITick("I_tel", "queue_depth",        10.0 + (t * 0.1), 10.0, 2.0),
            KPITick("I_anl", "inference_throughput", 500.0,            500.0, 20.0),
            KPITick("I_api", "p99_latency",          45.0,             45.0, 5.0),
        ])
        for t in range(10)
    ],

    # ── FAULT INJECT: queue backpressure in I_tel ─────────────────────────
    *[
        (10 + t, Phase.FAULT_INJECT, [
            KPITick("I_tel", "queue_depth",        40.0 + (t * 15), 10.0, 2.0,
                    label="⚠️ Queue backpressure building" if t == 0 else ""),
            KPITick("I_anl", "inference_throughput", 500.0 - (t * 10), 500.0, 20.0),
            KPITick("I_api", "p99_latency",          47.0 + (t * 1.5), 45.0, 5.0),
        ])
        for t in range(10)
    ],

    # ── CO-DRIFT: I_anl throughput drops, I_api latency rises ────────────
    *[
        (20 + t, Phase.CO_DRIFT, [
            KPITick("I_tel", "queue_depth",        200.0 + (t * 5),    10.0, 2.0),
            KPITick("I_anl", "inference_throughput", 400.0 - (t * 20),  500.0, 20.0,
                    label="⛓️ Causal co-drift: Analytics degraded" if t == 0 else ""),
            KPITick("I_api", "p99_latency",          60.0 + (t * 5),    45.0, 5.0,
                    label="📈 API latency rising" if t == 3 else ""),
        ])
        for t in range(15)
    ],

    # ── SLA BREACH: API p99 exceeds threshold ────────────────────────────
    *[
        (35 + t, Phase.SLA_BREACH, [
            KPITick("I_tel", "queue_depth",        250.0,       10.0, 2.0),
            KPITick("I_anl", "inference_throughput", 100.0,     500.0, 20.0),
            KPITick("I_api", "p99_latency",          200.0 + t, 45.0, 5.0,
                    label="🔴 SLA BREACH: p99 > 200ms threshold" if t == 0 else ""),
        ])
        for t in range(10)
    ],

    # ── REMEDIATION: auto-heal, KPIs recovering ──────────────────────────
    *[
        (45 + t, Phase.REMEDIATION, [
            KPITick("I_tel", "queue_depth",
                    max(10.0, 200.0 - (t * 15)), 10.0, 2.0,
                    label="🔧 Remediation: flushing queue" if t == 0 else ""),
            KPITick("I_anl", "inference_throughput",
                    min(500.0, 100.0 + (t * 30)), 500.0, 20.0),
            KPITick("I_api", "p99_latency",
                    max(48.0, 200.0 - (t * 20)),  45.0, 5.0),
        ])
        for t in range(15)
    ],
]


# ── Renderer ────────────────────────────────────────────────────────────────

PHASE_COLORS = {
    Phase.BASELINE:    "\033[32m",    # Green
    Phase.FAULT_INJECT:"\033[33m",    # Yellow
    Phase.CO_DRIFT:    "\033[35m",    # Magenta
    Phase.SLA_BREACH:  "\033[31m",    # Red
    Phase.REMEDIATION: "\033[36m",    # Cyan
    Phase.COMPLETE:    "\033[32m",    # Green
}
RESET = "\033[0m"


def print_banner() -> None:
    print("\n" + "═" * 70)
    print("  🌐  Intent Drift Engine — Cascade Simulation Runner  (Phase 3)")
    print("═" * 70)
    print("""
  Scenario: Queue backpressure in I_tel propagates causally to
            I_anl (throughput drop) → I_api (SLA breach)

  Intents:
    I_tel  Telemetry Intent      (queue_depth KPI)
    I_anl  Analytics Intent      (inference_throughput KPI)
    I_api  API Gateway Intent    (p99_latency KPI)
""")


def print_tick(tick_num: int, phase: Phase, ticks: list[KPITick], snapshot: dict[str, Any]) -> None:
    color = PHASE_COLORS.get(phase, "")
    print(f"\n{color}[t={tick_num:>3}s] {'─' * 10} {phase.value} {'─' * 10}{RESET}")

    for t in ticks:
        z = (t.value - t.baseline_mean) / t.baseline_std if t.baseline_std else 0
        bar = _bar(z)
        label_str = f"  {t.label}" if t.label else ""
        print(f"  {t.intent:<6} {t.kpi_name:<25} = {t.value:>8.1f}  z={z:>+5.1f}  {bar}{label_str}")

    health = snapshot.get("system_health", "?")
    severe = snapshot.get("most_severe", "?")
    log = snapshot.get("log", [])
    health_color = {"NOMINAL": "\033[32m", "WARNING": "\033[33m",
                    "DEGRADED": "\033[35m", "CRITICAL": "\033[31m"}.get(health, "")
    print(f"\n  System: {health_color}{health}{RESET}  |  Drift: {severe}")
    for entry in log:
        print(f"    ↳ {entry}")


def _bar(z: float, width: int = 20) -> str:
    """ASCII bar chart for z-score."""
    filled = int(min(abs(z) / 5.0, 1.0) * width)
    char = "█" if z > 2 else "▒" if z > 1 else "░"
    return f"[{'█' if z <= 0 else char * filled:{'<' if z > 0 else '>'}{width}}]"


# ── HTTP client ─────────────────────────────────────────────────────────────

def ingest_kpi(client: httpx.Client, tick: KPITick) -> dict[str, Any]:
    payload = {
        "intent": tick.intent,
        "kpi_name": tick.kpi_name,
        "value": tick.value,
        "baseline_mean": tick.baseline_mean,
        "baseline_std": tick.baseline_std,
    }
    resp = client.post("/drift/ingest", json=payload, timeout=5.0)
    resp.raise_for_status()
    return resp.json()


def submit_intent(client: httpx.Client) -> None:
    """Submit a sample intent at simulation start."""
    client.post("/intents/compile", json={
        "intent_text": "Ensure API gateway p99 latency < 200ms with SLA = 99.9%",
        "role": "network-ops",
        "domain": "api-gateway",
        "required_actions": ["read_metrics", "update_routing_policy"],
        "closure_threshold": 0.25,
    }, timeout=5.0)


# ── Main ─────────────────────────────────────────────────────────────────────

def run_simulation(api_url: str, speed: float) -> None:
    print_banner()

    with httpx.Client(base_url=api_url) as client:
        # Health check
        try:
            health = client.get("/health", timeout=3.0).json()
            print(f"  ✅ Connected to {api_url}")
            print(f"     Service: {health.get('service')} v{health.get('version')}")
            print(f"     System health: {health.get('system_health')}\n")
        except Exception as e:
            print(f"  ❌ Cannot connect to {api_url}: {e}")
            print("     Start the server first: poetry run uvicorn src.api.main:app --reload")
            sys.exit(1)

        submit_intent(client)
        print("  📋 Sample intent submitted to compiler.\n")
        print("  Starting simulation in 2s...")
        time.sleep(2 / speed)

        last_snapshot: dict[str, Any] = {}

        for tick_t, phase, ticks in SCENARIO:
            t0 = time.perf_counter()

            # Send all KPIs for this tick
            for kpi_tick in ticks:
                try:
                    snapshot = ingest_kpi(client, kpi_tick)
                    last_snapshot = snapshot
                except Exception as e:
                    print(f"  ⚠️  Ingest failed: {e}")

            print_tick(int(tick_t), phase, ticks, last_snapshot)

            # Sleep adjusted for speed factor
            elapsed = time.perf_counter() - t0
            sleep_time = max(0.0, (1.0 / speed) - elapsed)
            time.sleep(sleep_time)

    print("\n" + "═" * 70)
    print("  ✅  Simulation complete!")
    print(f"  Final system health: {last_snapshot.get('system_health', 'unknown')}")
    print("  View full logs at: GET /mild/status")
    print("═" * 70 + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Intent Drift Engine — Cascade Simulation")
    parser.add_argument("--api-url", default="http://localhost:8000", help="Base URL of the API")
    parser.add_argument("--speed", type=float, default=2.0,
                        help="Simulation speed multiplier (default 2x = 2 ticks/sec)")
    args = parser.parse_args()
    run_simulation(args.api_url, args.speed)
