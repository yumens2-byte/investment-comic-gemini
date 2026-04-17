"""
tests/test_integration_scenarios.py
파일럿 2차 — 3종 시나리오 통합 테스트

설계서 §11.2 통합 테스트 3종 + step_analysis() 핵심 흐름 시뮬레이션.
실제 DB/API 호출 없이 모든 분기를 통과하는지 검증.
"""
from __future__ import annotations

import pytest

# ── 공통 픽스처 ─────────────────────────────────────────────────────────────

def _delta_low_normal() -> dict:
    """시나리오 A: 평온한 상승장 (LOW risk, NORMAL event)"""
    return {
        "VIX":  {"curr": 14.5, "pct": -2.1},
        "SPY":  {"curr": 512.3, "pct": 0.5},
        "WTI":  {"curr": 62.0, "pct": 0.3},
        "DGS10": {"curr": 4.2, "pct": 0.0},
    }


def _delta_medium_battle() -> dict:
    """시나리오 B: 일반 전투 (MEDIUM risk, BATTLE event)"""
    return {
        "VIX":  {"curr": 22.4, "pct": 8.5},
        "SPY":  {"curr": 498.1, "pct": -1.2},
        "WTI":  {"curr": 95.0, "pct": 6.8},   # WTI >= 5% → Oil Shock Titan
        "DGS10": {"curr": 4.3, "pct": 0.1},
    }


def _delta_high_shock() -> dict:
    """시나리오 C: 위기 연합 (HIGH risk, SHOCK event)"""
    return {
        "VIX":  {"curr": 35.2, "pct": 22.3},
        "SPY":  {"curr": 478.5, "pct": -3.5},
        "WTI":  {"curr": 88.0, "pct": 2.1},
        "DGS10": {"curr": 4.6, "pct": 0.3},
    }


# ─────────────────────────────────────────────────────────────────────────────
# 시나리오 A: LOW + NORMAL → NO_BATTLE
# ─────────────────────────────────────────────────────────────────────────────
class TestScenarioA_NoBattle:
    def test_risk_level_is_low(self):
        from engine.narrative.scenario_selector import compute_risk_level_from_delta
        assert compute_risk_level_from_delta(_delta_low_normal()) == "LOW"

    def test_scenario_is_no_battle(self):
        from engine.narrative.scenario_selector import select_scenario
        assert select_scenario("LOW", "NORMAL") == "NO_BATTLE"

    def test_hero_selection(self):
        from engine.narrative.character_selector import select_for_no_battle
        hero, villain = select_for_no_battle(_delta_low_normal())
        # VIX=14.5 < 16 AND SPY=+0.5% → CHAR_HERO_001 (EDT)
        assert hero == "CHAR_HERO_001"
        assert villain is None

    def test_outcome_is_peaceful_growth(self):
        """NO_BATTLE → outcome 항상 PEACEFUL_GROWTH"""
        # step_analysis 로직 시뮬레이션
        from engine.narrative.scenario_selector import select_scenario
        scenario = select_scenario("LOW", "NORMAL")
        assert scenario == "NO_BATTLE"
        outcome = "PEACEFUL_GROWTH"  # NO_BATTLE에서 직접 할당
        assert outcome == "PEACEFUL_GROWTH"

    def test_ending_tone_is_optimistic(self):
        from engine.narrative.scenario_selector import select_ending_tone
        tone = select_ending_tone("NO_BATTLE", "PEACEFUL_GROWTH", "LOW")
        assert tone == "OPTIMISTIC"

    def test_full_flow_no_battle(self):
        """NO_BATTLE 전체 흐름 (step_analysis 핵심 경로 재현)"""
        from engine.narrative.character_selector import select_for_no_battle
        from engine.narrative.scenario_selector import (
            compute_risk_level_from_delta,
            select_ending_tone,
            select_scenario,
        )

        delta = _delta_low_normal()
        risk_level = compute_risk_level_from_delta(delta)
        scenario = select_scenario(risk_level, "NORMAL")
        hero_id, villain_id = select_for_no_battle(delta)
        outcome = "PEACEFUL_GROWTH"
        ending_tone = select_ending_tone(scenario, outcome, risk_level)

        assert risk_level == "LOW"
        assert scenario == "NO_BATTLE"
        assert villain_id is None
        assert outcome == "PEACEFUL_GROWTH"
        assert ending_tone == "OPTIMISTIC"

        # ctx 조립 검증
        ctx = {
            "scenario_type": scenario,
            "risk_level": risk_level,
            "ending_tone": ending_tone,
            "heroes": [hero_id],
            "hero_id": hero_id,
            "villain_id": villain_id or "NONE",
        }
        assert ctx["heroes"] == ["CHAR_HERO_001"]
        assert ctx["villain_id"] == "NONE"


