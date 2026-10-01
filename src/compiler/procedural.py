"""
Procedural Gap Analyzer — C_proc,t component.

Stems from the lack of a validated, policy-compliant execution path or
tool chain. A high C_proc score means the agent must rely on un-auditable
side channels or unverified actuation sequences.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class ToolStatus(str, Enum):
    AVAILABLE = "available"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"
    UNAUDITED = "unaudited"


class PathValidationResult(str, Enum):
    VALID = "valid"
    PARTIAL = "partial"
    INVALID = "invalid"
    UNKNOWN = "unknown"


@dataclass
class ExecutionStep:
    """A single step in a candidate execution path."""
    step_id: str
    tool_name: str
    tool_status: ToolStatus
    policy_compliant: bool
    auditable: bool
    estimated_risk: float      # [0.0, 1.0]


@dataclass
class ExecutionPath:
    """A candidate actuation path for an intent."""
    path_id: str
    steps: list[ExecutionStep]
    policy_validated: bool
    requires_side_channel: bool

    @property
    def all_tools_available(self) -> bool:
        return all(s.tool_status == ToolStatus.AVAILABLE for s in self.steps)

    @property
    def fully_auditable(self) -> bool:
        return all(s.auditable for s in self.steps)

    @property
    def fully_compliant(self) -> bool:
        return all(s.policy_compliant for s in self.steps)

    @property
    def mean_risk(self) -> float:
        if not self.steps:
            return 1.0
        return sum(s.estimated_risk for s in self.steps) / len(self.steps)


@dataclass
class ProceduralAnalysisResult:
    c_proc: float
    best_path: ExecutionPath | None
    validation_result: PathValidationResult
    notes: list[str]
    details: dict[str, Any]


class ProceduralGapAnalyzer:
    """
    Analyzes the procedural closure gap C_proc,t.

    Evaluates candidate execution paths and selects the best valid one.
    Gap is determined by tool availability, auditability, compliance,
    and whether side channels are required.
    """

    def analyze(
        self,
        candidate_paths: list[ExecutionPath],
    ) -> ProceduralAnalysisResult:
        notes: list[str] = []

        if not candidate_paths:
            notes.append("No execution paths provided — procedural gap fully open.")
            return ProceduralAnalysisResult(
                c_proc=1.0,
                best_path=None,
                validation_result=PathValidationResult.UNKNOWN,
                notes=notes,
                details={},
            )

        # Score each path
        scored: list[tuple[float, ExecutionPath]] = []
        for path in candidate_paths:
            score = self._score_path(path)
            scored.append((score, path))

        # Best path = lowest gap score
        best_gap, best_path = min(scored, key=lambda x: x[0])

        validation = self._validate_path(best_path)
        if best_path.requires_side_channel:
            notes.append(
                f"Path '{best_path.path_id}' requires a side channel — procedural risk elevated."
            )
        if not best_path.fully_auditable:
            notes.append(f"Path '{best_path.path_id}' contains non-auditable steps.")
        if not best_path.policy_validated:
            notes.append(f"Path '{best_path.path_id}' has not been policy-validated.")

        return ProceduralAnalysisResult(
            c_proc=best_gap,
            best_path=best_path,
            validation_result=validation,
            notes=notes,
            details={
                "total_paths_evaluated": len(candidate_paths),
                "path_scores": [(p.path_id, g) for g, p in scored],
            },
        )

    def _score_path(self, path: ExecutionPath) -> float:
        """Lower = better (closer to zero gap)."""
        gap = 0.0
        if not path.all_tools_available:
            gap += 0.4
        if not path.fully_auditable:
            gap += 0.3
        if not path.fully_compliant:
            gap += 0.2
        if not path.policy_validated:
            gap += 0.1
        if path.requires_side_channel:
            gap += 0.3
        gap += path.mean_risk * 0.2
        return float(min(gap, 1.0))

    def _validate_path(self, path: ExecutionPath) -> PathValidationResult:
        if path.all_tools_available and path.fully_compliant and path.policy_validated:
            return PathValidationResult.VALID
        if path.requires_side_channel or not path.fully_compliant:
            return PathValidationResult.INVALID
        return PathValidationResult.PARTIAL

    def score(self, candidate_paths: list[ExecutionPath]) -> float:
        return self.analyze(candidate_paths).c_proc
