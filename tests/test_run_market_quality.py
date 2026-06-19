import pytest

from engine.narrative.story_quality import StoryContinuityError
from scripts.run_market import (
    _build_continuity_repair_instructions,
    _ensure_narrative_quality_inputs,
    _feature_flag_snapshot,
    _record_context_error,
    _validate_narrative_quality_inputs,
    step_narrative,
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


def test_continuity_repair_instructions_preserve_market_contract() -> None:
    prompt = _build_continuity_repair_instructions(
        {},
        {
            "total_score": 35.0,
            "status": "fail",
            "previous_source_episode_id": "ICG-2026-06-15-001",
            "missing_requirements": ["opening_hook_payoff"],
            "warnings": ["Continuity score 35.0 below threshold 70"],
        },
    )

    assert "35.0/100" in prompt
    assert "opening_hook_payoff" in prompt
    assert "Preserve supplied market facts" in prompt
    assert "Return the full EpisodeScript JSON only" in prompt


def test_step_narrative_retries_once_on_strict_continuity_failure(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("NARRATIVE_CONTEXT_ENABLED", "true")
    monkeypatch.setenv("STORY_PLANNER_ENABLED", "true")
    monkeypatch.setenv("CONTINUITY_STRICT_ENABLED", "true")

    calls: list[dict] = []

    class FakeScript:
        panels = [object()] * 8

        def __init__(self, label: str) -> None:
            self.label = label

        def model_dump(self) -> dict:
            return {
                "episode_id": "ICG-2026-06-16-001",
                "date": "2026-06-16",
                "event_type": "NORMAL",
                "title": f"title-{self.label}",
                "panels": [{"idx": idx, "narration": f"panel {idx}"} for idx in range(1, 9)],
            }

    def fake_generate_episode(**kwargs):
        calls.append(kwargs)
        return FakeScript("repair" if kwargs.get("continuity_repair_instructions") else "draft")

    payloads = [
        {
            "total_score": 35.0,
            "status": "fail",
            "missing_requirements": ["opening_hook_payoff"],
            "warnings": ["Continuity score 35.0 below threshold 70"],
            "previous_source_episode_id": "ICG-2026-06-15-001",
        },
        {
            "total_score": 85.0,
            "status": "pass",
            "missing_requirements": [],
            "warnings": [],
            "previous_source_episode_id": "ICG-2026-06-15-001",
        },
    ]

    def fake_build_payload(*args, **kwargs):
        return dict(payloads.pop(0))

    validate_calls = []

    def fake_validate_continuity(*args, **kwargs):
        validate_calls.append(kwargs)
        if len(validate_calls) == 1:
            raise StoryContinuityError("Continuity score 35.0 below threshold 70")
        return []

    class FakeLogger:
        def step_start(self, *_args):
            return 0.0

        def step_done(self, *_args):
            return None

        def step_fail(self, *_args):
            return None

        def info(self, *_args):
            return None

        def warning(self, *_args):
            return None

    import engine.narrative.claude_client as claude_client
    import engine.narrative.story_quality as story_quality

    monkeypatch.setattr(claude_client, "generate_episode", fake_generate_episode)
    monkeypatch.setattr(story_quality, "validate_story_grounding", lambda *args, **kwargs: [])
    monkeypatch.setattr(story_quality, "build_continuity_quality_payload", fake_build_payload)
    monkeypatch.setattr(story_quality, "validate_story_continuity", fake_validate_continuity)

    script = step_narrative(
        "2026-06-16",
        "ICG-2026-06-16-001",
        _ctx()
        | {
            "event_type": "NORMAL",
            "delta": {"SPY": {"curr": 1.0}},
            "battle_result": {"outcome": "DRAW", "balance": 0},
            "hero_id": "CHAR_HERO_001",
            "villain_id": "CHAR_VILLAIN_001",
            "arc_context": {},
        },
        FakeLogger(),
    )

    assert len(calls) == 2
    assert "continuity_repair_instructions" not in calls[0]
    assert "Continuity score 35.0" in calls[1]["continuity_repair_instructions"]
    assert script["title"] == "title-repair"
    assert script["_continuity_quality"]["repair_attempted"] is True
