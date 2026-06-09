from pathlib import Path

import yaml

from engine.narrative.prompt_tpl import build_active_character_cards, render_user_prompt


def _canon():
    return yaml.safe_load(Path("config/characters.yaml").read_text(encoding="utf-8"))


def test_build_active_character_cards_uses_top_level_canon_prompts():
    cards = build_active_character_cards(
        canon=_canon(),
        hero_ids=["CHAR_HERO_003"],
        villain_id="CHAR_VILLAIN_002",
    )

    by_id = {card["char_id"]: card for card in cards}
    assert "CHAR_HERO_003" in by_id
    assert "CHAR_VILLAIN_002" in by_id
    assert "유가" in by_id["CHAR_HERO_003"]["narrative_identity"]
    assert by_id["CHAR_VILLAIN_002"]["forbidden"]


def test_render_user_prompt_appends_explicit_active_character_cards(monkeypatch):
    monkeypatch.delenv("NOTION_API_KEY", raising=False)
    rendered = render_user_prompt(
        date="2026-06-03",
        episode_id="ICG-2026-06-03-001",
        event_type="BATTLE",
        delta={"WTI": {"curr": 96, "pct": 8.2}},
        battle_result={"outcome": "DRAW", "balance": 0},
        hero_id="CHAR_HERO_003",
        villain_id="CHAR_VILLAIN_002",
        arc_context={"tension": 40},
        active_character_cards=[
            {
                "char_id": "CHAR_HERO_003",
                "name_ko": "레버리지 머슬맨",
                "narrative_identity": "유가 과열 테스트 카드",
                "voice": {"tone": "bold", "catchphrases": ["한 방"]},
                "entrance_cue": ["oil flame"],
                "market_metaphor": ["oil candle"],
                "signature_action": ["flame punch"],
                "forbidden": ["ice power"],
            }
        ],
    )

    assert "Active Character Canon Cards" in rendered
    assert "유가 과열 테스트 카드" in rendered
    assert "ice power" in rendered


def test_build_active_character_cards_accepts_multiple_villains():
    cards = build_active_character_cards(
        canon=_canon(),
        hero_ids=["CHAR_HERO_001"],
        villain_id="CHAR_VILLAIN_004",
        villain_ids=["CHAR_VILLAIN_004", "CHAR_VILLAIN_001"],
    )

    assert [card["char_id"] for card in cards[:3]] == [
        "CHAR_HERO_001",
        "CHAR_VILLAIN_004",
        "CHAR_VILLAIN_001",
    ]
