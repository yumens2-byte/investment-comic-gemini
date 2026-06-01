"""Narrative Context Pack pilot tests."""

from engine.analysis.story_context_builder import build_narrative_context_pack


def _delta() -> dict:
    return {
        "DGS10": {"prev": 4.5, "curr": 4.9, "pct": 8.8889},
        "VIX": {"prev": 18.0, "curr": 21.6, "pct": 20.0},
        "SPY": {"prev": -0.2, "curr": -1.1, "pct": -1.1},
    }


def test_context_pack_uses_top_market_evidence() -> None:
    pack = build_narrative_context_pack(
        delta=_delta(),
        battle_result={"outcome": "HERO_DEFEAT", "balance": -12},
        event_type="BATTLE",
        scenario_type="ONE_VS_ONE",
        ending_tone="OMINOUS",
    )

    assert pack["version"] == "pilot-1"
    assert pack["top_evidence"]
    assert pack["top_evidence"][0]["metric"] == "VIX"
    assert "Primary story driver" in pack["market_cause"]
    assert "Do not invent news" in pack["prohibited_claims"][0]


def test_context_pack_can_include_news_events_and_sector_symbols() -> None:
    pack = build_narrative_context_pack(
        delta=_delta(),
        battle_result={"outcome": "DRAW", "balance": 0},
        event_type="NORMAL",
        scenario_type="NO_BATTLE",
        ending_tone="OPTIMISTIC",
        news_items=[
            {
                "id": "news:fed",
                "source": "official/news",
                "source_url": "https://example.com/fed",
                "safe_summary_ko": "연준 발언으로 금리 경계감이 커졌다.",
                "relevance_score": 0.95,
                "story_use": "villain_trigger",
            }
        ],
        economic_events=[{"name": "CPI", "release_time": "2026-06-03", "importance": 5}],
        sector_heatmap={"sectors": [{"name": "AI", "change_pct": -2.5}]},
    )

    assert any(ev.get("id") == "news:fed" for ev in pack["top_evidence"])
    assert pack["foreshadow"] == ["CPI (2026-06-03)"]
    assert any("AI red sector board" in symbol for symbol in pack["scene_symbols"])


def test_context_pack_json_serializable() -> None:
    import json

    pack = build_narrative_context_pack(
        delta=_delta(),
        battle_result={"outcome": "DRAW", "balance": 0},
        event_type="NORMAL",
        scenario_type="ONE_VS_ONE",
        ending_tone="TENSE",
    )

    assert json.loads(json.dumps(pack, ensure_ascii=False))["version"] == "pilot-1"
