"""
engine/narrative/story_planner.py

Deterministic StoryBeatPlan pilot.

This is intentionally not an LLM pass yet. It creates a small beat contract from the
Narrative Context Pack so the existing Claude writer can produce a more coherent
8-panel episode while preserving the current pipeline.
"""

from __future__ import annotations

from typing import Any

from engine.narrative.schema import StoryBeat, StoryBeatPlan

_FUNCTIONS = [
    "HOOK",
    "MARKET_CAUSE",
    "CHARACTER_REACTION",
    "CONFLICT",
    "TURNING_POINT",
    "OUTCOME",
    "NEXT_HOOK",
    "DISCLAIMER",
]


def _evidence_ids(context_pack: dict[str, Any], idx: int) -> list[str]:
    evidence = context_pack.get("top_evidence") or []
    if not evidence:
        return []
    if idx == 1:
        return [str(evidence[0].get("id", "metric:unknown"))]
    if idx == 2:
        return [str(item.get("id", "metric:unknown")) for item in evidence[:2]]
    if idx in (3, 4, 5):
        return [str(evidence[min(idx - 3, len(evidence) - 1)].get("id", "metric:unknown"))]
    return []


def _symbol(context_pack: dict[str, Any], idx: int) -> str:
    symbols = context_pack.get("scene_symbols") or []
    if not symbols:
        return "market dashboard"
    return str(symbols[(idx - 1) % len(symbols)])


def build_story_beat_plan(
    *,
    narrative_context_pack: dict[str, Any],
    hero_id: str,
    villain_id: str,
    battle_result: dict[str, Any],
    scenario_type: str,
) -> StoryBeatPlan:
    """Build a deterministic 8-panel story plan for the current episode."""
    outcome = str(battle_result.get("outcome", "DRAW"))
    market_cause = str(narrative_context_pack.get("market_cause") or "Market signal is mixed.")
    foreshadow = narrative_context_pack.get("foreshadow") or []
    next_hook = str(foreshadow[0]) if foreshadow else "The next market gate remains unresolved."

    beats: list[StoryBeat] = []
    for idx, function in enumerate(_FUNCTIONS, 1):
        if function == "DISCLAIMER":
            required = []
            dialogue_intent = "State investment disclaimer clearly."
            emotional_shift = "Reset audience expectation from story to caution."
        elif scenario_type == "NO_BATTLE":
            required = [hero_id]
            dialogue_intent = "Observe the market calmly without introducing villain combat."
            emotional_shift = "Move from observation to cautious confidence."
        else:
            required = [hero_id, villain_id] if idx in (3, 4, 5, 6) else [hero_id]
            dialogue_intent = "Tie the fixed battle outcome to the supplied market cause."
            emotional_shift = "Escalate pressure, then resolve according to the fixed outcome."

        if function == "NEXT_HOOK":
            dialogue_intent = f"Foreshadow: {next_hook}"
            emotional_shift = "Leave a clear but non-predictive unresolved question."

        beats.append(
            StoryBeat(
                panel_idx=idx,
                dramatic_function=function,  # type: ignore[arg-type]
                market_evidence_ids=_evidence_ids(narrative_context_pack, idx),
                required_character=required,
                emotional_shift=emotional_shift,
                visual_symbol=_symbol(narrative_context_pack, idx),
                dialogue_intent=dialogue_intent,
                forbidden=[
                    "Do not change battle_result.outcome.",
                    "Do not invent unsupported market facts.",
                ],
            )
        )

    return StoryBeatPlan(
        episode_thesis=f"{market_cause} Outcome must remain {outcome}.",
        market_cause_summary=market_cause,
        villain_motivation=(
            "No direct villain combat; show market observation."
            if scenario_type == "NO_BATTLE"
            else f"{villain_id} gains pressure from the supplied market evidence."
        ),
        hero_inner_conflict=f"{hero_id} must respond without denying the fixed outcome: {outcome}.",
        panel_beats=beats,
        next_hook_seed=next_hook,
        factuality_guardrails=list(narrative_context_pack.get("prohibited_claims") or []),
    )
