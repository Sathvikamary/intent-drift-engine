"""
Semantic Gap Analyzer — C_sem,t component.

Measures ambiguity in the task acceptance criteria of an incoming intent.
Uses heuristic NLP scoring and (optionally) LLM-based disambiguation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


# ---------------------------------------------------------------------------
# Heuristic signals for semantic ambiguity
# ---------------------------------------------------------------------------

# Words that indicate vague / underspecified targets
VAGUE_TERMS = {
    "good", "fast", "slow", "better", "optimal", "reasonable",
    "acceptable", "sufficient", "adequate", "improve", "fix", "ensure",
}

# Quantitative specificity markers — reduce gap score
QUANTITATIVE_PATTERNS = [
    r"\d+\s?(ms|sec|s|mbps|gbps|%|packets|requests|rps|rpm)",
    r"p\d{2}",          # p50, p99, etc.
    r"sla\s?=",
    r"threshold\s?[=:<>]",
    r"<\s?\d+",
    r">\s?\d+",
    r"between\s+\d+\s+and\s+\d+",
]

# Acceptance criteria anchors — strongly reduce gap
ACCEPTANCE_ANCHORS = [
    r"when\s+.+\s+then",
    r"if\s+.+\s+fail",
    r"success\s+condition",
    r"acceptance\s+criteria",
    r"kpi\s+(target|bound|limit)",
]


@dataclass
class SemanticAnalysisResult:
    """Result of semantic gap analysis for a single intent string."""
    raw_intent: str
    c_sem: float                         # [0.0, 1.0] — 0 = fully specified
    vague_terms_found: list[str]
    quantitative_matches: list[str]
    acceptance_anchor_matches: list[str]
    confidence: float                    # Analyzer confidence in its own score
    notes: list[str]


class SemanticGapAnalyzer:
    """
    Analyzes the semantic closure gap C_sem,t for a declared intent.

    Scoring logic:
      - Start at base gap = 1.0 (fully unresolved).
      - Deduct points for quantitative specificity (+precision signals).
      - Add penalty for vague vocabulary present in the intent.
      - Deduct points for explicit acceptance criteria anchors.
    """

    def __init__(
        self,
        vague_penalty: float = 0.08,
        quantitative_credit: float = 0.15,
        anchor_credit: float = 0.25,
    ) -> None:
        self.vague_penalty = vague_penalty
        self.quantitative_credit = quantitative_credit
        self.anchor_credit = anchor_credit

        self._quant_patterns = [re.compile(p, re.IGNORECASE) for p in QUANTITATIVE_PATTERNS]
        self._anchor_patterns = [re.compile(p, re.IGNORECASE) for p in ACCEPTANCE_ANCHORS]

    def analyze(self, intent: str) -> SemanticAnalysisResult:
        """Compute semantic gap score for the given intent string."""
        text = intent.lower()
        gap = 1.0
        notes: list[str] = []

        # --- Vague term penalty ----------------------------------------
        words = set(re.findall(r"\b\w+\b", text))
        vague_found = list(words & VAGUE_TERMS)
        penalty = min(len(vague_found) * self.vague_penalty, 0.3)
        gap += penalty
        if vague_found:
            notes.append(f"Vague terms detected: {vague_found}. Increased semantic gap.")

        # --- Quantitative specificity credit ----------------------------
        quant_matches: list[str] = []
        for pat in self._quant_patterns:
            matches = pat.findall(intent)
            quant_matches.extend(matches)
        credit = min(len(quant_matches) * self.quantitative_credit, 0.6)
        gap -= credit
        if quant_matches:
            notes.append(f"Quantitative markers found: {quant_matches}.")

        # --- Acceptance anchor credit -----------------------------------
        anchor_matches: list[str] = []
        for pat in self._anchor_patterns:
            if pat.search(intent):
                anchor_matches.append(pat.pattern)
        anchor_credit = min(len(anchor_matches) * self.anchor_credit, 0.5)
        gap -= anchor_credit
        if anchor_matches:
            notes.append(f"Acceptance criteria anchors detected.")

        # Clamp to [0, 1]
        gap = float(max(0.0, min(1.0, gap)))

        # Confidence: low when no signals at all
        total_signals = len(vague_found) + len(quant_matches) + len(anchor_matches)
        confidence = min(0.4 + total_signals * 0.1, 1.0)

        return SemanticAnalysisResult(
            raw_intent=intent,
            c_sem=gap,
            vague_terms_found=vague_found,
            quantitative_matches=quant_matches,
            acceptance_anchor_matches=anchor_matches,
            confidence=confidence,
            notes=notes,
        )

    def score(self, intent: str) -> float:
        """Convenience method — returns c_sem float directly."""
        return self.analyze(intent).c_sem
