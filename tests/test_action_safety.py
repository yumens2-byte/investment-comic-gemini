"""DR-03: deterministic combat-brief checks, anchored on the 2026-10-03 incident."""
import json
from pathlib import Path

import pytest

from engine.image.action_safety import check_action, check_observation_actions, check_script_actions

REFUSED_P3 = ("Debt Titan materializes from the ledger stacks, slamming a chain of debt bonds "
              "toward Iron Securities Nuna who raises her shield to deflect")
ACCEPTED_P3 = ("Debt Titan rises out of the ledger stacks and sends a surging stream of glowing "
               "debt-bond chains across the vault corridor; Iron Securities Nuna braces behind "
               "her raised ETF hexagonal shield as the chains spark harmlessly off its glowing "
               "surface")
ORIGINAL_P4 = ("Iron Securities Nuna fires a burst from her rifle at the debt mountain, but the "
               "chains regenerate; Debt Titan surges forward pressing her shield back")
ACCEPTED_P4 = ("Iron Securities Nuna presses forward behind her ETF hexagonal shield, which "
               "projects a wide amber diversification barrier that splits the incoming chain "
               "stream into many thin strands; behind the barrier the strands knit back "
               "together as Debt Titan leans in and pushes the barrier back toward her")


def rules(text):
    return [v.rule for v in check_action(text, 1)]


def test_incident_refused_action_is_flagged():
    assert rules(REFUSED_P3) == ["ACTION_ATTACK_ON_CHARACTER"]
    assert rules(ORIGINAL_P4) == ["ACTION_FIREARM_DISCHARGE"]


def test_incident_accepted_actions_pass():
    assert rules(ACCEPTED_P3) == []
    assert rules(ACCEPTED_P4) == []


@pytest.mark.parametrize("text", [
    "Villain lashes a whip of lava toward her",
    "The titan slams into him while sparks fly",
    "Nuna fires her rifle at Debt Titan",
])
def test_attacks_on_characters_are_flagged(text):
    assert "ACTION_ATTACK_ON_CHARACTER" in rules(text)


@pytest.mark.parametrize("text", [
    "Debt Titan's fist smashes into her shield",
    "Hero swings her chainsaw into the villain's energy shield",
    "Debt Titan hurls a boulder at the city skyline",
    "Muscle Man punches the ground, cracking it",
    "She raises her rifle, ready, without firing",
    "Both combatants freeze in a tense standoff",
])
def test_object_targets_and_negation_pass(text):
    assert rules(text) == []


def test_graphic_injury_is_flagged_but_mild_fatigue_is_not():
    assert rules("blood pools beneath the fallen hero") == ["ACTION_GRAPHIC_INJURY"]
    assert rules("both wounded, neither defeated, breathing hard") == []


def test_script_check_skips_compositor_cards():
    script = {"panels": [
        {"idx": 1, "panel_type": "BATTLE", "action": REFUSED_P3},
        {"idx": 2, "panel_type": "TEXT_CARD", "action": "fires a burst from her rifle"},
    ]}
    found = check_script_actions(script)
    assert [(v.rule, v.panel_idx) for v in found] == [("ACTION_ATTACK_ON_CHARACTER", 1)]


def test_production_gate_reports_action_violation_with_retry_guidance():
    from engine.narrative.production_quality import (
        build_production_retry_feedback,
        validate_production_episode,
    )

    script = {"panels": [{"idx": 3, "panel_type": "BATTLE", "action": REFUSED_P3,
                          "characters": []}]}
    codes = {v.code for v in validate_production_episode(script)}
    assert "ACTION_ATTACK_ON_CHARACTER" in codes
    feedback = build_production_retry_feedback(validate_production_episode(script))
    assert "COMBAT IMAGE FIX" in feedback


def test_canary_fixture_is_action_safe():
    fixture = json.loads(Path("config/canary/combat_v1.json").read_text(encoding="utf-8"))
    assert check_script_actions(fixture["script"]) == []


@pytest.mark.parametrize("action", [
    "The analyst observes as the index hits support.",
    "The analyst marks the strike price.",
    "The analyst watches the price swing.",
    "A camera shot frames the analyst.",
    "The analyst adjusts the console and observes the holographic columns.",
])
def test_observation_allows_financial_and_camera_language(action):
    script = {"_episode_decision": {"scenario_type": "NO_BATTLE", "action_mode": "OBSERVATION"},
              "panels": [{"idx": 2, "action": action}]}
    assert check_observation_actions(script) == []


@pytest.mark.parametrize("action", [
    "The hero hits the console.",
    "The hero strikes a holographic column.",
    "The hero smashes into her shield.",
    "The hero punches the ground.",
    "The hero swings his fists.",
    "The index hits support; the hero smashes the console.",
    "The hero raises both fists and drives them into holographic columns.",
    "The hero fires her rifle at Debt Titan.",
])
def test_observation_rejects_physical_attacks(action):
    script = {"_episode_decision": {"scenario_type": "NO_BATTLE", "action_mode": "OBSERVATION"},
              "panels": [{"idx": 2, "action": action}]}
    found = check_observation_actions(script)
    assert [(v.rule, v.panel_idx) for v in found] == [("OBSERVATION_ACTION_CONFLICT", 2)]
