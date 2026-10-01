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


class StoryContinuityError(ValueError):
    """Raised when generated story fails required previous-episode continuity."""


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


def build_continuity_retry_feedback(
    script_dict: dict[str, Any],
    context_pack: dict[str, Any] | None,
    story_beat_plan: dict[str, Any] | None = None,
) -> str | None:
    """Build explicit LLM retry instructions from deterministic continuity scoring.

    The strict gate should not silently rewrite an episode after generation.  When
    the generated JSON misses prior continuity, send Claude a narrow retry note
    that cites only the already-supplied previous_episode state and the missing
    deterministic requirements.
    """
    from engine.narrative.continuity import sanitize_continuity_bundle
    from engine.narrative.continuity_score import score_story_continuity

    safe_context = dict(context_pack or {})
    safe_context["previous_episode"] = sanitize_continuity_bundle(
        safe_context.get("previous_episode") or {}
    ) or {}
    score = score_story_continuity(script_dict, safe_context, story_beat_plan)
    if score.status == "pass" or not (score.seed or score.source_episode_id):
        return None

    previous = sanitize_continuity_bundle(
        safe_context.get("previous_episode") or {}
    ) or {}
    unresolved = [
        str(item).strip() for item in previous.get("unresolved_threads") or [] if str(item).strip()
    ]
    lines = [
        "## STRICT CONTINUITY RETRY — previous episode payoff is mandatory",
        f"- prior_source_episode_id: {score.source_episode_id or previous.get('source_episode_id', '')}",
        f"- current_continuity_score: {score.total_score:.1f} ({score.status})",
        "- missing_requirements: "
        + (", ".join(score.missing_requirements) or "continuity_score_below_threshold"),
    ]
    if score.seed:
        lines.extend(
            [
                f"- previous_next_hook_to_pay_off: {score.seed}",
                "- Required: panel 1 must paraphrase the safe prior hook and show its concrete consequence before today's cause.",
                "- Do not copy unsupported causal wording merely because it appeared in an older episode.",
            ]
        )
    if unresolved:
        lines.extend(
            [
                "- unresolved_threads_to_resolve_or_acknowledge: " + "; ".join(unresolved[:3]),
                "- Required: acknowledge, advance, or resolve a supplied reader-facing thread through an observable panel action.",
                "- Put a thread in resolved_threads only when the episode visibly resolves it; otherwise keep it unresolved.",
            ]
        )
    lines.extend(
        [
            "- Do not invent new previous-episode facts or copy operational English placeholders.",
            "- Keep all EpisodeScript schema limits, including panel narration/key_text lengths, and return JSON only.",
        ]
    )
    return "\n".join(lines)


def validate_story_continuity(
    script_dict: dict[str, Any],
    context_pack: dict[str, Any] | None,
    story_beat_plan: dict[str, Any] | None = None,
    *,
    strict: bool = False,
) -> list[str]:
    """Validate that generated panels pay off previous-episode continuity."""
    from engine.narrative.continuity_score import score_story_continuity

    score = score_story_continuity(script_dict, context_pack, story_beat_plan)
    if not score.seed and not score.source_episode_id:
        return []

    warnings: list[str] = []
    if score.status != "pass":
        warnings.append(
            "Continuity score %.1f below threshold 70 (status=%s, missing=%s)"
            % (score.total_score, score.status, ",".join(score.missing_requirements) or "none")
        )

    if warnings and strict:
        raise StoryContinuityError("; ".join(warnings))
    return warnings


def build_continuity_quality_payload(
    script_dict: dict[str, Any],
    context_pack: dict[str, Any] | None,
    story_beat_plan: dict[str, Any] | None = None,
    *,
    strict_enabled: bool = False,
) -> dict[str, Any]:
    """Build persistable continuity-quality metadata for shadow/strict operation."""
    from engine.narrative.continuity_score import score_story_continuity

    score = score_story_continuity(script_dict, context_pack, story_beat_plan)
    warnings = []
    if score.status != "pass" and (score.seed or score.source_episode_id):
        warnings.append(
            "Continuity score %.1f below threshold 70 (missing=%s)"
            % (score.total_score, ",".join(score.missing_requirements) or "none")
        )
    payload = score.to_dict()
    payload.update(
        {
            "strict_enabled": strict_enabled,
            "warnings": warnings,
            "previous_source_episode_id": score.source_episode_id,
        }
    )
    return payload


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
