"""
engine/character/story_state_manager.py
ICG story_state_json 로드 / 저장 / 업데이트 매니저

Supabase 패턴: icg_table() 헬퍼 사용 (engine.common.supabase_client)
"""
from __future__ import annotations

import copy
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

VERSION = "1.0.0"

logger = logging.getLogger(__name__)

DEFAULT_STORY_STATE: dict[str, Any] = {
    "schema_version": "1.0",
    "arc_id": "arc_001",
    "arc_type": "BATTLE_ARC",
    "arc_episode": 1,
    "character_states": {
        "sentinel_yield": {"last_role": "ABSENT", "last_appear_date": None},
        "crypto_shade": {"last_role": "ABSENT", "last_appear_date": None},
        "sector_phantom": {"last_role": "ABSENT", "last_appear_date": None},
        "momentum_rider": {"last_role": "ABSENT", "last_appear_date": None},
    },
    "world_state": {
        "dimensional_rift_progress": 0,
        "volatility_fields_active": False,
    },
    "pending_plot": None,
}

_OUTCOME_HP_MAP: dict[str, int] = {
    "HERO_VICTORY": 10,
    "HERO_TACTICAL_VICTORY": 5,
    "DRAW": 0,
    "VILLAIN_TEMP_VICTORY": -5,
    "HERO_DEFEAT": -15,
    "PEACEFUL_GROWTH": 5,
    "PYRRHIC_VICTORY": -10,
}


def load_story_state(episode_date: str) -> dict:
    """
    전날 story_state_json 로드.
    없으면 DEFAULT_STORY_STATE 반환.

    Args:
        episode_date: 오늘 날짜 (YYYY-MM-DD)
    """
    try:
        from engine.common.supabase_client import icg_table

        yesterday = (
            datetime.strptime(episode_date, "%Y-%m-%d").date() - timedelta(days=1)
        ).isoformat()

        resp = (
            icg_table("daily_analysis")
            .select("story_state_json")
            .eq("analysis_date", yesterday)
            .limit(1)
            .execute()
        )

        if resp.data and resp.data[0].get("story_state_json"):
            state = resp.data[0]["story_state_json"]
            logger.info(
                "[StoryStateManager] 전날 story_state 로드 (arc=%s)", state.get("arc_id")
            )
            return state

        logger.info("[StoryStateManager] 전날 story_state 없음 → 초기값 사용")
        return _deep_copy_default()

    except Exception as e:
        logger.warning("[StoryStateManager] 로드 실패 (영향 없음): %s", e)
        return _deep_copy_default()


def save_story_state(episode_date: str, story_state: dict) -> bool:
    """
    오늘 daily_analysis 행에 story_state_json 저장.
    UPDATE 사용 (analysis_upsert 이후 행 존재 보장).

    Args:
        episode_date: 오늘 날짜 (YYYY-MM-DD)
        story_state: 저장할 상태 dict
    """
    try:
        from engine.common.supabase_client import icg_table

        icg_table("daily_analysis").update(
            {"story_state_json": story_state}
        ).eq("analysis_date", episode_date).execute()

        logger.info(
            "[StoryStateManager] story_state 저장 완료 (arc=%s ep=%d)",
            story_state.get("arc_id"),
            story_state.get("arc_episode", 0),
        )
        return True

    except Exception as e:
        logger.error("[StoryStateManager] 저장 실패: %s", e)
        return False


def update_after_episode(
    story_state: dict,
    guest_characters: list[tuple[str, str]],
    outcome: str,
    vix: float,
) -> dict:
    """
    에피소드 완료 후 story_state 업데이트.

    Args:
        story_state: 현재 상태
        guest_characters: [(캐릭터코드, 역할코드), ...]
        outcome: battle_result["outcome"] 값 (ICG 아웃컴 코드)
        vix: 오늘 VIX 값
    """
    state = copy.deepcopy(story_state)
    today_str = datetime.now(tz=timezone.utc).date().isoformat()

    # 게스트 캐릭터 상태 갱신
    char_states: dict = state.setdefault("character_states", {})
    for char_code, role in guest_characters:
        key = char_code.lower()
        char_states.setdefault(key, {})["last_role"] = role
        char_states[key]["last_appear_date"] = today_str

    # 세계 상태
    world: dict = state.setdefault("world_state", {})
    world["volatility_fields_active"] = vix >= 30

    rift = world.get("dimensional_rift_progress", 0)
    if vix >= 35:
        world["dimensional_rift_progress"] = min(100, rift + 10)
    elif vix < 25:
        world["dimensional_rift_progress"] = max(0, rift - 2)

    # Arc 에피소드 증가
    state["arc_episode"] = state.get("arc_episode", 1) + 1

    logger.info(
        "[StoryStateManager] 에피소드 업데이트 완료 (arc_ep=%d, rift=%d%%)",
        state["arc_episode"],
        world.get("dimensional_rift_progress", 0),
    )
    return state


def _deep_copy_default() -> dict:
    return copy.deepcopy(DEFAULT_STORY_STATE)
