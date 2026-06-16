"""End-to-end contract tests for the Narrative Context/Story Planner pilot."""

from __future__ import annotations

import pytest

from engine.analysis.story_context_builder import build_narrative_context_pack
from engine.narrative.prompt_tpl import render_user_prompt
from engine.narrative.story_planner import build_story_beat_plan
from engine.narrative.story_quality import StoryGroundingError, validate_story_grounding


def _pilot_context_pack() -> dict:
    return build_narrative_context_pack(
        delta={
            "VIX": {"curr": 18.4, "pct": 8.5},
            "SPY": {"curr": 512.0, "pct": -1.1},
            "BTC": {"curr": 72500, "pct": 3.2},
        },
        battle_result={"outcome": "HERO_TACTICAL_VICTORY", "balance": 12},
        event_type="NORMAL",
        scenario_type="ONE_VS_ONE",
        ending_tone="OPTIMISTIC",
        arc_context={"tension": 42},
        news_items=[
            {
                "id": "news:fed-watch",
                "safe_summary_ko": "연준 발언 대기 속 변동성 지표가 상승했다.",
                "source": "pilot-fixture",
                "relevance_score": 0.9,
                "story_use": "policy uncertainty",
            }
        ],
        economic_events=[{"name": "CPI", "release_time": "2026-06-02 21:30", "importance": 5}],
        sector_heatmap={
            "sectors": [
                {"name": "Technology", "change_pct": -2.4},
                {"name": "Energy", "change_pct": 1.7},
            ]
        },
    )


def test_pilot_context_plan_prompt_contract_survives_legacy_template(monkeypatch) -> None:
    """A legacy Notion template still receives context and plan via fallback blocks."""
    monkeypatch.setattr(
        "engine.common.notion_loader.load_narrative_user_template",
        lambda: "Episode {{ episode_id }} / {{ scenario_type }} / {{ ending_tone }}",
    )

    context_pack = _pilot_context_pack()
    story_plan = build_story_beat_plan(
        narrative_context_pack=context_pack,
        hero_id="CHAR_HERO_001",
        villain_id="CHAR_VILLAIN_005",
        battle_result={"outcome": "HERO_TACTICAL_VICTORY", "balance": 12},
        scenario_type="ONE_VS_ONE",
    ).model_dump()

    prompt = render_user_prompt(
        date="2026-06-01",
        episode_id="ICG-2026-06-01-001",
        event_type="NORMAL",
        delta={"VIX": {"curr": 18.4, "pct": 8.5}},
        battle_result={"outcome": "HERO_TACTICAL_VICTORY", "balance": 12},
        hero_id="CHAR_HERO_001",
        villain_id="CHAR_VILLAIN_005",
        arc_context={"tension": 42},
        scenario_type="ONE_VS_ONE",
        ending_tone="OPTIMISTIC",
        narrative_context_pack=context_pack,
        story_beat_plan=story_plan,
    )

    assert context_pack["version"] == "pilot-1"
    assert len(context_pack["top_evidence"]) == 3
    assert any(item["kind"] == "news" for item in context_pack["top_evidence"])
    assert len(story_plan["panel_beats"]) == 8
    assert story_plan["panel_beats"][-1]["dramatic_function"] == "DISCLAIMER"
    assert "Narrative Context Pack" in prompt
    assert "Story Beat Plan" in prompt
    assert "metric:VIX" in prompt
    assert "news:fed-watch" in prompt


def test_grounding_guardrails_are_present_when_context_pilot_is_disabled(monkeypatch) -> None:
    """Unsupported algo-volume claims must be forbidden even without pilot context."""
    monkeypatch.setattr(
        "engine.common.notion_loader.load_narrative_user_template",
        lambda: "Episode {{ episode_id }} / {{ scenario_type }} / {{ ending_tone }}",
    )

    prompt = render_user_prompt(
        date="2026-06-16",
        episode_id="ICG-2026-06-16-001",
        event_type="NORMAL",
        delta={"SPY": {"curr": 1.76, "pct": 1.76}},
        battle_result={"outcome": "HERO_TACTICAL_VICTORY", "balance": 12},
        hero_id="CHAR_HERO_001",
        villain_id="CHAR_VILLAIN_005",
        arc_context={"tension": 42},
        scenario_type="ONE_VS_ONE",
        ending_tone="OPTIMISTIC",
        narrative_context_pack=None,
        story_beat_plan=None,
    )

    assert "Always-on Market Grounding Guardrails" in prompt
    assert "Do not claim algo-trading volume" in prompt
    assert "Algorithm Reaper may appear as a fictional character" in prompt


def test_pilot_grounding_gate_blocks_unsupported_algo_claims_until_evidence_exists() -> None:
    context_pack = _pilot_context_pack()
    script = {
        "panels": [
            {
                "idx": 2,
                "narration": "시장 대시보드가 흔들렸다.",
                "market_ref": "알고 트레이딩 비중 급증 감지",
            }
        ]
    }

    with pytest.raises(StoryGroundingError):
        validate_story_grounding(script, context_pack, strict=True)

    supported_pack = {
        **context_pack,
        "top_evidence": [
            *context_pack["top_evidence"],
            {
                "id": "news:algo-volume",
                "kind": "news",
                "headline_summary": "알고 트레이딩 거래 비중 변화가 공식 데이터로 확인됐다.",
                "story_role": "algo trading volume evidence",
            },
        ],
    }

    assert validate_story_grounding(script, supported_pack, strict=True) == []
