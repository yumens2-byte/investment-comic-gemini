"""
Phase 2.3 G09 — Villain Signature Bonus + EMERGENCE Information Deficit 검증.

검증 항목:
- villain_signature_bonus 테이블 매핑 (Lv1:0/Lv2:+8/Lv3:+18)
- emergence_information_deficit:
    * EMERGENCE 당일: -10
    * deficit_days >= 2: -10
    * deficit_days == 1: -5
    * 그 외: 0
- emergence_outcome_demotion: balance 격하 동작
- Feature Flag VILLAIN_SIGNATURE_BONUS_ENABLED / EMERGENCE_DEFICIT_ENABLED
- apply_v23_modifiers: BattleResult 후처리 통합
- update_emergence_deficit days 전이 (EMERGENCE 발행 → 2 → 1 → 0)
"""
from __future__ import annotations

import pytest

from engine.arc.arc_state_engine import (
    get_emergence_deficit_modifier,
    update_emergence_deficit,
)
from engine.narrative.battle_calc import (
    BattleResult,
    apply_v23_modifiers,
    emergence_information_deficit,
    emergence_outcome_demotion,
    villain_signature_bonus,
)


# ════════════════════════════════════════════════════════════════════════════
# Villain Signature Bonus
# ════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("level", [1, 2, 3])
def test_villain_signature_flag_off(monkeypatch, level: int) -> None:
    monkeypatch.delenv("VILLAIN_SIGNATURE_BONUS_ENABLED", raising=False)
    assert villain_signature_bonus(level) == 0


@pytest.mark.parametrize(
    "level,expected",
    [
        (1, 0),
        (2, 8),
        (3, 18),
        (0, 0),     # 비정상 입력 fallback
        (99, 0),    # 정의되지 않은 레벨 → 0
    ],
)
def test_villain_signature_flag_on_table(
    monkeypatch, level: int, expected: int
) -> None:
    monkeypatch.setenv("VILLAIN_SIGNATURE_BONUS_ENABLED", "true")
    assert villain_signature_bonus(level) == expected


# ════════════════════════════════════════════════════════════════════════════
# EMERGENCE Information Deficit
# ════════════════════════════════════════════════════════════════════════════

def test_emergence_deficit_flag_off(monkeypatch) -> None:
    monkeypatch.delenv("EMERGENCE_DEFICIT_ENABLED", raising=False)
    arc_ctx = {"emergence_deficit_days": 2}
    assert emergence_information_deficit(arc_ctx, "EMERGENCE") == 0


def test_emergence_deficit_day_of_emergence(monkeypatch) -> None:
    monkeypatch.setenv("EMERGENCE_DEFICIT_ENABLED", "true")
    arc_ctx = {"emergence_deficit_days": 0}
    assert emergence_information_deficit(arc_ctx, "EMERGENCE") == -10


def test_emergence_deficit_days_2_residual(monkeypatch) -> None:
    monkeypatch.setenv("EMERGENCE_DEFICIT_ENABLED", "true")
    arc_ctx = {"emergence_deficit_days": 2}
    assert emergence_information_deficit(arc_ctx, "BATTLE") == -10


def test_emergence_deficit_days_1_residual(monkeypatch) -> None:
    monkeypatch.setenv("EMERGENCE_DEFICIT_ENABLED", "true")
    arc_ctx = {"emergence_deficit_days": 1}
    assert emergence_information_deficit(arc_ctx, "BATTLE") == -5


def test_emergence_deficit_days_0_no_effect(monkeypatch) -> None:
    monkeypatch.setenv("EMERGENCE_DEFICIT_ENABLED", "true")
    arc_ctx = {"emergence_deficit_days": 0}
    assert emergence_information_deficit(arc_ctx, "BATTLE") == 0


def test_emergence_deficit_missing_key(monkeypatch) -> None:
    monkeypatch.setenv("EMERGENCE_DEFICIT_ENABLED", "true")
    assert emergence_information_deficit({}, "BATTLE") == 0


# ════════════════════════════════════════════════════════════════════════════
# EMR-02 OUTCOME Demotion
# ════════════════════════════════════════════════════════════════════════════

def test_demotion_flag_off(monkeypatch) -> None:
    monkeypatch.delenv("EMERGENCE_DEFICIT_ENABLED", raising=False)
    assert emergence_outcome_demotion(50, "EMERGENCE") == (50, "")


def test_demotion_victory_to_tactical(monkeypatch) -> None:
    """Balance 50 (Victory) → 29 (Tactical)."""
    monkeypatch.setenv("EMERGENCE_DEFICIT_ENABLED", "true")
    balance, reason = emergence_outcome_demotion(50, "EMERGENCE")
    assert balance == 29
    assert "EMR-02" in reason


