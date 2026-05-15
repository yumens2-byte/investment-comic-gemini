"""
Phase 2.3 G08 — crowd_momentum Battle Modifier 검증.

검증 항목:
- modifier 공식: round(crowd_momentum / 4)
- 상한 ±5 클램프 (ICG 범위 -20~+20 적응)
- Feature Flag CROWD_MODIFIER_ENABLED OFF 시 0 반환
- attenuate_crowd_momentum: 매 EP 감쇠 동작
"""
from __future__ import annotations

import pytest

from engine.arc.arc_state_engine import attenuate_crowd_momentum
from engine.narrative.battle_calc import crowd_momentum_modifier

# ── Feature Flag OFF: 항상 0 ─────────────────────────────────────────────────

@pytest.mark.parametrize("cm", [-20, -10, -5, 0, 5, 10, 20])
def test_modifier_flag_off_returns_zero(monkeypatch, cm: int) -> None:
    monkeypatch.delenv("CROWD_MODIFIER_ENABLED", raising=False)
    assert crowd_momentum_modifier(cm) == 0


# ── Feature Flag ON: 공식 검증 ───────────────────────────────────────────────

@pytest.mark.parametrize(
    "cm,expected",
    [
        (0, 0),
        (4, 1),       # 4/4 = 1
        (8, 2),       # 8/4 = 2
        (10, 2),      # round(2.5) = 2 (banker's rounding)
        (12, 3),      # 12/4 = 3
        (15, 4),      # round(3.75) = 4
        (16, 4),
        (20, 5),      # 20/4 = 5 (상한 동일)
        (-4, -1),
        (-8, -2),
        (-12, -3),
        (-20, -5),
    ],
)
def test_modifier_formula(monkeypatch, cm: int, expected: int) -> None:
    monkeypatch.setenv("CROWD_MODIFIER_ENABLED", "true")
    assert crowd_momentum_modifier(cm) == expected


# ── 상한 ±5 클램프 ────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "cm,expected",
    [
        (24, 5),      # 24/4=6 → 클램프
        (40, 5),
        (100, 5),
        (-24, -5),
        (-40, -5),
        (-100, -5),
    ],
)
def test_modifier_clamp(monkeypatch, cm: int, expected: int) -> None:
    """이론상 범위를 넘어가는 입력에도 ±5 보장."""
    monkeypatch.setenv("CROWD_MODIFIER_ENABLED", "true")
    assert crowd_momentum_modifier(cm) == expected


# ── attenuate_crowd_momentum 단위 검증 ───────────────────────────────────────

@pytest.mark.parametrize(
    "input_cm,expected",
    [
        (10, 8),      # 양수: -2
        (1, 0),       # 양수 1: 0으로
        (0, 0),       # 0 유지
        (-1, 0),      # 음수 -1: 0으로 (부호 유지하며 절댓값 감소)
        (-10, -8),    # 음수: +2
        (2, 0),
        (-2, 0),
    ],
)
def test_attenuate_default_step_2(input_cm: int, expected: int) -> None:
    assert attenuate_crowd_momentum(input_cm) == expected


def test_attenuate_custom_step() -> None:
    """step=5로 강제 감쇠."""
    assert attenuate_crowd_momentum(20, step=5) == 15
    assert attenuate_crowd_momentum(-20, step=5) == -15
    assert attenuate_crowd_momentum(3, step=5) == 0  # 부호 유지하며 0 도달


def test_attenuate_preserves_sign() -> None:
    """부호 반전 없이 0에서 멈춰야 함."""
    # 양수가 음수로 넘어가지 않음
    assert attenuate_crowd_momentum(1, step=10) == 0
    # 음수가 양수로 넘어가지 않음
    assert attenuate_crowd_momentum(-1, step=10) == 0
