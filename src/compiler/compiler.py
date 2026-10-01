"""
Intent Compiler — Main Orchestrator.

Bridges the gap between high-level declarative goals and enforceable
low-level device configurations by resolving the 4-dimensional
closure-gap vector C_t = (C_sem, C_evid, C_proc, C_inst).
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from src.compiler.evidentiary import ContextSource, EvidentiaryGapAnalyzer
from src.compiler.gap_vector import ClosureGapVector
from src.compiler.institutional import InstitutionalGapAnalyzer, PolicyClearance
from src.compiler.procedural import ExecutionPath, ProceduralGapAnalyzer
from src.compiler.semantic import SemanticGapAnalyzer


class CompilationDecision(str, Enum):
    PROCEED = "proceed"           # All gaps closed — safe to compile & actuate
    DEFER = "defer"               # Gaps partially open — wait for more context
    REJECT = "reject"             # Institutional or procedural blocking gap
    OVERCLOSE_RISK = "overclose_risk"  # Agent attempting action on underspecified intent


@dataclass
class IntentCompilationRequest:
    """Input to the intent compiler."""
    intent_id: str
    intent_text: str
    role: str
    domain: str
    required_actions: list[str]
    context_sources: list[ContextSource] = field(default_factory=list)
    candidate_paths: list[ExecutionPath] = field(default_factory=list)
    clearances: list[PolicyClearance] = field(default_factory=list)
    required_source_ids: list[str] | None = None
    closure_threshold: float = 0.2        # Max acceptable gap per dimension
    max_time_to_action: float | None = None  # Optional deadline (seconds from now)


@dataclass
class IntentCompilationResult:
    """Output of the intent compiler."""
    intent_id: str
    request: IntentCompilationRequest
    gap_vector: ClosureGapVector
    decision: CompilationDecision
    selected_path: ExecutionPath | None
    compilation_time_ms: float
    notes: list[str]
    component_details: dict[str, Any]
    timestamp: float = field(default_factory=time.time)

    def is_safe_to_actuate(self) -> bool:
        return self.decision == CompilationDecision.PROCEED

    def summary(self) -> str:
        return (
            f"Intent '{self.intent_id}': {self.decision.value} | "
            f"Ct={self.gap_vector} | "
            f"compiled in {self.compilation_time_ms:.1f}ms"
        )


class IntentCompiler:
    """
    Orchestrates all four gap analyzers to produce a compiled intent or
    a structured rejection with residual gap attribution.

    Decision logic:
      PROCEED       → all gap components ≤ closure_threshold
      REJECT        → institutional gap = 1.0 OR procedural gap = 1.0
      OVERCLOSE_RISK → agent forced closure detected (all gaps forced < threshold
                        without proper evidence)
      DEFER         → partial gaps remain, request more resolution time
    """

    def __init__(self) -> None:
        self._sem = SemanticGapAnalyzer()
        self._evid = EvidentiaryGapAnalyzer()
        self._proc = ProceduralGapAnalyzer()
        self._inst = InstitutionalGapAnalyzer()

    def compile(self, request: IntentCompilationRequest) -> IntentCompilationResult:
        """Synchronous compilation — resolves all gap components."""
        t_start = time.perf_counter()
        notes: list[str] = []
        details: dict[str, Any] = {}

        # ── Semantic ────────────────────────────────────────────────────
        sem_result = self._sem.analyze(request.intent_text)
        c_sem = sem_result.c_sem
        details["semantic"] = {
            "c_sem": c_sem,
            "vague_terms": sem_result.vague_terms_found,
            "notes": sem_result.notes,
        }
        notes.extend(sem_result.notes)

        # ── Evidentiary ─────────────────────────────────────────────────
        evid_result = self._evid.analyze(
            request.context_sources,
            required_source_ids=request.required_source_ids,
        )
        c_evid = evid_result.c_evid
        details["evidentiary"] = {
            "c_evid": c_evid,
            "fresh": evid_result.fresh_count,
            "stale": evid_result.stale_count,
            "corrupted": evid_result.corrupted_count,
            "notes": evid_result.notes,
        }
        notes.extend(evid_result.notes)

        # ── Procedural ──────────────────────────────────────────────────
        proc_result = self._proc.analyze(request.candidate_paths)
        c_proc = proc_result.c_proc
        details["procedural"] = {
            "c_proc": c_proc,
            "validation": proc_result.validation_result.value if proc_result.validation_result else None,
            "notes": proc_result.notes,
        }
        notes.extend(proc_result.notes)

        # ── Institutional ───────────────────────────────────────────────
        inst_result = self._inst.analyze(
            role=request.role,
            domain=request.domain,
            required_actions=request.required_actions,
            clearances=request.clearances,
        )
        c_inst = inst_result.c_inst
        details["institutional"] = {
            "c_inst": c_inst,
            "auth_level": inst_result.authorization_level.value,
            "uncovered_actions": inst_result.uncovered_actions,
            "notes": inst_result.notes,
        }
        notes.extend(inst_result.notes)

        # ── Build gap vector ────────────────────────────────────────────
        gap_vector = ClosureGapVector(
            c_sem=c_sem,
            c_evid=c_evid,
            c_proc=c_proc,
            c_inst=c_inst,
        )

        # ── Compile decision ────────────────────────────────────────────
        decision = self._decide(gap_vector, request.closure_threshold, inst_result, proc_result)

        t_end = time.perf_counter()
        compilation_time_ms = (t_end - t_start) * 1000

        return IntentCompilationResult(
            intent_id=request.intent_id,
            request=request,
            gap_vector=gap_vector,
            decision=decision,
            selected_path=proc_result.best_path,
            compilation_time_ms=compilation_time_ms,
            notes=notes,
            component_details=details,
        )

    async def compile_async(self, request: IntentCompilationRequest) -> IntentCompilationResult:
        """Async wrapper for concurrent multi-intent compilation."""
        return await asyncio.get_event_loop().run_in_executor(None, self.compile, request)

    def _decide(
        self,
        gap: ClosureGapVector,
        threshold: float,
        inst_result: Any,
        proc_result: Any,
    ) -> CompilationDecision:
        from src.compiler.institutional import AuthorizationLevel
        from src.compiler.procedural import PathValidationResult

        # Hard blocks
        if inst_result.authorization_level == AuthorizationLevel.DENIED:
            return CompilationDecision.REJECT
        if proc_result.validation_result == PathValidationResult.INVALID and gap.c_proc >= 0.9:
            return CompilationDecision.REJECT

        # All closed
        if gap.is_closed(threshold):
            return CompilationDecision.PROCEED

        # Overclosing heuristic: if semantic and evidentiary are high,
        # but the agent has a path — flag overclose risk
        if gap.c_sem > 0.5 and gap.c_evid > 0.5 and gap.c_proc <= threshold:
            return CompilationDecision.OVERCLOSE_RISK

        return CompilationDecision.DEFER