def test_demotion_tactical_to_draw(monkeypatch) -> None:
    """Balance 15 (Tactical) → 9 (Draw)."""
    monkeypatch.setenv("EMERGENCE_DEFICIT_ENABLED", "true")
    balance, reason = emergence_outcome_demotion(15, "EMERGENCE")
    assert balance == 9


def test_demotion_draw_to_defeat(monkeypatch) -> None:
    """Balance 0 (Draw) → -11 (Defeat)."""
    monkeypatch.setenv("EMERGENCE_DEFICIT_ENABLED", "true")
    balance, reason = emergence_outcome_demotion(0, "EMERGENCE")
    assert balance == -11


def test_demotion_already_defeat_no_change(monkeypatch) -> None:
    """Balance -20 (Defeat 이하) → 변경 없음."""
    monkeypatch.setenv("EMERGENCE_DEFICIT_ENABLED", "true")
    balance, reason = emergence_outcome_demotion(-20, "EMERGENCE")
    assert balance == -20
    assert reason == ""


def test_demotion_non_emergence_no_change(monkeypatch) -> None:
    """EMERGENCE 아닌 타입에는 무영향."""
    monkeypatch.setenv("EMERGENCE_DEFICIT_ENABLED", "true")
    balance, reason = emergence_outcome_demotion(50, "BATTLE")
    assert balance == 50
    assert reason == ""


# ════════════════════════════════════════════════════════════════════════════
# update_emergence_deficit days 전이
# ════════════════════════════════════════════════════════════════════════════

def test_update_deficit_emergence_sets_2() -> None:
    """EMERGENCE 발행 후 days = 2."""
    state = {"emergence_deficit_days": 0}
    new_state = update_emergence_deficit(state, "EMERGENCE")
    assert new_state["emergence_deficit_days"] == 2


def test_update_deficit_decrement() -> None:
    """매 EP -1."""
    state = {"emergence_deficit_days": 2}
    new_state = update_emergence_deficit(state, "BATTLE")
    assert new_state["emergence_deficit_days"] == 1
    new_state2 = update_emergence_deficit(new_state, "BATTLE")
    assert new_state2["emergence_deficit_days"] == 0


def test_update_deficit_floor_at_0() -> None:
    state = {"emergence_deficit_days": 0}
    new_state = update_emergence_deficit(state, "BATTLE")
    assert new_state["emergence_deficit_days"] == 0


# ── get_emergence_deficit_modifier 사이드 (state 기반) ──────────────────────

def test_get_modifier_state_based_flag_off(monkeypatch) -> None:
    monkeypatch.delenv("EMERGENCE_DEFICIT_ENABLED", raising=False)
    assert get_emergence_deficit_modifier({"emergence_deficit_days": 2}, "BATTLE") == 0


def test_get_modifier_state_based_emergence_day(monkeypatch) -> None:
    monkeypatch.setenv("EMERGENCE_DEFICIT_ENABLED", "true")
    assert get_emergence_deficit_modifier({"emergence_deficit_days": 0}, "EMERGENCE") == -10


def test_get_modifier_state_based_days_1(monkeypatch) -> None:
    monkeypatch.setenv("EMERGENCE_DEFICIT_ENABLED", "true")
    assert get_emergence_deficit_modifier({"emergence_deficit_days": 1}, "BATTLE") == -5


# ════════════════════════════════════════════════════════════════════════════
# apply_v23_modifiers 통합
# ════════════════════════════════════════════════════════════════════════════

def _make_battle_result(
    hero_power: int = 100,
    villain_power: int = 90,
    outcome: str = "HERO_VICTORY",
) -> BattleResult:
    return BattleResult(
        hero_id="CHAR_HERO_001",
        villain_id="CHAR_VILLAIN_002",
        hero_power=hero_power,
        villain_power=villain_power,
        balance=hero_power - villain_power,
        outcome=outcome,
        hero_power_breakdown={"base": hero_power},
        villain_power_breakdown={"base": villain_power},
    )


def test_apply_v23_all_flags_off_returns_input(monkeypatch) -> None:
    """모든 Flag OFF → 입력 그대로 반환."""
    monkeypatch.delenv("CROWD_MODIFIER_ENABLED", raising=False)
    monkeypatch.delenv("VILLAIN_SIGNATURE_BONUS_ENABLED", raising=False)
    monkeypatch.delenv("EMERGENCE_DEFICIT_ENABLED", raising=False)
    original = _make_battle_result()
    arc_ctx = {"villain_signature": 3, "crowd_momentum": 20, "emergence_deficit_days": 2}
    result = apply_v23_modifiers(original, arc_ctx, "BATTLE")
    assert result is original  # 동일 객체