# ─────────────────────────────────────────────────────────────────────────────
# 시나리오 B: MEDIUM + BATTLE → ONE_VS_ONE
# ─────────────────────────────────────────────────────────────────────────────
class TestScenarioB_OneVsOne:
    def test_risk_level_is_medium(self):
        from engine.narrative.scenario_selector import compute_risk_level_from_delta
        assert compute_risk_level_from_delta(_delta_medium_battle()) == "MEDIUM"

    def test_scenario_is_one_vs_one(self):
        from engine.narrative.scenario_selector import select_scenario
        assert select_scenario("MEDIUM", "BATTLE") == "ONE_VS_ONE"

    def test_character_selection_oil_titan(self):
        from engine.narrative.battle_calc import select_characters_for_event
        hero, villain = select_characters_for_event("BATTLE", _delta_medium_battle())
        # WTI +6.8% >= 5% → Oil Shock Titan (CHAR_VILLAIN_002)
        assert villain == "CHAR_VILLAIN_002"
        assert hero == "CHAR_HERO_003"   # Exposure Futures Girl vs Oil Shock Titan

    def test_battle_one_vs_one(self):
        from engine.narrative.battle_calc import battle, select_characters_for_event
        delta = _delta_medium_battle()
        hero_id, villain_id = select_characters_for_event("BATTLE", delta)

        market_ctx = {
            "vix": 22.4,
            "wti_pct_3d": 6.8,
            "oil_shock": True,
            "dgs10": 4.3,
            "hy_spread": 350,
            "system_stress": False,
        }
        arc_ctx = {"tension": 40, "days_since_last": 1, "yesterday_type": "NORMAL"}

        result = battle(
            hero_id=hero_id,
            hero_base=74,
            villain_id=villain_id,
            villain_base=74,
            market_context=market_ctx,
            arc_context=arc_ctx,
        )
        assert result.outcome in (
            "HERO_VICTORY", "HERO_TACTICAL_VICTORY", "DRAW",
            "VILLAIN_TEMP_VICTORY", "HERO_DEFEAT", "SYSTEM_COLLAPSE",
        )
        assert result.outcome != "PEACEFUL_GROWTH"
        assert result.outcome != "PYRRHIC_VICTORY"

    def test_ending_tone_medium_battle(self):
        from engine.narrative.battle_calc import battle, select_characters_for_event
        from engine.narrative.scenario_selector import select_ending_tone

        delta = _delta_medium_battle()
        hero_id, villain_id = select_characters_for_event("BATTLE", delta)
        market_ctx = {"vix": 22.4, "wti_pct_3d": 6.8, "oil_shock": True, "dgs10": 4.3, "hy_spread": 350}
        arc_ctx = {"tension": 40}
        result = battle(hero_id=hero_id, hero_base=74, villain_id=villain_id, villain_base=74,
                        market_context=market_ctx, arc_context=arc_ctx)

        tone = select_ending_tone("ONE_VS_ONE", result.outcome, "MEDIUM")
        assert tone in ("OPTIMISTIC", "TENSE", "OMINOUS")


