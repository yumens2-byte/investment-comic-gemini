import pytest

from scripts.run_market import (
    _ensure_narrative_quality_inputs,
    _validate_narrative_quality_inputs,
)
    _feature_flag_snapshot,
    _record_context_error,
    _validate_narrative_quality_inputs,
)
from scripts.run_market import _ensure_narrative_quality_inputs, _validate_narrative_quality_inputs


def _ctx() -> dict:
    return {
        "narrative_context_pack": {"top_evidence": [{"id": "metric:VIX", "value": "VIX 15.7"}]},
        "story_beat_plan": {"panel_beats": [{"panel_idx": idx} for idx in range(1, 9)]},
    }


def test_quality_gate_passes_when_pilot_flags_have_context(monkeypatch) -> None:
    monkeypatch.setenv("NARRATIVE_CONTEXT_ENABLED", "true")
    monkeypatch.setenv("STORY_PLANNER_ENABLED", "true")

    summary = _validate_narrative_quality_inputs(_ctx())

    assert summary == {
        "narrative_enabled": True,
        "planner_enabled": True,
        "evidence_count": 1,
        "beat_count": 8,
    }


def test_quality_gate_fails_when_enabled_context_missing(monkeypatch) -> None:
    monkeypatch.setenv("NARRATIVE_CONTEXT_ENABLED", "true")
    monkeypatch.setenv("STORY_PLANNER_ENABLED", "false")

    with pytest.raises(RuntimeError, match="narrative_context_pack"):
        _validate_narrative_quality_inputs({})


def test_quality_gate_fails_when_story_plan_is_incomplete(monkeypatch) -> None:
    monkeypatch.setenv("NARRATIVE_CONTEXT_ENABLED", "true")
    monkeypatch.setenv("STORY_PLANNER_ENABLED", "true")
    ctx = _ctx()
    ctx["story_beat_plan"] = {"panel_beats": [{"panel_idx": 1}]}

    with pytest.raises(RuntimeError, match="8개"):
        _validate_narrative_quality_inputs(ctx)


def test_quality_gate_error_includes_flag_snapshot_and_context_errors(monkeypatch) -> None:
    monkeypatch.setenv("NARRATIVE_CONTEXT_ENABLED", "true")
    monkeypatch.setenv("STORY_PLANNER_ENABLED", "false")
    ctx: dict = {"feature_flags_snapshot": _feature_flag_snapshot()}
    _record_context_error(ctx, "narrative_context_pack", RuntimeError("boom"), strict=True)

    with pytest.raises(RuntimeError) as excinfo:
        _validate_narrative_quality_inputs(ctx)

    message = str(excinfo.value)
    assert "flags=" in message
    assert "context_errors=" in message
    assert "boom" in message


def test_feature_flag_snapshot_captures_continuity_flags(monkeypatch) -> None:
    monkeypatch.setenv("NARRATIVE_CONTEXT_ENABLED", "true")
    monkeypatch.setenv("STORY_PLANNER_ENABLED", "true")
    monkeypatch.setenv("CONTINUITY_STRICT_ENABLED", "true")
    monkeypatch.setenv("ARC_STATE_V3_ENABLED", "false")
    monkeypatch.setenv("EPISODE_TYPE_V3_ENABLED", "true")

    snapshot = _feature_flag_snapshot()

    assert snapshot == {
        "NARRATIVE_CONTEXT_ENABLED": True,
        "STORY_PLANNER_ENABLED": True,
        "CONTINUITY_STRICT_ENABLED": True,
        "ARC_STATE_V3_ENABLED": False,
        "EPISODE_TYPE_V3_ENABLED": True,
    }
def test_quality_inputs_rebuild_from_core_ctx_when_enabled(monkeypatch) -> None:
    monkeypatch.setenv("NARRATIVE_CONTEXT_ENABLED", "true")
    monkeypatch.setenv("STORY_PLANNER_ENABLED", "true")

    rebuilt = _ensure_narrative_quality_inputs(
        {
            "event_type": "NORMAL",
            "delta": {
                "VIX": {"curr": 17.68, "pct": 2.1},
                "SPY": {"curr": 1.76, "pct": 1.76},
            },
            "battle_result": {"outcome": "HERO_TACTICAL_VICTORY", "balance": 12},
            "hero_id": "CHAR_HERO_001",
            "villain_id": "CHAR_VILLAIN_001",
            "villain_ids": ["CHAR_VILLAIN_001"],
            "scenario_type": "ONE_VS_ONE",
            "ending_tone": "TENSE",
            "arc_context": {"tension": 40},
            "heroes": ["CHAR_HERO_001"],
        }
    )

    summary = _validate_narrative_quality_inputs(rebuilt)
    assert summary["evidence_count"] > 0
    assert summary["beat_count"] == 8


def test_quality_inputs_do_not_require_optional_story_enrichment(monkeypatch) -> None:
    monkeypatch.setenv("NARRATIVE_CONTEXT_ENABLED", "true")
    monkeypatch.setenv("STORY_PLANNER_ENABLED", "false")

    rebuilt = _ensure_narrative_quality_inputs(
        {
            "event_type": "NORMAL",
            "delta": {"SPY": {"curr": 1.76, "pct": 1.76}},
            "battle_result": {"outcome": "DRAW", "balance": 0},
            "hero_id": "CHAR_HERO_001",
            "villain_id": "CHAR_VILLAIN_001",
        }
    )

    assert rebuilt["narrative_context_pack"]["top_evidence"][0]["id"] == "metric:SPY"
