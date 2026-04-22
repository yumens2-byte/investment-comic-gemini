"""
tests/test_story_state_manager_icg.py
ICG story_state_manager — icg_table() 패턴 테스트
conftest.py가 engine.common.supabase_client 전체 모킹
"""
from __future__ import annotations

import copy

import pytest

from engine.character.story_state_manager import (
    DEFAULT_STORY_STATE,
    _deep_copy_default,
    update_after_episode,
)


@pytest.fixture()
def base_state() -> dict:
    return _deep_copy_default()


class TestDeepCopyDefault:
    def test_independent_copies(self):
        s1 = _deep_copy_default()
        s2 = _deep_copy_default()
        s1["arc_id"] = "modified"
        assert s2["arc_id"] == DEFAULT_STORY_STATE["arc_id"]

    def test_schema_version(self):
        assert _deep_copy_default()["schema_version"] == "1.0"


class TestLoadStoryState:
    def test_returns_dict_on_no_data(self):
        """conftest mock이 data=[] 반환 → DEFAULT_STORY_STATE 반환"""
        from engine.character.story_state_manager import load_story_state

        result = load_story_state("2026-04-22")
        assert isinstance(result, dict)
        assert "arc_id" in result

    def test_does_not_raise(self):
        from engine.character.story_state_manager import load_story_state

        # 예외 없이 실행
        load_story_state("2026-04-22")


class TestSaveStoryState:
    def test_does_not_raise(self, base_state):
        from engine.character.story_state_manager import save_story_state

        # conftest mock이 update().eq().execute()를 가로챔 → 예외 없음
        result = save_story_state("2026-04-22", base_state)
        assert isinstance(result, bool)


class TestUpdateAfterEpisode:
    def test_does_not_mutate_input(self, base_state):
        original = copy.deepcopy(base_state)
        update_after_episode(base_state, [], "HERO_VICTORY", 20.0)
        assert base_state == original

    def test_arc_episode_increments(self, base_state):
        result = update_after_episode(base_state, [], "HERO_VICTORY", 20.0)
        assert result["arc_episode"] == base_state["arc_episode"] + 1

    def test_volatility_active_high_vix(self, base_state):
        result = update_after_episode(base_state, [], "HERO_VICTORY", 31.0)
        assert result["world_state"]["volatility_fields_active"] is True

    def test_volatility_inactive_low_vix(self, base_state):
        result = update_after_episode(base_state, [], "HERO_VICTORY", 15.0)
        assert result["world_state"]["volatility_fields_active"] is False

    def test_rift_increases_extreme_vix(self, base_state):
        result = update_after_episode(base_state, [], "HERO_VICTORY", 40.0)
        assert result["world_state"]["dimensional_rift_progress"] == 10

    def test_rift_capped_at_100(self, base_state):
        state = _deep_copy_default()
        state["world_state"]["dimensional_rift_progress"] = 95
        result = update_after_episode(state, [], "HERO_VICTORY", 40.0)
        assert result["world_state"]["dimensional_rift_progress"] == 100

    def test_guest_state_updated(self, base_state):
        guests = [("SENTINEL_YIELD", "WARNER")]
        result = update_after_episode(base_state, guests, "HERO_VICTORY", 20.0)
        assert result["character_states"]["sentinel_yield"]["last_role"] == "WARNER"
        assert result["character_states"]["sentinel_yield"]["last_appear_date"] is not None
