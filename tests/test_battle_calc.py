"""
tests/test_battle_calc.py
BattleResult 결정론적 검증 (doc 07, doc 16a 기준).

Acceptance Criteria (Track C):
- [x] outcome 6단계 모든 분기 검증
- [x] 히어로/빌런 특수 시너지 반영
- [x] Canon 외 캐릭터 입력 시 UnknownCharacterError
- [x] 순수 함수 보장 — 동일 입력 동일 출력
"""

import pytest

from engine.common.exceptions import UnknownCharacterError
from engine.narrative.battle_calc import (
    CANON_HERO_IDS,
    CANON_VILLAIN_IDS,
    battle,
    resolve_outcome,
    select_characters_for_event,
)


class TestResolveOutcome:
    """resolve_outcome() — balance → Outcome 변환 테이블 검증."""

    def test_hero_victory(self):
        assert resolve_outcome(30) == "HERO_VICTORY"
        assert resolve_outcome(50) == "HERO_VICTORY"
        assert resolve_outcome(100) == "HERO_VICTORY"

    def test_hero_tactical_victory(self):
        assert resolve_outcome(10) == "HERO_TACTICAL_VICTORY"
        assert resolve_outcome(20) == "HERO_TACTICAL_VICTORY"
        assert resolve_outcome(29) == "HERO_TACTICAL_VICTORY"

    def test_draw(self):
        assert resolve_outcome(9) == "DRAW"
        assert resolve_outcome(0) == "DRAW"
        assert resolve_outcome(-5) == "DRAW"

    def test_villain_temp_victory(self):
        assert resolve_outcome(-6) == "VILLAIN_TEMP_VICTORY"
        assert resolve_outcome(-10) == "VILLAIN_TEMP_VICTORY"

    def test_hero_defeat(self):
        assert resolve_outcome(-11) == "HERO_DEFEAT"
        assert resolve_outcome(-30) == "HERO_DEFEAT"

    def test_system_collapse(self):
        assert resolve_outcome(-31) == "SYSTEM_COLLAPSE"
        assert resolve_outcome(-100) == "SYSTEM_COLLAPSE"

    def test_boundary_values(self):
        """경계값 정밀 검증."""
        assert resolve_outcome(9) == "DRAW"       # 10 미만
        assert resolve_outcome(10) == "HERO_TACTICAL_VICTORY"  # 10 이상
        assert resolve_outcome(-5) == "DRAW"       # -5 이상
        assert resolve_outcome(-6) == "VILLAIN_TEMP_VICTORY"   # -6
        assert resolve_outcome(-30) == "HERO_DEFEAT"           # -30
        assert resolve_outcome(-31) == "SYSTEM_COLLAPSE"       # -31 미만


