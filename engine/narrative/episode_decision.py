"""Resolve editorial diversity once, without changing market or awakening rules."""
from dataclasses import asdict
from typing import get_args

from engine.narrative.episode_type_engine import EpisodeType, EpisodeTypeResult, to_scenario_type
from engine.narrative.storyline_guard import latest_streak

VERSION = "episode-decision-1"
THRESHOLD = 3  # Provisional editorial review trigger, not a market signal.
_PROTECTED_STEPS = {"MANUAL_OVERRIDE", "STEP_0", "STEP_0_5", "STEP_1", "STEP_2"}


def resolve_episode_decision(candidate: EpisodeTypeResult, *, risk_level: str,
                             event_type: str, recent_scenarios: list[str],
                             has_market_evidence: bool) -> dict:
    if candidate.episode_type not in get_args(EpisodeType):
        raise ValueError("Unknown candidate episode type")
    if candidate.scenario_type != to_scenario_type(candidate.episode_type):
        raise ValueError("Candidate episode type and scenario disagree")
    streak = latest_streak(recent_scenarios, "NO_BATTLE")
    result = asdict(candidate)
    result.update(version=VERSION, candidate_type=candidate.episode_type,
                  candidate_scenario=candidate.scenario_type,
                  recent_no_battle_streak=streak, threshold=THRESHOLD,
                  policy_applied=False, protected_reason="",
                  action_mode=("OBSERVATION" if candidate.scenario_type == "NO_BATTLE"
                               else "COMBAT"))
    if (candidate.determined_by_step in _PROTECTED_STEPS
            or candidate.episode_type in {"CONFLICT", "FLASHBACK"}):
        result["protected_reason"] = candidate.determined_by_step
        return result
    if candidate.scenario_type != "NO_BATTLE" or streak < THRESHOLD:
        return result
    battle_allowed = (has_market_evidence and risk_level in {"MEDIUM", "HIGH"}
                      and event_type in {"BATTLE", "SHOCK"})
    result.update(episode_type="BATTLE" if battle_allowed else "TACTICAL",
                  scenario_type="ONE_VS_ONE" if battle_allowed else "NO_BATTLE",
                  form_bonus=0, slide_count=8, policy_applied=True,
                  action_mode="COMBAT" if battle_allowed else "TACTICAL_ACTION",
                  reason=("editorial_diversity_basic_battle" if battle_allowed
                          else "editorial_diversity_tactical_action"))
    return result


def validate_saved_decision(ctx: dict) -> None:
    decision = ctx.get("episode_decision")
    if not isinstance(decision, dict) or decision.get("version") != VERSION:
        raise ValueError("Stored episode decision is malformed or unsupported")
    if (decision.get("episode_type") not in get_args(EpisodeType)
            or decision.get("action_mode") not in {"COMBAT", "OBSERVATION", "TACTICAL_ACTION"}
            or decision.get("scenario_type") != to_scenario_type(decision.get("episode_type", ""))
            or decision.get("scenario_type") != ctx.get("scenario_type")
            or decision.get("episode_type") != ctx.get("episode_type_v3")
            or decision.get("form_bonus") != ctx.get("form_bonus")):
        raise ValueError("Stored episode decision disagrees with analysis context")


def narrative_action_contract(decision: dict | None) -> str:
    if not decision or decision.get("action_mode") != "TACTICAL_ACTION":
        return ""
    return ("FINAL ACTION CONTRACT: NO_BATTLE means no combat verdict, not absence of action. "
            "Use visible non-combat state-changing actions such as evacuation, rescue, tracking, "
            "evasion or operating a barrier. Use only the approved cast. No new enemy, attacks, "
            "victory, defeat, awakening or invented market crisis. Keep supplied market facts.")
