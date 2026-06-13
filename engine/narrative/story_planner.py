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
    hero_ids: list[str] | None = None,
    villain_ids: list[str] | None = None,
) -> StoryBeatPlan:
    """Build a deterministic 8-panel story plan for the current episode."""
    outcome = str(battle_result.get("outcome", "DRAW"))
    market_cause = str(narrative_context_pack.get("market_cause") or "Market signal is mixed.")
    foreshadow = narrative_context_pack.get("foreshadow") or []
    next_hook = str(foreshadow[0]) if foreshadow else "The next market gate remains unresolved."
    previous_episode = narrative_context_pack.get("previous_episode") or {}
    previous_hook = str(previous_episode.get("next_hook") or "").strip()
    previous_final = str(previous_episode.get("final_panel_summary") or "").strip()
    continuity_seed = previous_hook or previous_final
    active_villain_ids = villain_ids or ([villain_id] if villain_id else [])
    primary_villain = active_villain_ids[0] if active_villain_ids else villain_id
    support_villains = active_villain_ids[1:]
    active_hero_ids = hero_ids or [hero_id]
    primary_hero = active_hero_ids[0] if active_hero_ids else hero_id
    support_heroes = active_hero_ids[1:]

    beats: list[StoryBeat] = []
    for idx, function in enumerate(_FUNCTIONS, 1):
        if function == "DISCLAIMER":
            required = []
            dialogue_intent = "State investment disclaimer clearly."
            emotional_shift = "Reset audience expectation from story to caution."
        elif scenario_type == "NO_BATTLE":
            required = [primary_hero]
            dialogue_intent = "Observe the market calmly without introducing villain combat."
            emotional_shift = "Move from observation to cautious confidence."
        else:
            if scenario_type == "ALLIANCE" and idx in (4, 5) and support_heroes:
                required = [primary_hero, support_heroes[0], primary_villain]
                if support_villains:
                    required.append(support_villains[0])
            elif idx in (4, 5) and support_villains:
                required = [primary_hero, primary_villain, support_villains[0]]
            elif idx in (3, 4, 5, 6):
                required = [primary_hero, primary_villain]
            else:
                required = [primary_hero]
            dialogue_intent = "Tie the fixed battle outcome to the supplied market cause."
            if scenario_type == "ALLIANCE" and support_heroes and idx in (4, 5):
                dialogue_intent = "Show the support hero actively coordinating with the main hero without changing the fixed outcome."
            if support_villains and idx == 5:
                dialogue_intent = "Show the secondary villain amplifying pressure without changing the fixed outcome."
            emotional_shift = "Escalate pressure, then resolve according to the fixed outcome."

        continuity_payoff = None
        must_reference_previous = False
        if continuity_seed and idx == 1:
            continuity_payoff = f"Acknowledge previous episode hook: {continuity_seed}"
            must_reference_previous = True
            dialogue_intent = f"Open by paying off the previous hook before today's market cause: {continuity_seed}"
            emotional_shift = "Connect yesterday's unresolved tension to today's opening pressure."

        if function == "NEXT_HOOK":
            dialogue_intent = f"Foreshadow: {next_hook}"
            emotional_shift = "Leave a clear but non-predictive unresolved question."

        forbidden = [
            "Do not change battle_result.outcome.",
            "Do not invent unsupported market facts.",
            "Do not add villains outside the supplied villain_ids.",
        ]
        if continuity_seed:
            forbidden.append("Do not start a completely new conflict before acknowledging previous_episode.next_hook.")

        beats.append(
            StoryBeat(
                panel_idx=idx,
                dramatic_function=function,  # type: ignore[arg-type]
                market_evidence_ids=_evidence_ids(narrative_context_pack, idx),
                required_character=required,
                emotional_shift=emotional_shift,
                visual_symbol=_symbol(narrative_context_pack, idx),
                dialogue_intent=dialogue_intent,
                forbidden=forbidden,
                continuity_payoff=continuity_payoff,
                must_reference_previous=must_reference_previous,
            )
        )

    return StoryBeatPlan(
        episode_thesis=f"{market_cause} Outcome must remain {outcome}.",
        market_cause_summary=market_cause,
        villain_motivation=(
            "No direct villain combat; show market observation."
            if scenario_type == "NO_BATTLE"
            else (
                f"{primary_villain} leads pressure from the supplied market evidence; "
                f"support_villains={support_villains}."
            )
        ),
        hero_inner_conflict=(
            f"{primary_hero} must respond without denying the fixed outcome: {outcome}. "
            f"support_heroes={support_heroes}."
        ),
        panel_beats=beats,
        next_hook_seed=next_hook,
        factuality_guardrails=list(narrative_context_pack.get("prohibited_claims") or []),
    )
