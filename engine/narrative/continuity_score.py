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
    thread_acknowledgement_score: float
    relationship_reuse_score: float
    beat_compliance_score: float
    total_score: float
    missing_requirements: list[str] = field(default_factory=list)
    matched_terms: list[str] = field(default_factory=list)
    # 2026-10-05 gate rebalance: non-blocking findings (reported, never gate status).
    advisories: list[str] = field(default_factory=list)

    @property
    def status(self) -> str:
        if self.missing_requirements:
            return "fail"
        if self.total_score >= 70:
            return "pass"
        if self.total_score >= 40:
            return "degraded"
        return "fail"

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": "continuity-score-3",
            "source_episode_id": self.source_episode_id,
            "seed": self.seed,
            "opening_overlap_score": self.opening_overlap_score,
            "thread_resolution_score": self.thread_resolution_score,
            "thread_acknowledgement_score": self.thread_acknowledgement_score,
            "relationship_reuse_score": self.relationship_reuse_score,
            "beat_compliance_score": self.beat_compliance_score,
            "total_score": self.total_score,
            "status": self.status,
            "missing_requirements": list(self.missing_requirements),
            "matched_terms": list(self.matched_terms),
            "advisories": list(self.advisories),
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

    opening_applicable = bool(seed)
    opening_score = 0.0
    if seed:
        opening_score, opening_matches = _overlap_score(seed, _panel_text(script_dict, 2), 40.0)
        matched_terms.extend(opening_matches)
        if opening_score < 20:
            missing.append("opening_hook_payoff")

    unresolved = [
        str(item).strip() for item in previous.get("unresolved_threads") or [] if str(item).strip()
    ]
    full_text = _panel_text(script_dict)
    from engine.narrative.thread_contracts import validate_thread_transitions

    # 2026-10-05 gate rebalance: thread-contract errors no longer enter
    # missing_requirements. They are judged (and block) in the production gate
    # (production_quality.validate_production_episode) and the persist/image/publish
    # re-checks; counting them here too made one defect fail two gates at once.
    # validate_thread_transitions is still used below only for the informational
    # thread_resolution_score.
    advisories: list[str] = []
    thread_applicable = bool(unresolved)
    thread_score = 0.0
    if unresolved:
        thread_scores: list[float] = []
        for thread in unresolved[:3]:
            # This component measures acknowledgement/progress, not semantic resolution.
            score, matches = _overlap_score(thread, full_text, 1.0)
            thread_scores.append(score)
            matched_terms.extend(matches)
        thread_score = round(30.0 * (sum(thread_scores) / len(thread_scores)), 2)

        if thread_score < 10:
            # Lexical (exact eojeol) overlap is a weak proxy for reader-perceived
            # continuity; report it as an advisory instead of blocking the episode.
            advisories.append("unresolved_thread_acknowledgement")

    relationship_delta = previous.get("relationship_delta") or {}
    relationship_applicable = isinstance(relationship_delta, dict) and bool(relationship_delta)
    relationship_score = 0.0
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

    beat_score = 0.0
    beats = (story_beat_plan or {}).get("panel_beats") or []
    must_beats = [
        beat for beat in beats if isinstance(beat, dict) and beat.get("must_reference_previous")
    ]
    beat_applicable = bool(must_beats)
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
            required_chars = set(str(item) for item in beat.get("required_character") or [])
            rendered_chars = {
                str(item.get("char_id"))
                for item in (panel or {}).get("characters") or []
                if isinstance(item, dict) and item.get("char_id")
            }
            character_ok = not required_chars or required_chars.issubset(rendered_chars)
            payoff_terms = continuity_keywords(str(beat.get("continuity_payoff") or ""), limit=4)
            payoff_ok = not payoff_terms or any(term in panel_text.lower() for term in payoff_terms)
            if panel_text.strip() and character_ok and payoff_ok:
                compliant += 1
        beat_score = round(10.0 * (compliant / len(must_beats)), 2)
        if beat_score < 10:
            missing.append("must_reference_previous_panel_text")

    # Gate total (2026-10-06 code review CR-1): thread acknowledgement is advisory,
    # so it may only *help* an episode, never fail it. Take the better of
    #   (a) the score without the thread component, and
    #   (b) the legacy score that includes it.
    # (b) keeps every episode that passed before the rebalance passing; (a) stops a
    # weak lexical thread match from failing an otherwise continuous episode.
    gate_max = (
        (40.0 if opening_applicable else 0.0)
        + (20.0 if relationship_applicable else 0.0)
        + (10.0 if beat_applicable else 0.0)
    )
    gate_earned = opening_score + relationship_score + beat_score
    if gate_max:
        gate_total = 100.0 * gate_earned / gate_max
    else:
        # Only the advisory component applies → nothing gates this episode.
        gate_total = 100.0 if thread_applicable else 0.0
    legacy_max = gate_max + (30.0 if thread_applicable else 0.0)
    legacy_total = 100.0 * (gate_earned + thread_score) / legacy_max if legacy_max else 0.0
    total = round(max(gate_total, legacy_total), 2)
    if seed and "opening_hook_payoff" in missing:
        # Missing the opening payoff is the most visible continuity break; cap
        # the total so strict/shadow gates cannot treat incidental defaults as pass.
        total = min(total, 35.0)
    return ContinuityScore(
        source_episode_id=str(source_episode_id) if source_episode_id else None,
        seed=seed,
        opening_overlap_score=opening_score,
        thread_resolution_score=(30.0 if script_dict.get("resolved_threads") and
            not validate_thread_transitions(script_dict, previous,
                (context_pack or {}).get("_resolution_review")) else 0.0),
        thread_acknowledgement_score=thread_score,
        relationship_reuse_score=relationship_score,
        beat_compliance_score=beat_score,
        total_score=total,
        missing_requirements=list(dict.fromkeys(missing)),
        matched_terms=list(dict.fromkeys(matched_terms)),
        advisories=list(dict.fromkeys(advisories)),
    )
