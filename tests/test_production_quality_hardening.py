import pytest

from engine.analysis.delta_engine import compute
from engine.analysis.story_context_builder import build_narrative_context_pack
from engine.narrative.claude_client import _validate_canon
from engine.narrative.production_quality import (
    ProductionQualityError,
    validate_production_episode,
)
from engine.narrative.schema import EpisodeScript


def test_daily_return_is_not_recomputed_as_percent_of_percent() -> None:
    delta = compute(
        {"spy_change": 0.6553, "nasdaq_change": 1.5735},
        {"spy_change": 0.0508, "nasdaq_change": 0.15187},
    )

    assert delta["SPY"]["curr"] == 0.6553
    assert delta["SPY"]["pct"] == 0.6553
    assert delta["SPY"]["semantic_type"] == "daily_return_pct"
    assert delta["NASDAQ"]["pct"] == 1.5735


def test_spread_uses_absolute_change_not_percent_return() -> None:
    delta = compute(
        {"crypto_basis_spread": 0.007979},
        {"crypto_basis_spread": 0.002645},
    )

    assert delta["CRYPTO_BASIS"]["pct"] is None
    assert delta["CRYPTO_BASIS"]["change"] == pytest.approx(0.005334)


def test_context_formats_daily_return_once_and_avoids_algo_causality() -> None:
    delta = compute({"spy_change": 0.6553}, {"spy_change": 0.0508})
    context = build_narrative_context_pack(
        delta=delta,
        battle_result={"outcome": "PEACEFUL_GROWTH"},
        event_type="INTEL",
        scenario_type="NO_BATTLE",
        ending_tone="OPTIMISTIC",
    )

    assert context["top_evidence"][0]["value"] == "SPY +0.6553%"
    assert "Algorithm Reaper pressure" not in context["market_cause"]


def test_production_gate_rejects_supplied_bad_episode_shape() -> None:
    script = {
        "next_hook": None,
        "unresolved_threads": [],
        "resolved_threads": [],
        "panels": [
            {
                "idx": 1,
                "panel_type": "BATTLE",
                "characters": [{"char_id": "CHAR_HERO_001"}],
                "action": "EDT stands and studies the screen.",
                "narration": "알고리즘이 방향을 바꿨다.",
                "market_ref": "SPY 0.6553 (+1190.35%)",
            },
            {
                "idx": 2,
                "panel_type": "CLIMAX",
                "characters": [{"char_id": "CHAR_HERO_001"}],
                "action": "EDT looks at the chart.",
            },
            {
                "idx": 3,
                "panel_type": "AFTERMATH",
                "characters": [{"char_id": "CHAR_HERO_001"}],
                "action": "EDT sits and watches.",
            },
            {
                "idx": 4,
                "panel_type": "CLIMAX",
                "characters": [{"char_id": "CHAR_HERO_001"}],
                "action": "EDT stands and reads.",
            },
        ],
    }
    plan = {
        "panel_beats": [
            {"panel_idx": 1, "required_character": ["CHAR_HERO_001"]},
            {"panel_idx": 3, "required_character": ["SENTINEL_YIELD"]},
        ]
    }

    violations = validate_production_episode(
        script,
        context_pack={"top_evidence": [{"id": "metric:SPY", "value": "SPY +0.6553%"}]},
        story_beat_plan=plan,
        scenario_type="NO_BATTLE",
        serial_required=True,
    )
    codes = {item.code for item in violations}

    assert {
        "NUMERIC_PERCENT_OUTLIER",
        "UNSUPPORTED_ALGORITHM_CAUSALITY",
        "REQUIRED_CAST_MISSING",
        "SCENARIO_PANEL_MISMATCH",
        "SERIAL_NEXT_HOOK_MISSING",
        "SERIAL_THREAD_LEDGER_EMPTY",
        "STATIC_ACTION_STREAK",
    } <= codes

    with pytest.raises(ProductionQualityError):
        validate_production_episode(
            script,
            context_pack={"top_evidence": []},
            story_beat_plan=plan,
            scenario_type="NO_BATTLE",
            serial_required=True,
            strict=True,
        )


def test_numeric_gate_does_not_reject_supported_vix_relative_move() -> None:
    violations = validate_production_episode(
        {
            "next_hook": "다음 변동성 신호를 검증한다",
            "unresolved_threads": ["변동성 신호"],
            "panels": [
                {
                    "idx": 1,
                    "panel_type": "TENSION",
                    "characters": [{"char_id": "CHAR_HERO_001"}],
                    "action": "The hero braces against a warning siren.",
                    "market_ref": "VIX 24.1 (+32.4%)",
                }
            ],
        },
        context_pack={"top_evidence": [{"id": "metric:VIX", "value": "VIX 24.1 (+32.4%)"}]},
        serial_required=True,
    )

    assert "NUMERIC_PERCENT_OUTLIER" not in {item.code for item in violations}


def test_registered_neutral_guest_is_accepted_as_npc() -> None:
    panel = {
        "camera": "MEDIUM",
        "setting": "bond hall",
        "action": "Sentinel warns the hero.",
        "key_text": "금리 경고다",
        "narration": "센티널이 수익률 신호를 확인했다.",
        "market_ref": "DGS10 4.5%",
    }
    panels = [
        {
            **panel,
            "idx": idx,
            "panel_type": "DISCLAIMER" if idx == 8 else "TENSION",
            "characters": (
                []
                if idx == 8
                else [{"char_id": "SENTINEL_YIELD", "role": "npc", "position": "RIGHT"}]
            ),
        }
        for idx in range(1, 9)
    ]
    script = EpisodeScript.model_validate(
        {
            "episode_id": "ICG-2026-08-28-001",
            "date": "2026-08-28",
            "event_type": "INTEL",
            "title": "금리 경고",
            "logline": "센티널이 금리 신호를 검증한다.",
            "next_hook": "다음 금리 신호를 확인한다",
            "unresolved_threads": ["금리 신호"],
            "panels": panels,
            "caption_x_cover": "금리 경고",
            "caption_x_parts": ["파트1", "파트2"],
            "caption_x_final": "투자 참고 정보이며 투자 권유가 아닙니다",
            "caption_telegram": "금리 경고",
            "hashtags": ["#금리"],
            "arc_tension_delta": 1,
        }
    )

    _validate_canon(script, scenario_type="NO_BATTLE")
