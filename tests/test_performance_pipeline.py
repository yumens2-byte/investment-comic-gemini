"""Unit tests for structured image performance compilation and validation."""

import pytest
from pydantic import ValidationError

from engine.image.performance_compiler import (
    compile_episode_performance,
    compile_panel_performance,
)
from engine.image.performance_schema import (
    BodyMechanics,
    PanelPerformanceSpec,
    StagingSpec,
    VisualContinuityState,
)
from engine.image.performance_validator import (
    validate_episode_performance,
    validate_panel_performance,
)
from engine.image.prompt_builder import build_panel_prompt


def _panel(action: str = "Hero punches the villain in the chest") -> dict:
    return {
        "idx": 4,
        "panel_type": "BATTLE",
        "characters": [
            {"char_id": "CHAR_HERO_001", "role": "hero", "position": "LEFT"},
            {"char_id": "CHAR_VILLAIN_001", "role": "villain", "position": "RIGHT"},
        ],
        "camera": "MEDIUM",
        "setting": "Wall Street canyon",
        "action": action,
        "key_text": "충돌",
        "narration": "두 힘이 정면으로 부딪힌다.",
        "market_ref": "VIX pressure",
    }


def test_compile_interaction_preserves_subject_target_and_contact() -> None:
    spec = compile_panel_performance(_panel())

    assert spec.subject_id == "CHAR_HERO_001"
    assert spec.target_id == "CHAR_VILLAIN_001"
    assert spec.interaction_required is True
    assert spec.action_phase == "IMPACT"
    assert spec.contact_point
    assert spec.required_character_ids == ["CHAR_HERO_001", "CHAR_VILLAIN_001"]


def test_generic_action_is_observable_warning() -> None:
    panel = _panel("Hero does something dramatic")
    spec = compile_panel_performance(panel)
    result = validate_panel_performance(panel, spec)

    assert result.status == "PASS"
    assert "PERF_W_ACTION_GENERIC" in [issue.code for issue in result.issues]


def test_schema_rejects_interaction_without_target() -> None:
    with pytest.raises(ValidationError):
        PanelPerformanceSpec(
            panel_idx=1,
            narrative_purpose="impact",
            subject_id="hero",
            action_verb="punches",
            intent="stop threat",
            action_phase="IMPACT",
            interaction_required=True,
            body_mechanics=BodyMechanics(),
            staging=StagingSpec(shot_size="MS", focal_point="fist"),
            entering_state=VisualContinuityState(),
            exiting_state=VisualContinuityState(),
        )


def test_validator_rejects_close_up_full_body_kick() -> None:
    panel = _panel("Hero kicks the villain")
    panel["camera"] = "CLOSE_UP"
    spec = compile_panel_performance(panel)
    result = validate_panel_performance(panel, spec)

    assert result.status == "FAIL"
    assert "PERF_E_CAMERA_CROP" in [issue.code for issue in result.issues]


def test_episode_compiler_carries_visual_state_forward() -> None:
    first = _panel("Hero punches the villain")
    first["idx"] = 1
    second = _panel("Hero watches the villain")
    second["idx"] = 2
    second["panel_type"] = "TENSION"
    second["setting"] = ""

    specs = compile_episode_performance({"panels": [first, second]})

    assert specs[1].entering_state.location == "Wall Street canyon"
    assert specs[1].entering_state.character_positions["CHAR_HERO_001"] == "LEFT"


def test_episode_validator_rejects_unexplained_prop_repair() -> None:
    first = _panel("Hero punches the villain")
    first["idx"] = 1
    second = _panel("Hero punches the villain")
    second["idx"] = 2
    specs = compile_episode_performance({"panels": [first, second]})
    specs[0].exiting_state = VisualContinuityState(prop_states={"shield": "broken"})
    specs[1].entering_state = VisualContinuityState(prop_states={"shield": "intact"})

    result = validate_episode_performance({"panels": [first, second]}, specs)

    assert result.status == "FAIL"
    assert "PERF_E_PROP_DISCONTINUITY" in {issue.code for issue in result.issues}


def test_performance_prompt_contains_hard_action_contract(monkeypatch) -> None:
    panel = _panel()
    spec = compile_panel_performance(panel)
    monkeypatch.setattr("engine.image.prompt_builder._get_style_block", lambda: "STYLE")
    monkeypatch.setattr("engine.image.prompt_builder._get_negative_block", lambda: "NEGATIVE")
    monkeypatch.setattr("engine.image.prompt_builder._get_char_designs", lambda _ids: "")
    monkeypatch.setattr("engine.image.prompt_builder._build_identity_lock", lambda *_args: "")
    monkeypatch.setattr("engine.image.prompt_builder._get_panel_visual_spec", lambda _type: "")

    prompt = build_panel_prompt(panel, performance_spec=spec)

    assert "PERFORMANCE CONTRACT — HARD REQUIREMENT" in prompt
    assert "CHAR_HERO_001" in prompt
    assert "CHAR_VILLAIN_001" in prompt
    assert "VISIBLE CONTACT" in prompt
    assert "BODY MECHANICS" in prompt
