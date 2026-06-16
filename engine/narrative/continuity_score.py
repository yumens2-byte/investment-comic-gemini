"""Deterministic continuity scoring for generated ICG episodes."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

_STOPWORDS = {
    "previous",
    "episode",
    "remains",
    "unresolved",
    "emotionally",
    "track",
    "continuing",
    "pressure",
    "from",
    "villain",
    "must",
    "continue",
    "the",
    "and",
    "이전",
    "회차",
    "아직",
    "다음",
    "시장",
    "압력",
    "감정",
    "갈등",
    "계속",
}


@dataclass(frozen=True)
class ContinuityScore:
    """Panel-level continuity score used by strict and shadow gates."""

    source_episode_id: str | None
    seed: str
    opening_overlap_score: float
    thread_resolution_score: float
    relationship_reuse_score: float
    beat_compliance_score: float
    total_score: float
    missing_requirements: list[str] = field(default_factory=list)
    matched_terms: list[str] = field(default_factory=list)

    @property
    def status(self) -> str:
        if self.total_score >= 70:
            return "pass"
        if self.total_score >= 40:
            return "degraded"
        return "fail"

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": "continuity-score-1",
            "source_episode_id": self.source_episode_id,
            "seed": self.seed,
            "opening_overlap_score": self.opening_overlap_score,
            "thread_resolution_score": self.thread_resolution_score,
            "relationship_reuse_score": self.relationship_reuse_score,
            "beat_compliance_score": self.beat_compliance_score,
            "total_score": self.total_score,
            "status": self.status,
            "missing_requirements": list(self.missing_requirements),
            "matched_terms": list(self.matched_terms),
        }


def continuity_keywords(text: str, *, limit: int = 8) -> list[str]:
    """Return compact, order-preserving keywords for deterministic overlap checks."""
    words = re.findall(r"[0-9A-Za-z가-힣]{2,}", text or "")
    result: list[str] = []
    for word in words:
        lowered = word.lower()
        if len(lowered) < 2 or lowered in _STOPWORDS:
            continue
        if lowered not in result:
            result.append(lowered)
    return result[:limit]


def _panel_text(script_dict: dict[str, Any], panel_limit: int | None = None) -> str:
    panels = [p for p in (script_dict.get("panels") or []) if isinstance(p, dict)]
    if panel_limit is not None:
        panels = panels[:panel_limit]
    parts: list[str] = []
    for panel in panels:
        for field_name in ("narration", "key_text", "market_ref"):
            value = panel.get(field_name)
            if isinstance(value, str) and value.strip():
                parts.append(value.strip())
    return "\n".join(parts).lower()


def _overlap_score(seed: str, text: str, max_score: float) -> tuple[float, list[str]]:
    keywords = continuity_keywords(seed)
    if not keywords:
        return (max_score if not seed else 0.0), []
    matched = [keyword for keyword in keywords if keyword in text]
    return round(max_score * (len(matched) / len(keywords)), 2), matched


def score_story_continuity(
    script_dict: dict[str, Any],
    context_pack: dict[str, Any] | None,
    story_beat_plan: dict[str, Any] | None = None,
) -> ContinuityScore:
    """Score whether generated script continues prior hook/thread/relationship state."""
    previous = (context_pack or {}).get("previous_episode") or {}
    seed = str(previous.get("next_hook") or previous.get("must_continue_from") or "").strip()
    source_episode_id = previous.get("source_episode_id")
    missing: list[str] = []
    matched_terms: list[str] = []

    opening_score = 40.0
    if seed:
        opening_score, opening_matches = _overlap_score(seed, _panel_text(script_dict, 2), 40.0)
        matched_terms.extend(opening_matches)
        if opening_score < 20:
            missing.append("opening_hook_payoff")

    unresolved = [
        str(item).strip() for item in previous.get("unresolved_threads") or [] if str(item).strip()
    ]
    full_text = _panel_text(script_dict)
    resolved_text = "\n".join(
        str(item) for item in script_dict.get("resolved_threads") or []
    ).lower()
    thread_score = 30.0
    if unresolved:
        thread_scores: list[float] = []
        for thread in unresolved[:3]:
            score, matches = _overlap_score(thread, f"{full_text}\n{resolved_text}", 1.0)
            thread_scores.append(score)
            matched_terms.extend(matches)
        thread_score = round(30.0 * (max(thread_scores) if thread_scores else 0.0), 2)
        if thread_score < 10:
            missing.append("unresolved_thread_resolution")

    relationship_delta = previous.get("relationship_delta") or {}
    relationship_score = 20.0
    if isinstance(relationship_delta, dict) and relationship_delta:
        relation_terms: list[str] = []
        for pair, delta in list(relationship_delta.items())[:3]:
            relation_terms.extend(continuity_keywords(str(pair), limit=4))
            relation_terms.extend(continuity_keywords(str(delta), limit=4))
        relation_terms = list(dict.fromkeys(relation_terms))[:10]
        if relation_terms:
            matched_relationship_terms = [term for term in relation_terms if term in full_text]
            matched_terms.extend(matched_relationship_terms)
            relationship_score = round(
                20.0 * (len(matched_relationship_terms) / len(relation_terms)), 2
            )
            if relationship_score == 0:
                missing.append("relationship_delta_reuse")

    beat_score = 10.0
    beats = (story_beat_plan or {}).get("panel_beats") or []
    must_beats = [
        beat for beat in beats if isinstance(beat, dict) and beat.get("must_reference_previous")
    ]
    if must_beats:
        panels = [p for p in (script_dict.get("panels") or []) if isinstance(p, dict)]
        compliant = 0
        for beat in must_beats:
            try:
                idx = int(beat.get("panel_idx"))
            except (TypeError, ValueError):
                continue
            panel = next((p for p in panels if p.get("idx") == idx), None)
            panel_text = (
                " ".join(
                    str(panel.get(field_name) or "")
                    for field_name in ("narration", "key_text", "market_ref")
                )
                if panel
                else ""
            )
            if panel_text.strip():
                compliant += 1
        beat_score = round(10.0 * (compliant / len(must_beats)), 2)
        if beat_score < 10:
            missing.append("must_reference_previous_panel_text")

    total = round(opening_score + thread_score + relationship_score + beat_score, 2)
    if seed and "opening_hook_payoff" in missing:
        # Missing the opening payoff is the most visible continuity break; cap
        # the total so strict/shadow gates cannot treat incidental defaults as pass.
        total = min(total, 35.0)
    return ContinuityScore(
        source_episode_id=str(source_episode_id) if source_episode_id else None,
        seed=seed,
        opening_overlap_score=opening_score,
        thread_resolution_score=thread_score,
        relationship_reuse_score=relationship_score,
        beat_compliance_score=beat_score,
        total_score=total,
        missing_requirements=list(dict.fromkeys(missing)),
        matched_terms=list(dict.fromkeys(matched_terms)),
    )
