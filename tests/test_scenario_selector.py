"""tests/test_scenario_selector.py
ICG v2.0 — scenario_selector 유닛 테스트
21개 조합 (7 event_type × 3 risk_level) 전수 검증
"""
import pytest

from engine.narrative.scenario_selector import (
    compute_risk_level_from_delta,
    select_ending_tone,
    select_scenario,
)


class TestSelectScenario:
    """21개 조합 전수 테스트 (7 event_type × 3 risk_level)."""

    # ── ALLIANCE 발동 조건: HIGH + (BATTLE|SHOCK) ──────────────────────────────
    @pytest.mark.parametrize("event_type", ["BATTLE", "SHOCK"])
    def test_alliance_high_risk(self, event_type):
        assert select_scenario("HIGH", event_type) == "ALLIANCE"

    # ── NO_BATTLE 발동 조건: LOW + (NORMAL|INTEL) ─────────────────────────────
    @pytest.mark.parametrize("event_type", ["NORMAL", "INTEL"])
    def test_no_battle_low_risk(self, event_type):
        assert select_scenario("LOW", event_type) == "NO_BATTLE"

    # ── ONE_VS_ONE — HIGH + (비 BATTLE|SHOCK) ─────────────────────────────────
    @pytest.mark.parametrize("event_type", ["AFTERMATH", "INTEL", "NORMAL", "FLASHBACK", "TACTICAL"])
    def test_one_vs_one_high_non_crisis(self, event_type):
        assert select_scenario("HIGH", event_type) == "ONE_VS_ONE"

    # ── ONE_VS_ONE — LOW + (비 NORMAL|INTEL) ─────────────────────────────────
    @pytest.mark.parametrize("event_type", ["BATTLE", "SHOCK", "AFTERMATH", "FLASHBACK", "TACTICAL"])
    def test_one_vs_one_low_non_calm(self, event_type):
        assert select_scenario("LOW", event_type) == "ONE_VS_ONE"

    # ── ONE_VS_ONE — MEDIUM 전체 (7종 모두) ──────────────────────────────────
    @pytest.mark.parametrize(
        "event_type",
        ["BATTLE", "SHOCK", "AFTERMATH", "INTEL", "NORMAL", "FLASHBACK", "TACTICAL"],
    )
    def test_one_vs_one_medium_all(self, event_type):
        assert select_scenario("MEDIUM", event_type) == "ONE_VS_ONE"

    # ── 방어: None 입력 ────────────────────────────────────────────────────────
    def test_none_input_returns_one_vs_one(self):
        assert select_scenario(None, None) == "ONE_VS_ONE"

    # ── 대소문자 무관 ──────────────────────────────────────────────────────────
    def test_case_insensitive(self):
        assert select_scenario("high", "battle") == "ALLIANCE"
        assert select_scenario("low", "normal") == "NO_BATTLE"
        assert select_scenario("Medium", "Battle") == "ONE_VS_ONE"


class TestSelectEndingTone:
    """EndingTone 결정 로직 테스트."""

    def test_no_battle_always_optimistic(self):
        """NO_BATTLE은 어떤 outcome/risk에서도 항상 OPTIMISTIC."""
        for outcome in ["PEACEFUL_GROWTH", "HERO_VICTORY", "HERO_DEFEAT", "SYSTEM_COLLAPSE", "DRAW"]:
            for risk in ["LOW", "MEDIUM", "HIGH"]:
                assert select_ending_tone("NO_BATTLE", outcome, risk) == "OPTIMISTIC", \
                    f"NO_BATTLE + {outcome} + {risk} → OPTIMISTIC이어야 함"

    def test_system_collapse_ominous(self):
        for scenario in ("ONE_VS_ONE", "ALLIANCE"):
            assert select_ending_tone(scenario, "SYSTEM_COLLAPSE", "HIGH") == "OMINOUS"
            assert select_ending_tone(scenario, "SYSTEM_COLLAPSE", "LOW") == "OMINOUS"

    def test_hero_defeat_ominous(self):
        assert select_ending_tone("ONE_VS_ONE", "HERO_DEFEAT", "MEDIUM") == "OMINOUS"

    def test_alliance_pyrrhic_ominous(self):
        assert select_ending_tone("ALLIANCE", "PYRRHIC_VICTORY", "HIGH") == "OMINOUS"
        assert select_ending_tone("ALLIANCE", "PYRRHIC_VICTORY", "MEDIUM") == "OMINOUS"

    def test_high_villain_victory_ominous(self):
        assert select_ending_tone("ONE_VS_ONE", "VILLAIN_TEMP_VICTORY", "HIGH") == "OMINOUS"

    def test_medium_villain_victory_tense(self):
        assert select_ending_tone("ONE_VS_ONE", "VILLAIN_TEMP_VICTORY", "MEDIUM") == "TENSE"

    def test_low_villain_victory_tense(self):
        assert select_ending_tone("ONE_VS_ONE", "VILLAIN_TEMP_VICTORY", "LOW") == "TENSE"

    def test_draw_tense(self):
        assert select_ending_tone("ONE_VS_ONE", "DRAW", "MEDIUM") == "TENSE"
        assert select_ending_tone("ONE_VS_ONE", "DRAW", "HIGH") == "TENSE"

    def test_hero_victory_optimistic(self):
        assert select_ending_tone("ONE_VS_ONE", "HERO_VICTORY", "LOW") == "OPTIMISTIC"
        assert select_ending_tone("ONE_VS_ONE", "HERO_TACTICAL_VICTORY", "MEDIUM") == "OPTIMISTIC"

    def test_one_vs_one_pyrrhic_not_ominous(self):
        """ONE_VS_ONE에서 PYRRHIC_VICTORY는 OMINOUS 아님 (ALLIANCE 전용 규칙)."""
        # PYRRHIC_VICTORY가 _OMINOUS_OUTCOMES에 없으므로 OPTIMISTIC이어야 함
        result = select_ending_tone("ONE_VS_ONE", "PYRRHIC_VICTORY", "HIGH")
        assert result in ("OPTIMISTIC", "TENSE")  # OMINOUS 아님


class TestComputeRiskLevelFromDelta:
    """risk_level 자체 계산 테스트."""

    def _delta(self, vix: float, wti: float) -> dict:
        return {"VIX": {"curr": vix}, "WTI": {"curr": wti}}

    def test_high_vix(self):
        assert compute_risk_level_from_delta(self._delta(30, 50)) == "HIGH"

    def test_high_wti(self):
        assert compute_risk_level_from_delta(self._delta(15, 100)) == "HIGH"

    def test_medium_vix(self):
        assert compute_risk_level_from_delta(self._delta(20, 50)) == "MEDIUM"

    def test_medium_wti(self):
        assert compute_risk_level_from_delta(self._delta(15, 70)) == "MEDIUM"

    def test_low(self):
        assert compute_risk_level_from_delta(self._delta(15, 60)) == "LOW"

    def test_empty_delta_returns_low(self):
        assert compute_risk_level_from_delta({}) == "LOW"

    def test_boundary_vix_30(self):
        assert compute_risk_level_from_delta(self._delta(30, 0)) == "HIGH"

    def test_boundary_vix_29(self):
        assert compute_risk_level_from_delta(self._delta(29, 0)) == "MEDIUM"
