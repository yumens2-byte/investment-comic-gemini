from __future__ import annotations

from pathlib import Path

import yaml

from engine.narrative.character_selector import select_for_no_battle
from engine.narrative.continuity import _merge_recent_window, build_continuity_bundle
from engine.narrative.serial_contracts import (
    build_villain_reader_card,
    merge_thread_ledger,
    rotate_hero,
    summarize_cast_history,
    thread_id,
    validate_canon_mirrors,
)
from engine.narrative.story_planner import build_story_beat_plan


def _canon() -> dict:
    return yaml.safe_load(Path("config/characters.yaml").read_text())


def test_rotation_prevents_third_default_nuna_lead() -> None:
    history = summarize_cast_history(
        [{"hero_ids": ["CHAR_HERO_002"]}, {"hero_ids": ["CHAR_HERO_002"]}]
    )
    hero, villain, trace = select_for_no_battle(
        {"VIX": {"curr": 17}, "SPY": {"pct": 0.2}},
        cast_history=history,
        return_trace=True,
    )
    assert villain is None
    assert hero != "CHAR_HERO_002"
    assert trace["candidates"]["CHAR_HERO_002"]["consecutive_penalty"] == 30


def test_market_fit_override_preserves_overwhelming_signal() -> None:
    hero, trace = rotate_hero(
        {"CHAR_HERO_001": 100, "CHAR_HERO_002": 0},
        summarize_cast_history([{"hero_ids": ["CHAR_HERO_001"]}] * 2),
    )
    assert hero == "CHAR_HERO_001"
    assert trace["reason"] == "MARKET_FIT_OVERRIDE"


def test_thread_ids_and_legacy_upgrade_are_stable() -> None:
    assert thread_id("MYSTERY", "  Lost   route ") == thread_id("mystery", "lost route")
    ledger = merge_thread_ledger(
        [{"source_episode_id": "E1", "unresolved_threads": ["Lost route"]}]
    )
    assert ledger[0]["thread_id"].startswith("THREAD_")
    assert ledger[0]["status"] == "OPEN"


def test_continuity_window_exposes_cast_and_thread_ledgers() -> None:
    bundle = build_continuity_bundle(
        "ICG-2026-08-27-001",
        "2026-08-27",
        {"heroes": ["CHAR_HERO_004"], "battle_result": {"outcome": "DRAW"}},
        {"next_hook": "Follow the signal", "panels": []},
    )
    window = _merge_recent_window([bundle])
    assert window["cast_history"]["recent_lead_ids"] == ["CHAR_HERO_004"]
    assert window["thread_ledger"][0]["thread_id"].startswith("THREAD_")


def test_natural_disaster_villain_card_does_not_invent_intent() -> None:
    card = build_villain_reader_card(_canon(), "CHAR_VILLAIN_002")
    assert card is not None
    assert card["natural_disaster"] is True
    assert "임계" in card["mechanism"]
    assert card["intro_mode"] == "FULL"


def test_canon_mirror_validator_accepts_reciprocal_canon() -> None:
    assert validate_canon_mirrors(_canon()) == []


def test_canon_mirror_validator_detects_nonreciprocal_edit() -> None:
    canon = _canon()
    canon["villains"]["CHAR_VILLAIN_006"]["belief"]["mirror_hero"] = "CHAR_HERO_004"
    assert any(
        "CHAR_HERO_001->CHAR_VILLAIN_006" in error
        for error in validate_canon_mirrors(canon)
    )


def test_story_plan_carries_villain_and_serial_contract() -> None:
    card = build_villain_reader_card(_canon(), "CHAR_VILLAIN_003")
    plan = build_story_beat_plan(
        narrative_context_pack={
            "market_cause": "Liquidity tightened.",
            "villain_reader_card": card,
            "continuity_window": {
                "thread_ledger": [
                    {"thread_id": "THREAD_X", "status": "DUE", "promise": "Find route"}
                ]
            },
        },
        hero_id="CHAR_HERO_002",
        villain_id="CHAR_VILLAIN_003",
        battle_result={"outcome": "DRAW"},
        scenario_type="ONE_VS_ONE",
    )
    assert plan.episode_archetype == "VILLAIN_REVEAL"
    assert plan.villain_reader_card["char_id"] == "CHAR_VILLAIN_003"
    assert plan.serial_contract["payoff_required"] is True
    assert "Reveal villain reader step" in plan.panel_beats[1].dialogue_intent
