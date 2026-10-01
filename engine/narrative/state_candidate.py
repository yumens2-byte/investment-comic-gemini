"""Build future state without changing the confirmed story clock."""
from __future__ import annotations

import copy


def build_state_candidate(episode_date: str, ctx: dict, script: dict) -> dict:
    from engine.arc.arc_state_engine import update_after_episode as update_arc
    from engine.character.story_state_manager import update_after_episode as update_story

    outcome = (ctx.get("battle_result") or {}).get("outcome", "DRAW")
    snapshot = ctx.get("_snapshot_row") or {}
    prior_arc = ctx.get("_arc_state")
    prior_story = ctx.get("_story_state")
    return {
        "version": "state-candidate-1", "episode_date": episode_date,
        "previous_episode": copy.deepcopy(ctx.get("previous_episode") or
            (ctx.get("narrative_context_pack") or {}).get("previous_episode") or {}),
        "base_arc": copy.deepcopy(prior_arc),
        "arc_after": update_arc(
            state=prior_arc, outcome=outcome,
            episode_type=ctx.get("episode_type_v3") or ctx.get("scenario_type", "ONE_VS_ONE"),
            snapshot=snapshot, new_villain=ctx.get("_new_villain_id"),
            open_hook=script.get("next_hook"), episode_date=episode_date,
        ) if prior_arc is not None else None,
        "story_after": update_story(
            prior_story, ctx.get("_guest_characters") or [], outcome,
            float(snapshot.get("vix") or 0), episode_date=episode_date,
        ) if prior_story else None,
    }
