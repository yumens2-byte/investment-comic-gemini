"""tests/test_battle_alliance.py
ALLIANCE 전투 계산 + PYRRHIC_VICTORY 경계값 전수 검증
"""
from engine.narrative.battle_calc import resolve_alliance_outcome


class TestResolveAllianceOutcome:
    """balance 경계값 테스트."""

    # ── 압도적 완승 ────────────────────────────────────────────────────────────
    def test_hero_victory_at_30(self):
        assert resolve_alliance_outcome(30) == "HERO_VICTORY"

    def test_hero_victory_above_30(self):
        assert resolve_alliance_outcome(50) == "HERO_VICTORY"
        assert resolve_alliance_outcome(100) == "HERO_VICTORY"

    # ── PYRRHIC_VICTORY 범위 (10~29) ─────────────────────────────────────────
    def test_pyrrhic_at_29(self):
        assert resolve_alliance_outcome(29) == "PYRRHIC_VICTORY"

    def test_pyrrhic_at_15(self):
        assert resolve_alliance_outcome(15) == "PYRRHIC_VICTORY"

    def test_pyrrhic_at_10(self):
        assert resolve_alliance_outcome(10) == "PYRRHIC_VICTORY"

    # ── DRAW 범위 (-5~9) ──────────────────────────────────────────────────────
    def test_draw_at_9(self):
        assert resolve_alliance_outcome(9) == "DRAW"

    def test_draw_at_0(self):
        assert resolve_alliance_outcome(0) == "DRAW"

    def test_draw_at_minus5(self):
        assert resolve_alliance_outcome(-5) == "DRAW"

    # ── VILLAIN_TEMP_VICTORY 범위 (-10~-6) ────────────────────────────────────
    def test_villain_at_minus6(self):
        assert resolve_alliance_outcome(-6) == "VILLAIN_TEMP_VICTORY"

    def test_villain_at_minus10(self):
        assert resolve_alliance_outcome(-10) == "VILLAIN_TEMP_VICTORY"

    # ── HERO_DEFEAT 범위 (-30~-11) ────────────────────────────────────────────
    def test_defeat_at_minus11(self):
        assert resolve_alliance_outcome(-11) == "HERO_DEFEAT"

    def test_defeat_at_minus30(self):
        assert resolve_alliance_outcome(-30) == "HERO_DEFEAT"

    # ── SYSTEM_COLLAPSE (<= -31) ──────────────────────────────────────────────
    def test_collapse_at_minus31(self):
        assert resolve_alliance_outcome(-31) == "SYSTEM_COLLAPSE"

    def test_collapse_deep(self):
        assert resolve_alliance_outcome(-100) == "SYSTEM_COLLAPSE"

    # ── 핵심: HERO_TACTICAL_VICTORY는 절대 반환 안 됨 ─────────────────────────
    def test_no_tactical_victory_in_alliance(self):
        """ALLIANCE에서 HERO_TACTICAL_VICTORY는 절대 반환되지 않아야 한다."""
        for b in range(-100, 101):
            result = resolve_alliance_outcome(b)
            assert result != "HERO_TACTICAL_VICTORY", (
                f"balance={b}에서 HERO_TACTICAL_VICTORY 반환됨 — "
                "ALLIANCE에서는 PYRRHIC_VICTORY여야 함"
            )