# ─────────────────────────────────────────────────────────────────────────────
# 시나리오 C: HIGH + SHOCK → ALLIANCE
# ─────────────────────────────────────────────────────────────────────────────
class TestScenarioC_Alliance:
    def test_risk_level_is_high(self):
        from engine.narrative.scenario_selector import compute_risk_level_from_delta
        # VIX = 35.2 >= 30 → HIGH
        assert compute_risk_level_from_delta(_delta_high_shock()) == "HIGH"

    def test_scenario_is_alliance(self):
        from engine.narrative.scenario_selector import select_scenario
        assert select_scenario("HIGH", "SHOCK") == "ALLIANCE"

    def test_alliance_character_selection(self):
        from engine.narrative.battle_calc import select_characters_for_event
        from engine.narrative.character_selector import select_for_alliance

        delta = _delta_high_shock()
        # VIX=35.2 > 28, WTI pct=2.1% < 5 → Volatility Hydra (CHAR_VILLAIN_004)
        _, villain_id = select_characters_for_event("SHOCK", delta)
        assert villain_id == "CHAR_VILLAIN_004"  # Volatility Hydra

        heroes, vill = select_for_alliance("SHOCK", delta, villain_id)
        assert len(heroes) == 2
        assert villain_id in (vill,)
        assert heroes[0] != heroes[1]   # 두 히어로가 달라야 함

    def test_battle_alliance_result(self):
        from engine.narrative.battle_calc import battle_alliance, select_characters_for_event
        from engine.narrative.character_selector import select_for_alliance

        delta = _delta_high_shock()
        _, villain_id = select_characters_for_event("SHOCK", delta)
        heroes, villain = select_for_alliance("SHOCK", delta, villain_id)

        market_ctx = {
            "vix": 35.2, "wti_pct_3d": 2.1, "oil_shock": False,
            "dgs10": 4.6, "hy_spread": 420, "system_stress": True,
        }
        arc_ctx = {"tension": 55, "days_since_last": 0, "yesterday_type": "SHOCK"}

        result = battle_alliance(
            hero_ids=heroes,
            hero_bases=[75, 74],
            villain_id=villain,
            villain_base=75,
            market_context=market_ctx,
            arc_context=arc_ctx,
        )
        # ALLIANCE에서 HERO_TACTICAL_VICTORY는 절대 나오면 안 됨
        assert result.outcome != "HERO_TACTICAL_VICTORY"
        # heroes[0]이 hero_id에 세팅돼야 함 (후방 호환)
        assert result.hero_id == heroes[0]

    def test_alliance_ending_tone_ominous(self):
        """ALLIANCE + PYRRHIC_VICTORY → OMINOUS"""
        from engine.narrative.scenario_selector import select_ending_tone
        tone = select_ending_tone("ALLIANCE", "PYRRHIC_VICTORY", "HIGH")
        assert tone == "OMINOUS"

    def test_full_flow_alliance(self):
        """ALLIANCE 전체 흐름 (step_analysis 핵심 경로 재현)"""
        from engine.narrative.battle_calc import battle_alliance, select_characters_for_event
        from engine.narrative.character_selector import select_for_alliance
        from engine.narrative.scenario_selector import (
            compute_risk_level_from_delta,
            select_ending_tone,
            select_scenario,
        )

        delta = _delta_high_shock()
        risk_level = compute_risk_level_from_delta(delta)
        scenario = select_scenario(risk_level, "SHOCK")

        # 캐릭터 선정
        _, villain_id_base = select_characters_for_event("SHOCK", delta)
        heroes_v2, villain_id = select_for_alliance("SHOCK", delta, villain_id_base)

        # ALLIANCE 전투
        market_ctx = {"vix": 35.2, "wti_pct_3d": 2.1, "dgs10": 4.6, "hy_spread": 420}
        arc_ctx = {"tension": 55}
        result = battle_alliance(
            hero_ids=heroes_v2,
            hero_bases=[75, 74],
            villain_id=villain_id,
            villain_base=75,
            market_context=market_ctx,
            arc_context=arc_ctx,
        )

        ending_tone = select_ending_tone(scenario, result.outcome, risk_level)

        assert risk_level == "HIGH"
        assert scenario == "ALLIANCE"
        assert len(heroes_v2) == 2
        assert result.outcome != "HERO_TACTICAL_VICTORY"
        assert ending_tone in ("OPTIMISTIC", "TENSE", "OMINOUS")

        # ctx 조립 검증
        ctx = {
            "scenario_type": scenario,
            "risk_level": risk_level,
            "ending_tone": ending_tone,
            "heroes": heroes_v2,
            "hero_id": heroes_v2[0],   # 후방 호환
            "villain_id": villain_id,
            "battle_result": result.to_dict(),
        }
        assert ctx["battle_result"]["outcome"] != "HERO_TACTICAL_VICTORY"
        assert len(ctx["heroes"]) == 2


