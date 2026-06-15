"""StoryBeatPlan pilot tests."""

import pytest
from pydantic import ValidationError

from engine.narrative.schema import StoryBeatPlan
from engine.narrative.story_planner import build_story_beat_plan


def _context_pack() -> dict:
    return {
        "market_cause": "Primary story driver: Debt Titan pressure from DGS10 4.9 (+8.9%).",
        "top_evidence": [
            {"id": "metric:DGS10", "scene_symbol": "bond auction hall"},
            {"id": "metric:VIX", "scene_symbol": "red volatility siren"},
        ],
        "scene_symbols": ["bond auction hall", "red volatility siren"],
        "foreshadow": ["CPI (2026-06-03)"],
        "prohibited_claims": ["Do not invent news."],
    }


def test_build_story_beat_plan_returns_eight_ordered_beats() -> None:
    plan = build_story_beat_plan(
        narrative_context_pack=_context_pack(),
        hero_id="CHAR_HERO_003",
        villain_id="CHAR_VILLAIN_002",
        battle_result={"outcome": "HERO_DEFEAT"},
        scenario_type="ONE_VS_ONE",
    )

    assert isinstance(plan, StoryBeatPlan)
    assert [beat.panel_idx for beat in plan.panel_beats] == list(range(1, 9))
    assert plan.panel_beats[-1].dramatic_function == "DISCLAIMER"
    assert plan.next_hook_seed == "CPI (2026-06-03)"
    assert "HERO_DEFEAT" in plan.episode_thesis


def test_story_beat_plan_schema_rejects_wrong_order() -> None:
    plan = build_story_beat_plan(
        narrative_context_pack=_context_pack(),
        hero_id="CHAR_HERO_003",
        villain_id="CHAR_VILLAIN_002",
        battle_result={"outcome": "DRAW"},
        scenario_type="ONE_VS_ONE",
    ).model_dump()
    plan["panel_beats"][0]["panel_idx"] = 2

    with pytest.raises(ValidationError):
        StoryBeatPlan.model_validate(plan)


def test_no_battle_plan_does_not_require_villain_characters() -> None:
    plan = build_story_beat_plan(
        narrative_context_pack=_context_pack(),
        hero_id="CHAR_HERO_001",
        villain_id="CHAR_VILLAIN_002",
        battle_result={"outcome": "PEACEFUL_GROWTH"},
        scenario_type="NO_BATTLE",
    )

    assert all("CHAR_VILLAIN_002" not in beat.required_character for beat in plan.panel_beats)


def test_story_beat_plan_model_dump_json_serializable() -> None:
    import json

    plan = build_story_beat_plan(
        narrative_context_pack=_context_pack(),
        hero_id="CHAR_HERO_003",
        villain_id="CHAR_VILLAIN_002",
        battle_result={"outcome": "DRAW"},
        scenario_type="ONE_VS_ONE",
    ).model_dump()

    assert (
        json.loads(json.dumps(plan, ensure_ascii=False))["panel_beats"][-1]["dramatic_function"]
        == "DISCLAIMER"
    )


def test_story_beat_plan_pays_off_previous_hook_in_opening() -> None:
    context = _context_pack()
    context["previous_episode"] = {
        "next_hook": "문은 아직 닫히지 않았다.",
        "final_panel_summary": "전날의 균열",
    }

    plan = build_story_beat_plan(
        narrative_context_pack=context,
        hero_id="CHAR_HERO_003",
        villain_id="CHAR_VILLAIN_002",
        battle_result={"outcome": "DRAW"},
        scenario_type="ONE_VS_ONE",
    )

    first = plan.panel_beats[0]
    assert first.must_reference_previous is True
    assert "문은 아직 닫히지 않았다" in (first.continuity_payoff or "")
    assert "previous hook" in first.dialogue_intent


def test_story_beat_plan_limits_multi_villain_panels_to_p4_p5() -> None:
    plan = build_story_beat_plan(
        narrative_context_pack=_context_pack(),
        hero_id="CHAR_HERO_001",
        villain_id="CHAR_VILLAIN_004",
        villain_ids=["CHAR_VILLAIN_004", "CHAR_VILLAIN_001"],
        battle_result={"outcome": "DRAW"},
        scenario_type="ALLIANCE",
    )

    support_panels = [
        beat.panel_idx for beat in plan.panel_beats if "CHAR_VILLAIN_001" in beat.required_character
    ]
    assert support_panels == [4, 5]
    assert all(
        "outside the supplied villain_ids" in " ".join(beat.forbidden) for beat in plan.panel_beats
    )


def test_alliance_story_beat_plan_requires_support_hero_in_coordination_panels() -> None:
    plan = build_story_beat_plan(
        narrative_context_pack=_context_pack(),
        hero_id="CHAR_HERO_004",
        hero_ids=["CHAR_HERO_004", "CHAR_HERO_001"],
        villain_id="CHAR_VILLAIN_004",
        battle_result={"outcome": "PYRRHIC_VICTORY"},
        scenario_type="ALLIANCE",
    )

    support_panels = [
        beat.panel_idx for beat in plan.panel_beats if "CHAR_HERO_001" in beat.required_character
    ]
    assert support_panels == [4, 5]
    assert "support_heroes=['CHAR_HERO_001']" in plan.hero_inner_conflict


def test_story_beat_plan_marks_panel_2_for_arc_pivot() -> None:
    context = _context_pack()
    context["previous_episode"] = {"next_hook": "검은 문은 아직 닫히지 않았다"}
    context["arc_pivot"] = {
        "pivot_required": True,
        "pivot_reasons": ["active_villain_changed"],
        "instruction": "Explain why the villain changed.",
    }

    plan = build_story_beat_plan(
        narrative_context_pack=context,
        hero_id="hero_gold_bond_muscle",
        villain_id="villain_debt_titan",
        battle_result={"outcome": "DRAW"},
        scenario_type="ONE_VS_ONE",
    )

    assert plan.panel_beats[1].must_reference_previous is True
    assert "villain changed" in plan.panel_beats[1].dialogue_intent
