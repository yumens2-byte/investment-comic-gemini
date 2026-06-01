import pytest

from scripts.run_market import _validate_narrative_quality_inputs


def _ctx() -> dict:
    return {
        "narrative_context_pack": {
            "top_evidence": [{"id": "metric:VIX", "value": "VIX 15.7"}]
        },
        "story_beat_plan": {
            "panel_beats": [{"panel_idx": idx} for idx in range(1, 9)]
        },
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
