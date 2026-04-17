"""
tests/test_prompt_tpl.py
prompt_tpl.py v2.0 — render_user_prompt() 파라미터 확장 테스트

검증 항목:
  - v2.0 파라미터 없이 호출 → 하위 호환 동작 (TypeError 없음)
  - scenario_type 각 3종이 템플릿에 올바르게 치환
  - ending_tone이 템플릿에 올바르게 치환
  - ALLIANCE에서 hero_ids[0]/[1] 모두 치환
  - heroes=None → [hero_id] 자동 세팅
"""
import pytest

from engine.narrative.prompt_tpl import render_user_prompt

# ── 공통 픽스처 ─────────────────────────────────────────────────────────────

_BASE_ARGS = dict(
    date="2026-04-18",
    episode_id="ICG-2026-04-18-001",
    event_type="NORMAL",
    delta={"VIX": {"curr": 14.5, "pct": -2.1}, "SPY": {"curr": 512.3, "pct": 0.5}},
    battle_result={"outcome": "PEACEFUL_GROWTH", "balance": 0},
    hero_id="CHAR_HERO_001",
    villain_id="CHAR_VILLAIN_005",
    arc_context={"tension": 40},
)


class TestRenderUserPromptBackwardCompat:
    """v2.0 파라미터 없이 기존 방식 호출 — TypeError 없어야 함."""

    def test_call_without_v2_params(self):
        """기존 8개 파라미터만으로 호출 성공."""
        result = render_user_prompt(**_BASE_ARGS)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_default_scenario_type_one_vs_one(self):
        """scenario_type 미전달 시 기본값 ONE_VS_ONE이 템플릿에 반영."""
        result = render_user_prompt(**_BASE_ARGS)
        assert "ONE_VS_ONE" in result

    def test_default_ending_tone_tense(self):
        """ending_tone 미전달 시 기본값 TENSE가 템플릿에 반영."""
        result = render_user_prompt(**_BASE_ARGS)
        assert "TENSE" in result

    def test_heroes_none_falls_back_to_hero_id(self):
        """heroes=None → [hero_id] 자동 세팅, 렌더링 성공."""
        result = render_user_prompt(**_BASE_ARGS, heroes=None)
        assert isinstance(result, str)


class TestRenderUserPromptNoBattle:
    """NO_BATTLE 시나리오 렌더링 검증."""

    def test_no_battle_scenario_in_output(self):
        result = render_user_prompt(
            **_BASE_ARGS,
            scenario_type="NO_BATTLE",
            ending_tone="OPTIMISTIC",
            heroes=["CHAR_HERO_001"],
        )
        assert "NO_BATTLE" in result

    def test_no_battle_hero_id_in_output(self):
        result = render_user_prompt(
            **_BASE_ARGS,
            scenario_type="NO_BATTLE",
            ending_tone="OPTIMISTIC",
            heroes=["CHAR_HERO_001"],
        )
        assert "CHAR_HERO_001" in result

    def test_no_battle_optimistic_tone_in_output(self):
        result = render_user_prompt(
            **_BASE_ARGS,
            scenario_type="NO_BATTLE",
            ending_tone="OPTIMISTIC",
            heroes=["CHAR_HERO_001"],
        )
        assert "OPTIMISTIC" in result

    def test_no_battle_villain_none_in_output(self):
        """NO_BATTLE 분기에서 'NONE'이 출력에 포함 (Notion 템플릿 기준)."""
        result = render_user_prompt(
            **_BASE_ARGS,
            scenario_type="NO_BATTLE",
            ending_tone="OPTIMISTIC",
            heroes=["CHAR_HERO_001"],
        )
        assert "NONE" in result


class TestRenderUserPromptAlliance:
    """ALLIANCE 시나리오 렌더링 검증."""

    def test_alliance_scenario_in_output(self):
        result = render_user_prompt(
            **{**_BASE_ARGS, "event_type": "SHOCK", "villain_id": "CHAR_VILLAIN_004"},
            scenario_type="ALLIANCE",
            ending_tone="OMINOUS",
            heroes=["CHAR_HERO_001", "CHAR_HERO_002"],
        )
        assert "ALLIANCE" in result

    def test_alliance_hero1_in_output(self):
        result = render_user_prompt(
            **{**_BASE_ARGS, "event_type": "SHOCK", "villain_id": "CHAR_VILLAIN_004"},
            scenario_type="ALLIANCE",
            ending_tone="OMINOUS",
            heroes=["CHAR_HERO_001", "CHAR_HERO_002"],
        )
        assert "CHAR_HERO_001" in result

    def test_alliance_hero2_in_output(self):
        """ALLIANCE에서 두 번째 히어로 ID도 템플릿에 포함."""
        result = render_user_prompt(
            **{**_BASE_ARGS, "event_type": "SHOCK", "villain_id": "CHAR_VILLAIN_004"},
            scenario_type="ALLIANCE",
            ending_tone="OMINOUS",
            heroes=["CHAR_HERO_001", "CHAR_HERO_002"],
        )
        assert "CHAR_HERO_002" in result

    def test_alliance_ominous_tone_in_output(self):
        result = render_user_prompt(
            **{**_BASE_ARGS, "event_type": "SHOCK", "villain_id": "CHAR_VILLAIN_004"},
            scenario_type="ALLIANCE",
            ending_tone="OMINOUS",
            heroes=["CHAR_HERO_001", "CHAR_HERO_002"],
        )
        assert "OMINOUS" in result


class TestRenderUserPromptOneVsOne:
    """ONE_VS_ONE 시나리오 렌더링 검증 (기존 동작 유지)."""

    def test_one_vs_one_explicit_in_output(self):
        result = render_user_prompt(
            **{**_BASE_ARGS, "event_type": "BATTLE"},
            scenario_type="ONE_VS_ONE",
            ending_tone="TENSE",
            heroes=["CHAR_HERO_003"],
        )
        assert "ONE_VS_ONE" in result

    def test_hero_villain_both_in_output(self):
        result = render_user_prompt(
            **{**_BASE_ARGS,
               "event_type": "BATTLE",
               "hero_id": "CHAR_HERO_003",
               "villain_id": "CHAR_VILLAIN_002"},
            scenario_type="ONE_VS_ONE",
            ending_tone="TENSE",
            heroes=["CHAR_HERO_003"],
        )
        assert "CHAR_HERO_003" in result
        assert "CHAR_VILLAIN_002" in result


class TestRenderUserPromptEndingTone:
    """EndingTone 3종 모두 올바르게 치환되는지 검증."""

    @pytest.mark.parametrize("tone", ["OPTIMISTIC", "TENSE", "OMINOUS"])
    def test_all_tones_render(self, tone):
        result = render_user_prompt(
            **_BASE_ARGS,
            scenario_type="ONE_VS_ONE",
            ending_tone=tone,
        )
        assert tone in result
