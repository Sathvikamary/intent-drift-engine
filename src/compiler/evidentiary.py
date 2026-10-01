"""
Evidentiary Gap Analyzer — C_evid,t component.

Reflects reliance on stale, corrupted, or inadmissible context sources,
forcing reasoning over invalid assumptions.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ContextSourceStatus(str, Enum):
    FRESH = "fresh"
    STALE = "stale"
    CORRUPTED = "corrupted"
    INADMISSIBLE = "inadmissible"
    MISSING = "missing"


@dataclass
class ContextSource:
    """A single piece of context evidence used during intent resolution."""
    source_id: str
    content: Any
    timestamp: float          # Unix epoch seconds when collected
    checksum: str | None = None     # SHA-256 of content at collection time
    admissible: bool = True   # False if source is outside policy bounds
    max_age_seconds: float = 60.0   # SLA for freshness

    def compute_checksum(self) -> str:
        return hashlib.sha256(str(self.content).encode()).hexdigest()

    def validate_integrity(self) -> bool:
        """True when stored checksum matches current content hash."""
        if self.checksum is None:
            return True  # No checksum recorded — assume valid
        return self.compute_checksum() == self.checksum

    def age_seconds(self) -> float:
        return time.time() - self.timestamp

    def status(self) -> ContextSourceStatus:
        if not self.admissible:
            return ContextSourceStatus.INADMISSIBLE
        if not self.validate_integrity():
            return ContextSourceStatus.CORRUPTED
        if self.age_seconds() > self.max_age_seconds:
            return ContextSourceStatus.STALE
        return ContextSourceStatus.FRESH


@dataclass
class EvidentiaryAnalysisResult:
    source_results: list[dict[str, Any]]
    c_evid: float
    fresh_count: int
    stale_count: int
    corrupted_count: int
    inadmissible_count: int
    missing_count: int
    notes: list[str]


class EvidentiaryGapAnalyzer:
    """
    Analyzes the evidentiary closure gap C_evid,t.

    Logic:
      - Each source contributes a per-source gap score based on its status.
      - Aggregate gap is the weighted mean of per-source scores.
      - If no sources are provided, gap = 1.0 (no evidence at all).
    """

    STATUS_WEIGHTS: dict[ContextSourceStatus, float] = {
        ContextSourceStatus.FRESH: 0.0,
        ContextSourceStatus.STALE: 0.6,
        ContextSourceStatus.CORRUPTED: 0.9,
        ContextSourceStatus.INADMISSIBLE: 1.0,
        ContextSourceStatus.MISSING: 1.0,
    }

    def analyze(
        self,
        sources: list[ContextSource],
        required_source_ids: list[str] | None = None,
    ) -> EvidentiaryAnalysisResult:
        notes: list[str] = []
        results: list[dict[str, Any]] = []

        # Track required sources
        provided_ids = {s.source_id for s in sources}
        missing_ids: list[str] = []
        if required_source_ids:
            missing_ids = [sid for sid in required_source_ids if sid not in provided_ids]

        counts: dict[ContextSourceStatus, int] = {s: 0 for s in ContextSourceStatus}
        gap_scores: list[float] = []

        for src in sources:
            status = src.status()
            counts[status] += 1
            weight = self.STATUS_WEIGHTS[status]
            gap_scores.append(weight)
            results.append({"source_id": src.source_id, "status": status.value, "gap": weight})

        # Missing required sources
        for mid in missing_ids:
            counts[ContextSourceStatus.MISSING] += 1
            gap_scores.append(1.0)
            results.append({"source_id": mid, "status": "missing", "gap": 1.0})
            notes.append(f"Required context source '{mid}' is missing.")

        if not gap_scores:
            notes.append("No context sources provided — evidentiary gap fully open.")
            c_evid = 1.0
        else:
            c_evid = float(sum(gap_scores) / len(gap_scores))

        if counts[ContextSourceStatus.STALE]:
            notes.append(f"{counts[ContextSourceStatus.STALE]} stale source(s) detected.")
        if counts[ContextSourceStatus.CORRUPTED]:
            notes.append(f"{counts[ContextSourceStatus.CORRUPTED]} corrupted source(s) detected.")
        if counts[ContextSourceStatus.INADMISSIBLE]:
            notes.append(f"{counts[ContextSourceStatus.INADMISSIBLE]} inadmissible source(s) detected.")

        return EvidentiaryAnalysisResult(
            source_results=results,
            c_evid=c_evid,
            fresh_count=counts[ContextSourceStatus.FRESH],
            stale_count=counts[ContextSourceStatus.STALE],
            corrupted_count=counts[ContextSourceStatus.CORRUPTED],
            inadmissible_count=counts[ContextSourceStatus.INADMISSIBLE],
            missing_count=counts[ContextSourceStatus.MISSING],
            notes=notes,
        )

    def score(self, sources: list[ContextSource]) -> float:
        return self.analyze(sources).c_evid