class TestBattle:
    """battle() 통합 검증."""

    _MARKET_NORMAL = {"oil_shock": False, "vix": 18.0, "wti_pct_3d": 2.0, "dgs10": 4.3}
    _ARC_NORMAL = {"tension": 30, "days_since_last": 0}

    def test_hero_victory_with_synergy(self):
        """CHAR_HERO_003 + oil_shock + form_bonus=10 → HERO_VICTORY (balance >= 30).

        계산:
          hero: base=80 + oil_synergy=8 + high_tension=5 + form_bonus=10 = 103
          villain: base=60 + oil_intensity=min(int(6.0*1.5),25)=9 = 69
          balance = 103 - 69 = 34 → HERO_VICTORY
        """
        result = battle(
            "CHAR_HERO_003", 80,
            "CHAR_VILLAIN_002", 60,
            {"oil_shock": True, "wti_pct_3d": 6.0, "vix": 20.0},
            {"tension": 80},
            form_bonus=10,
        )
        assert result.balance >= 30
        assert result.outcome == "HERO_VICTORY"
        assert "oil_synergy" in result.hero_power_breakdown
        assert "form_bonus" in result.hero_power_breakdown

    def test_system_collapse(self):
        """doc 07 예시: high VIX + low base hero → SYSTEM_COLLAPSE."""
        result = battle(
            "CHAR_HERO_001", 60,
            "CHAR_VILLAIN_004", 100,
            {"vix": 45, "wti_pct_3d": 0},
            {"tension": 95},
        )
        assert result.balance <= -30
        assert result.outcome == "SYSTEM_COLLAPSE"
        assert "vix_amp" in result.villain_power_breakdown

    def test_draw_scenario(self):
        """균형 잡힌 전투 → DRAW."""
        result = battle(
            "CHAR_HERO_001", 75,
            "CHAR_VILLAIN_005", 70,
            self._MARKET_NORMAL,
            self._ARC_NORMAL,
        )
        # base 차이 5 → DRAW 범위
        assert result.outcome in ("DRAW", "HERO_TACTICAL_VICTORY", "VILLAIN_TEMP_VICTORY")

    def test_pure_function(self):
        """동일 입력 → 동일 출력 (순수 함수 보장)."""
        args = (
            "CHAR_HERO_002", 78,
            "CHAR_VILLAIN_001", 72,
            self._MARKET_NORMAL,
            self._ARC_NORMAL,
        )
        result1 = battle(*args)
        result2 = battle(*args)
        assert result1.outcome == result2.outcome
        assert result1.balance == result2.balance

    def test_battle_result_frozen(self):
        """BattleResult는 불변이어야 한다 — Claude가 outcome 수정 불가."""
        result = battle(
            "CHAR_HERO_001", 85,
            "CHAR_VILLAIN_002", 80,
            self._MARKET_NORMAL,
            self._ARC_NORMAL,
        )
        with pytest.raises((AttributeError, TypeError)):
            result.outcome = "HERO_VICTORY"  # type: ignore

    def test_unknown_hero_raises(self):
        """Canon 외 hero_id → UnknownCharacterError."""
        with pytest.raises(UnknownCharacterError):
            battle(
                "CHAR_HERO_999", 80,
                "CHAR_VILLAIN_001", 72,
                self._MARKET_NORMAL,
                self._ARC_NORMAL,
            )

    def test_unknown_villain_raises(self):
        """Canon 외 villain_id → UnknownCharacterError."""
        with pytest.raises(UnknownCharacterError):
            battle(
                "CHAR_HERO_001", 85,
                "CHAR_VILLAIN_999", 72,
                self._MARKET_NORMAL,
                self._ARC_NORMAL,
            )

    def test_high_tension_bonus(self):
        """arc tension >= 75 → hero +5 보너스 적용."""
        result_low = battle(
            "CHAR_HERO_001", 70,
            "CHAR_VILLAIN_004", 70,
            {"vix": 20.0, "wti_pct_3d": 0},
            {"tension": 10},
        )
        result_high = battle(
            "CHAR_HERO_001", 70,
            "CHAR_VILLAIN_004", 70,
            {"vix": 20.0, "wti_pct_3d": 0},
            {"tension": 80},
        )
        assert result_high.hero_power > result_low.hero_power
        assert "high_tension" in result_high.hero_power_breakdown

    def test_to_dict_has_required_keys(self):
        """BattleResult.to_dict()에 Claude 입력 필수 키가 모두 있어야 한다."""
        result = battle(
            "CHAR_HERO_001", 85,
            "CHAR_VILLAIN_002", 80,
            self._MARKET_NORMAL,
            self._ARC_NORMAL,
        )
        d = result.to_dict()
        required_keys = {"hero_power", "villain_power", "balance", "outcome"}
        assert required_keys.issubset(set(d.keys()))

    def test_gold_bond_vix_defensive(self):
        """CHAR_HERO_005 (Gold Bond) + VIX > 30 → defensive_mode +12."""
        result = battle(
            "CHAR_HERO_005", 70,
            "CHAR_VILLAIN_004", 75,
            {"vix": 35.0, "wti_pct_3d": 0},
            {"tension": 40},
        )
        assert "defensive_mode" in result.hero_power_breakdown
        assert result.hero_power_breakdown["defensive_mode"] == 12


