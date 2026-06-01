"""Story grounding quality checks for ICG narrative output.

The checks here are intentionally lightweight and deterministic.  They do not try
to judge style; they only catch market facts that are easy to hallucinate when
the script uses the Algorithm Reaper / algo-trading motif without supplied data.
"""

from __future__ import annotations

import re
from typing import Any

_UNSUPPORTED_ALGO_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"알고\s*트레이딩\s*비중"),
    re.compile(r"알고\s*트레이딩.*(급증|증가|폭증)"),
    re.compile(r"알고\s*캐스케이드.*(감지|전조|최대|붕괴|정상화)"),
    re.compile(r"algorithmic trading.*(volume|spike|surge)", re.IGNORECASE),
    re.compile(r"algo[- ]?trading.*(volume|spike|surge)", re.IGNORECASE),
)

_ALGO_TRADING_EVIDENCE_TERMS = (
    "algo trading",
    "algorithmic trading",
    "trading volume",
    "알고 트레이딩",
    "알고리즘 거래",
    "거래 비중",
)


class StoryGroundingError(ValueError):
    """Raised when generated story contains unsupported market facts."""


def _evidence_text(context_pack: dict[str, Any] | None) -> str:
    if not context_pack:
        return ""
    parts: list[str] = []
    for item in context_pack.get("top_evidence") or []:
        if not isinstance(item, dict):
            continue
        for key in (
            "id",
            "kind",
            "metric",
            "value",
            "headline_summary",
            "story_role",
            "source",
        ):
            value = item.get(key)
            if value:
                parts.append(str(value))
    for hook in context_pack.get("foreshadow") or []:
        parts.append(str(hook))
    return "\n".join(parts).lower()


def _has_algo_trading_evidence(context_pack: dict[str, Any] | None) -> bool:
    evidence = _evidence_text(context_pack)
    return any(term.lower() in evidence for term in _ALGO_TRADING_EVIDENCE_TERMS)


def _script_market_text(script_dict: dict[str, Any]) -> list[tuple[str, str]]:
    snippets: list[tuple[str, str]] = []
    for panel in script_dict.get("panels") or []:
        if not isinstance(panel, dict):
            continue
        idx = panel.get("idx", "?")
        for field in ("market_ref", "narration"):
            value = panel.get(field)
            if isinstance(value, str) and value.strip():
                snippets.append((f"P{idx}.{field}", value.strip()))
    return snippets


def validate_story_grounding(
    script_dict: dict[str, Any],
    context_pack: dict[str, Any] | None,
    *,
    strict: bool = False,
) -> list[str]:
    """Validate that generated market claims are supported by supplied context.

    Args:
        script_dict: EpisodeScript model_dump output.
        context_pack: Narrative Context Pack stored in analysis ctx.
        strict: If True, raise StoryGroundingError when unsupported claims are found.

    Returns:
        List of warning strings. Empty means no obvious grounding issue was found.
    """
    warnings: list[str] = []
    has_algo_evidence = _has_algo_trading_evidence(context_pack)

    for location, text in _script_market_text(script_dict):
        if has_algo_evidence:
            continue
        for pattern in _UNSUPPORTED_ALGO_PATTERNS:
            if pattern.search(text):
                warnings.append(
                    f"{location}: supplied evidence does not support algo-trading volume/cascade "
                    f"claim: {text}"
                )
                break

    if warnings and strict:
        raise StoryGroundingError("; ".join(warnings))
    return warnings