def test_apply_v23_villain_signature_only(monkeypatch) -> None:
    """VS Bonus만 활성: villain_power +18 (Lv.3)."""
    monkeypatch.setenv("VILLAIN_SIGNATURE_BONUS_ENABLED", "true")
    monkeypatch.delenv("CROWD_MODIFIER_ENABLED", raising=False)
    monkeypatch.delenv("EMERGENCE_DEFICIT_ENABLED", raising=False)
    original = _make_battle_result(hero_power=100, villain_power=90)
    arc_ctx = {"villain_signature": 3, "crowd_momentum": 0, "emergence_deficit_days": 0}
    result = apply_v23_modifiers(original, arc_ctx, "BATTLE")
    assert result.villain_power == 108
    assert result.balance == 100 - 108
    assert result.hero_power == 100


def test_apply_v23_crowd_modifier_only(monkeypatch) -> None:
    """crowd_momentum=12 → +3, hero_power +3."""
    monkeypatch.setenv("CROWD_MODIFIER_ENABLED", "true")
    monkeypatch.delenv("VILLAIN_SIGNATURE_BONUS_ENABLED", raising=False)
    monkeypatch.delenv("EMERGENCE_DEFICIT_ENABLED", raising=False)
    original = _make_battle_result(hero_power=100, villain_power=90)
    arc_ctx = {"villain_signature": 1, "crowd_momentum": 12, "emergence_deficit_days": 0}
    result = apply_v23_modifiers(original, arc_ctx, "BATTLE")
    assert result.hero_power == 103
    assert result.balance == 13


def test_apply_v23_emergence_deficit_only(monkeypatch) -> None:
    """EMERGENCE 당일 → hero_power -10."""
    monkeypatch.setenv("EMERGENCE_DEFICIT_ENABLED", "true")
    monkeypatch.delenv("CROWD_MODIFIER_ENABLED", raising=False)
    monkeypatch.delenv("VILLAIN_SIGNATURE_BONUS_ENABLED", raising=False)
    original = _make_battle_result(hero_power=100, villain_power=90)
    arc_ctx = {"villain_signature": 1, "crowd_momentum": 0, "emergence_deficit_days": 0}
    result = apply_v23_modifiers(original, arc_ctx, "EMERGENCE")
    # hero_power 100 - 10 = 90
    assert result.hero_power == 90
    # balance 0 → emergence_outcome_demotion 격하 (0 → -11)
    # 0 >= -4 이므로 격하: Draw → Defeat (balance -11)
    assert result.balance == -11


def test_apply_v23_full_stack(monkeypatch) -> None:
    """모든 Flag ON 통합: VS Bonus + crowd_modifier + EMERGENCE deficit."""
    monkeypatch.setenv("VILLAIN_SIGNATURE_BONUS_ENABLED", "true")
    monkeypatch.setenv("CROWD_MODIFIER_ENABLED", "true")
    monkeypatch.setenv("EMERGENCE_DEFICIT_ENABLED", "true")
    original = _make_battle_result(hero_power=100, villain_power=90)
    arc_ctx = {"villain_signature": 2, "crowd_momentum": 8, "emergence_deficit_days": 0}
    result = apply_v23_modifiers(original, arc_ctx, "BATTLE")
    # villain_power +8 (Lv.2), hero_power +2 (crowd=8/4=2), no EMERGENCE deficit
    assert result.villain_power == 98
    assert result.hero_power == 102
    assert result.balance == 4


def test_apply_v23_peaceful_growth_preserved(monkeypatch) -> None:
    """PEACEFUL_GROWTH outcome은 modifier 적용해도 outcome 유지."""
    monkeypatch.setenv("CROWD_MODIFIER_ENABLED", "true")
    original = BattleResult(
        hero_id="CHAR_HERO_001",
        villain_id="CHAR_VILLAIN_002",
        hero_power=0,
        villain_power=0,
        balance=0,
        outcome="PEACEFUL_GROWTH",
        hero_power_breakdown={},
        villain_power_breakdown={},
    )
    arc_ctx = {"villain_signature": 1, "crowd_momentum": 12, "emergence_deficit_days": 0}
    result = apply_v23_modifiers(original, arc_ctx, "STALEMATE")
    assert result.outcome == "PEACEFUL_GROWTH"
