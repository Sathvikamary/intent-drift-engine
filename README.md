# intent-drift-engine

> **Autonomous Intent Compilation, Multi-Intent Drift Detection & Adaptive Delegation Envelopes**

A research-grade framework for Intent-Based Networking (IBN) that bridges the gap between high-level declarative operational goals and precise, policy-compliant device configurations.

---

## 🏗️ Architecture Overview

```
┌────────────────────────────────────────────────────────────────────────┐
│                       intent-drift-engine                              │
│                                                                        │
│  ┌─────────────────┐   ┌──────────────────┐   ┌────────────────────┐ │
│  │ Intent Compiler │──▶│ Drift Detector   │──▶│ Delegation         │ │
│  │                 │   │                  │   │ Envelope Engine    │ │
│  │ Ct = (Csem,     │   │ Granger Causality│   │                    │ │
│  │  Cevid, Cproc,  │   │ + SCM Engine     │   │ Role Authorization │ │
│  │  Cinst)         │   │                  │   │ + Policy Clearance │ │
│  └─────────────────┘   └──────────────────┘   └────────────────────┘ │
│           │                     │                        │            │
│           └─────────────────────┴────────────────────────┘            │
│                                 │                                      │
│                    ┌────────────▼──────────────┐                      │
│                    │   FastAPI REST Interface   │                      │
│                    │   + WebSocket KPI Stream   │                      │
│                    └───────────────────────────┘                      │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 📐 Core Concepts

### 1. Closure-Gap Vector $C_t$

$$C_t = \big( C_{\text{sem},t},\, C_{\text{evid},t},\, C_{\text{proc},t},\, C_{\text{inst},t} \big)$$

| Component | Symbol | Description |
|-----------|--------|-------------|
| Semantic Gap | $C_{\text{sem},t}$ | Ambiguity in task acceptance criteria |
| Evidentiary Gap | $C_{\text{evid},t}$ | Stale/corrupted/inadmissible context |
| Procedural Gap | $C_{\text{proc},t}$ | Absence of validated execution path |
| Institutional Gap | $C_{\text{inst},t}$ | Missing role authorization/policy clearance |

### 2. Multi-Intent Causal Co-Drift

Three macro-intents in a self-driving network:
- **$\mathcal{I}_{\text{tel}}$** — Telemetry Intent
- **$\mathcal{I}_{\text{anl}}$** — Analytics Intent  
- **$\mathcal{I}_{\text{api}}$** — API Gateway Intent

Causal co-drift chain: `I_tel (queue backpressure) → I_anl (throughput degradation) → I_api (latency violation)`

### 3. Adaptive Delegation Envelopes

Role-bounded, policy-verified authorization windows that prevent misdelegation errors during overclosing attempts.

---

## 🛠️ Tech Stack

| Layer | Technology |
|-------|-----------|
| Runtime | Python 3.11+ |
| API Framework | FastAPI + Uvicorn |
| Async Engine | asyncio + aiohttp |
| Causal Analysis | statsmodels (Granger), pgmpy (SCM) |
| KPI Monitoring | prometheus_client |
| Config Management | Pydantic v2 |
| Testing | pytest + pytest-asyncio |
| Packaging | Poetry |

---

## 📁 Project Structure

```
intent-drift-engine/
├── src/
│   ├── compiler/          # Intent Compiler — Ct vector resolution
│   │   ├── gap_vector.py      # ClosureGapVector dataclass + scoring
│   │   ├── semantic.py        # Semantic gap analyzer (LLM-based)
│   │   ├── evidentiary.py     # Context freshness + integrity checks
│   │   ├── procedural.py      # Execution path validator
│   │   ├── institutional.py   # Role/policy authorization checker
│   │   └── compiler.py        # Main intent compiler orchestrator
│   ├── drift/             # Multi-Intent Drift Detection
│   │   ├── kpi_monitor.py     # KPI baseline tracker
│   │   ├── granger.py         # Granger causality engine
│   │   ├── scm.py             # Structural Causal Model builder
│   │   ├── detector.py        # Real-time drift detector
│   │   └── causal_graph.py    # Causal dependency graph
│   ├── delegation/        # Adaptive Delegation Envelopes
│   │   ├── envelope.py        # Delegation envelope definition
│   │   ├── policy.py          # Policy evaluation engine
│   │   ├── role_auth.py       # Role authorization manager
│   │   └── delegator.py       # Adaptive delegator
│   ├── api/               # FastAPI REST Interface
│   │   ├── main.py            # App entrypoint
│   │   ├── routes/            # Route handlers
│   │   └── websocket.py       # KPI stream WebSocket
│   └── shared/            # Cross-cutting concerns
│       ├── models.py          # Pydantic models
│       ├── config.py          # Settings & configuration
│       ├── logging.py         # Structured logging
│       └── exceptions.py      # Domain exceptions
├── tests/
│   ├── unit/
│   └── integration/
├── docs/                  # Research notes & API docs
├── configs/               # YAML intent definitions
├── scripts/               # Dev utility scripts
├── pyproject.toml
├── Dockerfile
└── README.md
```

---

## 🚀 Quick Start

```bash
# Install dependencies
poetry install

# Run development server
poetry run uvicorn src.api.main:app --reload --port 8000

# Run tests
poetry run pytest

# Submit an intent
curl -X POST http://localhost:8000/intents/compile \
  -H "Content-Type: application/json" \
  -d '{"intent": "Ensure API gateway p99 latency < 50ms", "role": "network-ops"}'
```

---

## 📖 References

1. AgentVerify Framework — Control-flow safety via LTL model checking
2. OpenClaw Harness — Runtime governance for embodied agents
3. MILD Assurance Engine — Multi-intent self-driving network loops
4. INTA Framework — Cross-vendor intent translation

---

## 👤 Author

**Sathvikamary** | sk0981@srmist.edu.in
