from copy import deepcopy

import pytest

from engine.narrative.episode_decision import resolve_episode_decision, validate_saved_decision
from engine.narrative.episode_type_engine import EpisodeTypeResult, determine_episode_type


def candidate(kind="TACTICAL", scenario="NO_BATTLE", step="STEP_3_4"):
    return EpisodeTypeResult(kind, scenario, "ACT_3", step, "candidate")


def resolve(c=None, **overrides):
    params = dict(risk_level="MEDIUM", event_type="BATTLE",
                  recent_scenarios=["NO_BATTLE"] * 5, has_market_evidence=True)
    params.update(overrides)
    return resolve_episode_decision(c or candidate(), **params)


def test_day64_reproduction_and_market_inputs_unchanged():
    arc = {"arc_day": 64, "arc_tension": 27}
    delta = {"reversal_state": "NONE"}
    original = deepcopy((arc, delta))
    c = determine_episode_type(arc, delta, "MEDIUM", ["OBSERVATION"] * 3)
    assert c.episode_type == "TACTICAL"
    result = resolve(c)
    assert (result["episode_type"], result["scenario_type"], result["action_mode"]) == (
        "BATTLE", "ONE_VS_ONE", "COMBAT")
    assert result["form_bonus"] == 0 and result["slide_count"] == 8
    assert (arc, delta) == original


@pytest.mark.parametrize("overrides", [dict(risk_level="LOW"), dict(event_type="NORMAL"),
                                      dict(has_market_evidence=False)])
def test_no_combat_when_market_does_not_allow_it(overrides):
    result = resolve(**overrides)
    assert result["episode_type"] == "TACTICAL"
    assert result["scenario_type"] == "NO_BATTLE"
    assert result["action_mode"] == "TACTICAL_ACTION"


@pytest.mark.parametrize("step", ["MANUAL_OVERRIDE", "STEP_0", "STEP_0_5", "STEP_1", "STEP_2"])
def test_canon_priority_is_preserved(step):
    c = candidate(step=step)
    result = resolve(c)
    assert not result["policy_applied"]
    assert result["episode_type"] == c.episode_type


def test_awakening_and_finale_keep_form_bonus():
    for kind, scenario, bonus in [("BATTLE_PLUS_FORM3", "ONE_VS_ONE", 20),
                                  ("SEASON_FINALE", "ALLIANCE", 0)]:
        c = candidate(kind, scenario)
        c.form_bonus = bonus
        assert resolve(c)["form_bonus"] == bonus
        assert resolve(c)["episode_type"] == kind


def test_short_streak_and_older_tail_do_not_trigger_policy():
    assert not resolve(recent_scenarios=["NO_BATTLE", "ONE_VS_ONE"] + ["NO_BATTLE"] * 5)["policy_applied"]


def test_conflict_and_flashback_are_preserved():
    for kind in ["CONFLICT", "FLASHBACK"]:
        assert resolve(candidate(kind))["episode_type"] == kind


def test_long_arc_aftermath_requires_latest_combat():
    arc = {"arc_day": 66, "arc_tension": 27}
    assert determine_episode_type(arc, {}, "LOW", ["OBSERVATION", "HERO_VICTORY"]).episode_type == "INTEL"
    assert determine_episode_type(arc, {}, "LOW", ["HERO_VICTORY"]).episode_type == "AFTERMATH"
    arc.update(form3_activated=True, form3_countdown=1)
    assert determine_episode_type(arc, {}, "LOW", ["OBSERVATION"]).determined_by_step == "STEP_0"


def test_saved_decision_rejects_context_mismatch_and_unknown_type():
    decision = resolve()
    ctx = dict(episode_decision=decision, episode_type_v3="BATTLE", scenario_type="ONE_VS_ONE", form_bonus=0)
    validate_saved_decision(ctx)
    with pytest.raises(ValueError):
        validate_saved_decision(dict(ctx, form_bonus=20))
    with pytest.raises(ValueError):
        resolve(candidate("TYPO", "ONE_VS_ONE"))