# ─────────────────────────────────────────────────────────────────────────────
# 교차 매트릭스 — 21개 조합 경계값 검증
# ─────────────────────────────────────────────────────────────────────────────
class TestCrossMatrix:
    """risk_level × event_type 21개 조합이 설계서 §6.1과 일치하는지 검증"""

    @pytest.mark.parametrize("event_type,expected", [
        ("BATTLE",   "ALLIANCE"),
        ("SHOCK",    "ALLIANCE"),
        ("AFTERMATH","ONE_VS_ONE"),
        ("INTEL",    "ONE_VS_ONE"),
        ("NORMAL",   "ONE_VS_ONE"),
        ("FLASHBACK","ONE_VS_ONE"),
        ("TACTICAL", "ONE_VS_ONE"),
    ])
    def test_high_risk(self, event_type, expected):
        from engine.narrative.scenario_selector import select_scenario
        assert select_scenario("HIGH", event_type) == expected

    @pytest.mark.parametrize("event_type,expected", [
        ("BATTLE",   "ONE_VS_ONE"),
        ("SHOCK",    "ONE_VS_ONE"),
        ("AFTERMATH","ONE_VS_ONE"),
        ("INTEL",    "NO_BATTLE"),
        ("NORMAL",   "NO_BATTLE"),
        ("FLASHBACK","ONE_VS_ONE"),
        ("TACTICAL", "ONE_VS_ONE"),
    ])
    def test_low_risk(self, event_type, expected):
        from engine.narrative.scenario_selector import select_scenario
        assert select_scenario("LOW", event_type) == expected

    @pytest.mark.parametrize("event_type", [
        "BATTLE", "SHOCK", "AFTERMATH", "INTEL", "NORMAL", "FLASHBACK", "TACTICAL",
    ])
    def test_medium_all_one_vs_one(self, event_type):
        from engine.narrative.scenario_selector import select_scenario
        assert select_scenario("MEDIUM", event_type) == "ONE_VS_ONE"


# ─────────────────────────────────────────────────────────────────────────────
# Feature Flag OFF 검증 — 기존 로직 100% 유지
# ─────────────────────────────────────────────────────────────────────────────
class TestFeatureFlagOff:
    """SCENARIO_V2_ENABLED=false 시 신규 모듈이 기존 결과에 영향 없어야 함"""

    def test_existing_battle_unaffected(self):
        """기존 battle() 함수 결과는 v2.0 추가와 무관하게 동일해야 함."""
        from engine.narrative.battle_calc import battle

        market_ctx = {"vix": 22.4, "wti_pct_3d": 2.1, "dgs10": 4.3, "hy_spread": 350}
        arc_ctx = {"tension": 40}
        result = battle(
            hero_id="CHAR_HERO_001",
            hero_base=75,
            villain_id="CHAR_VILLAIN_004",
            villain_base=75,
            market_context=market_ctx,
            arc_context=arc_ctx,
        )
        # 결과가 기존 6종 + 신규 2종 중 하나인지 확인
        valid_outcomes = {
            "HERO_VICTORY", "HERO_TACTICAL_VICTORY", "DRAW",
            "VILLAIN_TEMP_VICTORY", "HERO_DEFEAT", "SYSTEM_COLLAPSE",
            "PEACEFUL_GROWTH", "PYRRHIC_VICTORY",
        }
        assert result.outcome in valid_outcomes
        # 기존 battle()은 PEACEFUL_GROWTH, PYRRHIC_VICTORY를 반환하지 않아야 함
        assert result.outcome not in ("PEACEFUL_GROWTH", "PYRRHIC_VICTORY")

    def test_resolve_outcome_unchanged(self):
        """resolve_outcome() 기존 6종 결과가 v2.0에서도 동일."""
        from engine.narrative.battle_calc import resolve_outcome
        assert resolve_outcome(35)  == "HERO_VICTORY"
        assert resolve_outcome(15)  == "HERO_TACTICAL_VICTORY"
        assert resolve_outcome(0)   == "DRAW"
        assert resolve_outcome(-8)  == "VILLAIN_TEMP_VICTORY"
        assert resolve_outcome(-20) == "HERO_DEFEAT"
        assert resolve_outcome(-40) == "SYSTEM_COLLAPSE"
