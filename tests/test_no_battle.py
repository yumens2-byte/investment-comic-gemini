"""tests/test_no_battle.py
NO_BATTLE 시나리오 — 히어로 선정 + PEACEFUL_GROWTH 통합 검증
"""
from engine.narrative.character_selector import select_for_no_battle
from engine.narrative.scenario_selector import select_ending_tone, select_scenario


def _delta(vix: float, spy_pct: float) -> dict:
    """테스트용 delta 생성 헬퍼."""
    return {
        "VIX": {"curr": vix, "pct": 0.0},
        "SPY": {"curr": 500.0, "pct": spy_pct},
        "WTI": {"curr": 80.0, "pct": 0.0},
    }


class TestSelectForNoBattle:
    """히어로 선정 4분기 검증."""

    def test_vix_low_spy_positive_returns_edt(self):
        """VIX < 16 AND SPY > 0% → CHAR_HERO_001 (EDT)."""
        hero, villain = select_for_no_battle(_delta(vix=14.0, spy_pct=0.5))
        assert hero == "CHAR_HERO_001"
        assert villain is None

    def test_vix_at_15_spy_positive_returns_edt(self):
        """VIX = 15 (경계값 15.9) AND SPY > 0% → CHAR_HERO_001."""
        hero, villain = select_for_no_battle(_delta(vix=15.9, spy_pct=0.1))
        assert hero == "CHAR_HERO_001"
        assert villain is None

    def test_spy_strong_up_returns_exposure(self):
        """SPY > +1.0% → CHAR_HERO_003 (Exposure Futures)."""
        hero, villain = select_for_no_battle(_delta(vix=18.0, spy_pct=1.5))
        assert hero == "CHAR_HERO_003"
        assert villain is None

    def test_spy_exactly_1pct_returns_exposure(self):
        """SPY = +1.01% → CHAR_HERO_003 (경계값)."""
        hero, villain = select_for_no_battle(_delta(vix=17.0, spy_pct=1.01))
        assert hero == "CHAR_HERO_003"
        assert villain is None

    def test_high_vix_returns_gold_bond(self):
        """VIX > 18 → CHAR_HERO_004 (Gold Bond)."""
        hero, villain = select_for_no_battle(_delta(vix=20.0, spy_pct=0.2))
        assert hero == "CHAR_HERO_004"
        assert villain is None

    def test_default_returns_iron_nuna(self):
        """VIX 17, SPY +0.5% → CHAR_HERO_002 (Iron Nuna, else 분기)."""
        hero, villain = select_for_no_battle(_delta(vix=17.0, spy_pct=0.5))
        assert hero == "CHAR_HERO_002"
        assert villain is None

    def test_villain_always_none(self):
        """NO_BATTLE은 어떤 시장 조건에서도 villain이 항상 None."""
        test_cases = [
            (10.0, 1.0),   # EDT 분기
            (15.0, 2.0),   # Exposure 분기
            (25.0, -1.0),  # Gold Bond 분기
            (17.0, 0.5),   # Iron Nuna 분기
        ]
        for vix, spy in test_cases:
            _, villain = select_for_no_battle(_delta(vix, spy))
            assert villain is None, f"VIX={vix} SPY={spy}에서 villain={villain} (None이어야 함)"

    def test_none_delta_safe(self):
        """빈 delta 입력 시 안전하게 처리."""
        hero, villain = select_for_no_battle({})
        assert hero in (
            "CHAR_HERO_001", "CHAR_HERO_002", "CHAR_HERO_003", "CHAR_HERO_004", "CHAR_HERO_005"
        )
        assert villain is None


class TestNoBattleIntegration:
    """scenario_selector × character_selector 통합 테스트."""

    def test_low_normal_is_no_battle(self):
        assert select_scenario("LOW", "NORMAL") == "NO_BATTLE"

    def test_low_intel_is_no_battle(self):
        assert select_scenario("LOW", "INTEL") == "NO_BATTLE"

    def test_no_battle_ending_tone_always_optimistic(self):
        """NO_BATTLE은 어떤 outcome/risk에서도 OPTIMISTIC."""
        outcomes = ["PEACEFUL_GROWTH", "HERO_VICTORY", "HERO_DEFEAT", "SYSTEM_COLLAPSE"]
        risks    = ["LOW", "MEDIUM", "HIGH"]
        for outcome in outcomes:
            for risk in risks:
                tone = select_ending_tone("NO_BATTLE", outcome, risk)
                assert tone == "OPTIMISTIC", (
                    f"NO_BATTLE + outcome={outcome} + risk={risk} → {tone} "
                    "(OPTIMISTIC이어야 함)"
                )

    def test_no_battle_never_ominous(self):
        """NO_BATTLE에서 OMINOUS는 절대 반환 안 됨."""
        for outcome in ["SYSTEM_COLLAPSE", "HERO_DEFEAT", "PYRRHIC_VICTORY"]:
            tone = select_ending_tone("NO_BATTLE", outcome, "HIGH")
            assert tone != "OMINOUS", (
                f"NO_BATTLE + {outcome} + HIGH → OMINOUS 반환됨 (불가)"
            )

    def test_no_battle_never_tense(self):
        """NO_BATTLE에서 TENSE는 절대 반환 안 됨."""
        for outcome in ["DRAW", "VILLAIN_TEMP_VICTORY"]:
            tone = select_ending_tone("NO_BATTLE", outcome, "HIGH")
            assert tone != "TENSE", (
                f"NO_BATTLE + {outcome} + HIGH → TENSE 반환됨 (불가)"
            )
