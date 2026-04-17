"""
engine/narrative/character_selector.py
ICG 2차 고도화 — NO_BATTLE, ALLIANCE 시나리오 캐릭터 선정.
ONE_VS_ONE은 기존 battle_calc.select_characters_for_event() 그대로 유지.
"""

from __future__ import annotations

import logging

VERSION = "2.0.0"

logger = logging.getLogger(__name__)

# ── 캐릭터 Canon ──────────────────────────────────────────────────────────────
CANON_HERO_IDS: list[str] = [
    "CHAR_HERO_001",   # EDT — 전략 수호자
    "CHAR_HERO_002",   # Iron Securities Nuna — 데이터 분석가
    "CHAR_HERO_003",   # Exposure Futures Girl — 선물 감지
    "CHAR_HERO_004",   # Gold Bond Muscle — 금/채권 방어
    "CHAR_HERO_005",   # (5번째 히어로)
]

# 빌런 → 주 히어로 상극 매핑 (battle_calc.select_characters_for_event 기반 역매핑)
_VILLAIN_TO_MAIN_HERO: dict[str, str] = {
    "CHAR_VILLAIN_001": "CHAR_HERO_002",   # Debt Titan → Iron Nuna
    "CHAR_VILLAIN_002": "CHAR_HERO_003",   # Oil Shock Titan → Exposure Futures
    "CHAR_VILLAIN_003": "CHAR_HERO_005",   # Liquidity Leviathan → Gold Bond
    "CHAR_VILLAIN_004": "CHAR_HERO_001",   # Volatility Hydra → EDT
    "CHAR_VILLAIN_005": "CHAR_HERO_001",   # Algorithm Reaper → EDT
    "CHAR_VILLAIN_006": "CHAR_HERO_004",   # War Dominion → Futures Girl
}

# 보조 히어로 우선순위 (event_type별)
_SUPPORT_PRIORITY: dict[str, list[str]] = {
    "BATTLE":   ["CHAR_HERO_003", "CHAR_HERO_001", "CHAR_HERO_002"],
    "SHOCK":    ["CHAR_HERO_004", "CHAR_HERO_001", "CHAR_HERO_002"],
    "DEFAULT":  ["CHAR_HERO_001", "CHAR_HERO_002", "CHAR_HERO_004"],
}


def select_for_no_battle(delta: dict) -> tuple[str, None]:
    """
    NO_BATTLE 시나리오: Villain 없는 히어로 단독 서사.

    선정 기준:
        VIX < 16 AND SPY > 0%  → CHAR_HERO_001 (EDT, 평온한 상승)
        SPY > +1.0%             → CHAR_HERO_003 (Exposure Futures, 모멘텀)
        VIX > 18                → CHAR_HERO_004 (Gold Bond, 방어적)
        else                    → CHAR_HERO_002 (Iron Nuna, 분석적)

    Args:
        delta: compute() 결과 dict.

    Returns:
        (hero_id, None) — villain은 항상 None.
    """
    vix     = delta.get("VIX", {}).get("curr", 20) or 20
    spy_pct = delta.get("SPY", {}).get("pct", 0) or 0

    if vix < 16 and spy_pct > 0:
        hero_id = "CHAR_HERO_001"
    elif spy_pct > 1.0:
        hero_id = "CHAR_HERO_003"
    elif vix > 18:
        hero_id = "CHAR_HERO_004"
    else:
        hero_id = "CHAR_HERO_002"

    logger.debug(
        "[CharSelector v%s] NO_BATTLE → hero=%s (VIX=%.1f SPY=%+.2f%%)",
        VERSION, hero_id, vix, spy_pct,
    )
    return hero_id, None


def select_for_alliance(
    event_type: str,
    delta: dict,
    main_villain_id: str,
) -> tuple[list[str], str]:
    """
    ALLIANCE 시나리오: 히어로 2명 + 빌런 1명.

    로직:
        1. 주 히어로 = _VILLAIN_TO_MAIN_HERO[main_villain_id]
        2. 보조 히어로 = pool에서 event_type 우선순위 기준 선정

    Args:
        event_type:      현재 이벤트 타입 (보조 히어로 기준)
        delta:           시장 변화 데이터
        main_villain_id: select_characters_for_event()로 산출된 빌런 ID

    Returns:
        ([main_hero_id, support_hero_id], villain_id)
    """
    main_hero    = _VILLAIN_TO_MAIN_HERO.get(main_villain_id, "CHAR_HERO_001")
    pool         = [h for h in CANON_HERO_IDS if h != main_hero]
    support_hero = _pick_support(pool, event_type)
    hero_ids     = [main_hero, support_hero]

    logger.debug(
        "[CharSelector v%s] ALLIANCE → heroes=%s villain=%s (event=%s)",
        VERSION, hero_ids, main_villain_id, event_type,
    )
    return hero_ids, main_villain_id


def _pick_support(pool: list[str], event_type: str) -> str:
    """pool에서 event_type 우선순위에 따라 보조 히어로를 선정한다."""
    priority = _SUPPORT_PRIORITY.get(event_type.upper(), _SUPPORT_PRIORITY["DEFAULT"])
    for hero_id in priority:
        if hero_id in pool:
            return hero_id
    return pool[0] if pool else "CHAR_HERO_001"
