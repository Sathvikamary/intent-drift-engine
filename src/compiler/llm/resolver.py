"""
LLM Semantic Resolver — auto-closes C_sem,t via language model disambiguation.

Sends the raw intent text to an LLM (Google Gemini / OpenAI compatible)
and extracts:
  1. Structured acceptance criteria (measurable, time-bound)
  2. KPI targets and thresholds
  3. Residual ambiguity score → updated C_sem,t

Falls back to the heuristic SemanticGapAnalyzer if no LLM is configured.

Environment variables:
    LLM_PROVIDER       = "gemini" | "openai" | "none"
    LLM_API_KEY        = <your key>
    LLM_MODEL          = "gemini-2.0-flash" | "gpt-4o-mini" | ...
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any

from src.compiler.semantic import SemanticGapAnalyzer, SemanticAnalysisResult


RESOLUTION_PROMPT = """\
You are an Intent Compilation Engine for Intent-Based Networking (IBN).

Your task is to analyze a high-level declarative operational intent and:
1. Identify ALL measurable acceptance criteria (KPI targets, thresholds, time bounds).
2. Detect and list ambiguous or vague terms that prevent precise actuation.
3. Suggest a rewritten, fully-specified version of the intent.
4. Assign a residual_ambiguity_score from 0.0 (fully precise) to 1.0 (fully vague).

Return ONLY a valid JSON object with this exact schema:
{
  "acceptance_criteria": [
    {"kpi": "<name>", "operator": "<lt|gt|lte|gte|eq>", "threshold": <number>, "unit": "<unit>"}
  ],
  "vague_terms": ["<term1>", "<term2>"],
  "rewritten_intent": "<precise restatement>",
  "residual_ambiguity_score": <0.0 to 1.0>,
  "reasoning": "<brief explanation>"
}

Intent to analyze:
\"\"\"
{intent}
\"\"\"
"""


@dataclass
class LLMResolutionResult:
    """Result of LLM-based semantic resolution."""
    raw_intent: str
    rewritten_intent: str
    acceptance_criteria: list[dict[str, Any]]
    vague_terms: list[str]
    residual_ambiguity_score: float    # → new C_sem,t
    reasoning: str
    provider: str
    model: str
    fallback_used: bool = False
    notes: list[str] = field(default_factory=list)


class LLMSemanticResolver:
    """
    Resolves the semantic closure gap C_sem,t via LLM.

    Workflow:
      1. Send intent text to LLM with structured extraction prompt.
      2. Parse JSON response → acceptance criteria + ambiguity score.
      3. Return LLMResolutionResult with updated C_sem,t.
      4. If LLM unavailable → fallback to heuristic SemanticGapAnalyzer.
    """

    def __init__(
        self,
        provider: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
    ) -> None:
        self.provider = (provider or os.getenv("LLM_PROVIDER", "none")).lower()
        self.api_key = api_key or os.getenv("LLM_API_KEY", "")
        self.model = model or os.getenv("LLM_MODEL", "")
        self._heuristic = SemanticGapAnalyzer()

    async def resolve(self, intent: str) -> LLMResolutionResult:
        """Main async resolution entry point."""
        if self.provider == "gemini":
            return await self._resolve_gemini(intent)
        elif self.provider == "openai":
            return await self._resolve_openai(intent)
        else:
            return self._resolve_heuristic(intent)

    # ------------------------------------------------------------------ #
    # Google Gemini                                                        #
    # ------------------------------------------------------------------ #

    async def _resolve_gemini(self, intent: str) -> LLMResolutionResult:
        try:
            import aiohttp
            prompt = RESOLUTION_PROMPT.format(intent=intent)
            model = self.model or "gemini-2.0-flash"
            url = (
                f"https://generativelanguage.googleapis.com/v1beta/models/"
                f"{model}:generateContent?key={self.api_key}"
            )
            payload = {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "temperature": 0.1,
                    "responseMimeType": "application/json",
                },
            }
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    resp.raise_for_status()
                    data = await resp.json()

            text = data["candidates"][0]["content"]["parts"][0]["text"]
            return self._parse_llm_response(intent, text, provider="gemini", model=model)

        except Exception as e:
            result = self._resolve_heuristic(intent)
            result.notes.append(f"Gemini call failed ({e}). Heuristic fallback used.")
            result.fallback_used = True
            return result

    # ------------------------------------------------------------------ #
    # OpenAI-compatible                                                    #
    # ------------------------------------------------------------------ #

    async def _resolve_openai(self, intent: str) -> LLMResolutionResult:
        try:
            import aiohttp
            prompt = RESOLUTION_PROMPT.format(intent=intent)
            model = self.model or "gpt-4o-mini"
            url = "https://api.openai.com/v1/chat/completions"
            payload = {
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.1,
                "response_format": {"type": "json_object"},
            }
            headers = {"Authorization": f"Bearer {self.api_key}"}
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url, json=payload, headers=headers,
                    timeout=aiohttp.ClientTimeout(total=15)
                ) as resp:
                    resp.raise_for_status()
                    data = await resp.json()

            text = data["choices"][0]["message"]["content"]
            return self._parse_llm_response(intent, text, provider="openai", model=model)

        except Exception as e:
            result = self._resolve_heuristic(intent)
            result.notes.append(f"OpenAI call failed ({e}). Heuristic fallback used.")
            result.fallback_used = True
            return result

    # ------------------------------------------------------------------ #
    # Response parsing                                                     #
    # ------------------------------------------------------------------ #

    def _parse_llm_response(
        self,
        intent: str,
        text: str,
        provider: str,
        model: str,
    ) -> LLMResolutionResult:
        """Parse the structured JSON response from the LLM."""
        # Extract JSON block (sometimes wrapped in markdown)
        json_match = re.search(r"\{.*\}", text, re.DOTALL)
        raw = json_match.group(0) if json_match else text

        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            # Fallback parse: extract score only
            score_match = re.search(r'"residual_ambiguity_score"\s*:\s*([0-9.]+)', raw)
            score = float(score_match.group(1)) if score_match else 0.7
            return LLMResolutionResult(
                raw_intent=intent,
                rewritten_intent=intent,
                acceptance_criteria=[],
                vague_terms=[],
                residual_ambiguity_score=min(1.0, max(0.0, score)),
                reasoning="JSON parse failed — partial extraction",
                provider=provider,
                model=model,
                notes=["LLM response JSON parse failed."],
            )

        score = float(parsed.get("residual_ambiguity_score", 0.5))
        return LLMResolutionResult(
            raw_intent=intent,
            rewritten_intent=parsed.get("rewritten_intent", intent),
            acceptance_criteria=parsed.get("acceptance_criteria", []),
            vague_terms=parsed.get("vague_terms", []),
            residual_ambiguity_score=min(1.0, max(0.0, score)),
            reasoning=parsed.get("reasoning", ""),
            provider=provider,
            model=model,
        )

    # ------------------------------------------------------------------ #
    # Heuristic fallback                                                   #
    # ------------------------------------------------------------------ #

    def _resolve_heuristic(self, intent: str) -> LLMResolutionResult:
        result: SemanticAnalysisResult = self._heuristic.analyze(intent)
        return LLMResolutionResult(
            raw_intent=intent,
            rewritten_intent=intent,
            acceptance_criteria=[],
            vague_terms=result.vague_terms_found,
            residual_ambiguity_score=result.c_sem,
            reasoning="Heuristic analysis (LLM provider not configured)",
            provider="heuristic",
            model="SemanticGapAnalyzer",
            fallback_used=True,
            notes=result.notes,
        )