class TestSelectCharacters:
    """select_characters_for_event() 검증."""

    def test_oil_shock_selects_oil_titan_and_leverage(self):
        hero_id, villain_id = select_characters_for_event(
            "BATTLE", {"WTI": {"pct": 7.0}, "VIX": {"curr": 20.0}, "DGS10": {"curr": 4.3}}
        )
        assert villain_id == "CHAR_VILLAIN_002"
        assert hero_id == "CHAR_HERO_003"

    def test_vix_spike_selects_hydra(self):
        hero_id, villain_id = select_characters_for_event(
            "SHOCK", {"WTI": {"pct": 1.0}, "VIX": {"curr": 32.0}, "DGS10": {"curr": 4.3}}
        )
        assert villain_id == "CHAR_VILLAIN_004"

    def test_all_outputs_are_canon(self):
        """모든 이벤트 타입에서 Canon ID만 반환."""
        event_types = ["BATTLE", "SHOCK", "AFTERMATH", "INTEL", "NORMAL"]
        for et in event_types:
            h, v = select_characters_for_event(et, {})
            assert h in CANON_HERO_IDS, f"{et}: hero {h} not in canon"
            assert v in CANON_VILLAIN_IDS, f"{et}: villain {v} not in canon"


# ── Event Classifier 테스트 ───────────────────────────────────────────────────

from engine.analysis.event_classifier import classify  # noqa: E402


class TestEventClassifier:
    """classify() 7종 분기 검증."""

    def test_battle_from_oil_shock(self):
        delta = {"WTI": {"pct": 6.0}, "VIX": {"curr": 22.0, "pct": 10.0}}
        assert classify(delta, {}) == "BATTLE"

    def test_shock_from_vix_spike(self):
        delta = {"WTI": {"pct": 1.0}, "VIX": {"curr": 30.0, "pct": 25.0}}
        assert classify(delta, {}) == "SHOCK"

    def test_battle_from_rate_surge(self):
        delta = {"WTI": {"pct": 1.0}, "VIX": {"curr": 18.0, "pct": 5.0}, "DGS10": {"curr": 5.1}}
        assert classify(delta, {}) == "BATTLE"

    def test_battle_from_spy_crash(self):
        delta = {"WTI": {"pct": 0.5}, "VIX": {"curr": 20.0, "pct": 10.0}, "SPY": {"pct": -3.5}}
        assert classify(delta, {}) == "BATTLE"

    def test_aftermath(self):
        delta = {"WTI": {"pct": 1.0}, "VIX": {"curr": 22.0, "pct": 5.0}}
        arc = {"yesterday_type": "BATTLE", "tension": 60}
        assert classify(delta, arc) == "AFTERMATH"

    def test_intel_quiet_market(self):
        delta = {"WTI": {"pct": 0.5}, "VIX": {"curr": 16.0, "pct": 2.0}}
        arc = {"yesterday_type": "NORMAL", "tension": 20, "days_since_last": 3}
        assert classify(delta, arc) == "INTEL"

    def test_normal_default(self):
        delta = {"WTI": {"pct": 0.5}, "VIX": {"curr": 16.0, "pct": 2.0}}
        arc = {"yesterday_type": "NORMAL", "tension": 10, "days_since_last": 0}
        assert classify(delta, arc) == "NORMAL"

    def test_oil_shock_priority_over_vix(self):
        """유가 쇼크가 VIX 급등보다 우선순위가 높아야 한다."""
        delta = {
            "WTI": {"pct": 7.0},
            "VIX": {"curr": 32.0, "pct": 30.0},
        }
        # WTI >= 5% → BATTLE (VIX SHOCK 아님)
        assert classify(delta, {}) == "BATTLE"

    def test_aftermath_requires_tension_threshold(self):
        """tension <= 40이면 AFTERMATH 불발."""
        delta = {"WTI": {"pct": 1.0}, "VIX": {"curr": 20.0, "pct": 5.0}}
        arc = {"yesterday_type": "BATTLE", "tension": 30}  # tension <= 40
        result = classify(delta, arc)
        # AFTERMATH가 아닌 INTEL 또는 NORMAL이어야 한다
        assert result in ("INTEL", "NORMAL")
