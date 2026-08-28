import pytest

from scripts.run_market import (
    _ensure_narrative_quality_inputs,
    _feature_flag_snapshot,
    _production_quality_strict_enabled,
    _record_context_error,
    _validate_narrative_quality_inputs,
)


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

    # 관측성 확장(2026-06-30)으로 전체 11개를 기록하지만, continuity 5개 값은 보존된다.
    assert snapshot["NARRATIVE_CONTEXT_ENABLED"] is True
    assert snapshot["STORY_PLANNER_ENABLED"] is True
    assert snapshot["CONTINUITY_STRICT_ENABLED"] is True
    assert snapshot["ARC_STATE_V3_ENABLED"] is False
    assert snapshot["EPISODE_TYPE_V3_ENABLED"] is True


def test_continuity_strict_also_makes_production_quality_fail_closed(monkeypatch) -> None:
    monkeypatch.setenv("SERIAL_NARRATIVE_P0_ENABLED", "false")

    assert _production_quality_strict_enabled(continuity_strict=True) is True
    assert _production_quality_strict_enabled(continuity_strict=False) is False


def test_feature_flag_snapshot_captures_all_12_flags(monkeypatch) -> None:
    """관측성 확장: production strict flag를 포함한 전체 플래그를 기록한다."""
    all_flags = [
        "NARRATIVE_CONTEXT_ENABLED",
        "STORY_PLANNER_ENABLED",
        "CONTINUITY_STRICT_ENABLED",
        "ARC_STATE_V3_ENABLED",
        "EPISODE_TYPE_V3_ENABLED",
        "SCENARIO_V2_ENABLED",
        "NARRATIVE_DEPTH_ENABLED",
        "PAIR_TENSION_ENABLED",
        "CROWD_MODIFIER_ENABLED",
        "VILLAIN_SIGNATURE_BONUS_ENABLED",
        "EMERGENCE_DEFICIT_ENABLED",
        "SERIAL_NARRATIVE_P0_ENABLED",
    ]
    for name in all_flags:
        monkeypatch.setenv(name, "true")
    monkeypatch.setenv("PAIR_TENSION_ENABLED", "false")  # 혼합값 검증

    snapshot = _feature_flag_snapshot()

    # 12개 키 전부 기록
    assert set(snapshot.keys()) == set(all_flags)
    # scenario/battle 6개 값 정확성
    assert snapshot["SCENARIO_V2_ENABLED"] is True
    assert snapshot["NARRATIVE_DEPTH_ENABLED"] is True
    assert snapshot["PAIR_TENSION_ENABLED"] is False
    assert snapshot["CROWD_MODIFIER_ENABLED"] is True
    assert snapshot["VILLAIN_SIGNATURE_BONUS_ENABLED"] is True
    assert snapshot["EMERGENCE_DEFICIT_ENABLED"] is True
    assert snapshot["SERIAL_NARRATIVE_P0_ENABLED"] is True


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
