"""
Phase 2.3 G05 — STEP 1.5-B (pair_tension trigger) + STEP 4-B (PR-01 가중) 검증.

검증 항목:
- STEP 1.5-B: PAIR_TENSION_ENABLED Feature Flag OFF/ON 동작
- STEP 4-B 조건 A: Draw 누적 → CONFLICT
- STEP 4-B 조건 B: pair_trigger_flag True → CONFLICT
- A+B 중복 충족: 최대 1회만 CONFLICT 격상 (중복 누적 금지)
- REVERSAL_DOWN + CONFLICT 충돌: arc_tension >= 70 → BATTLE 우선
- Feature Flag OFF 시 v1.4 동작 유지
"""
from __future__ import annotations

import pytest

from engine.narrative.episode_type_engine import (
    _step1_5_b_pair_tension,
    _step4_dss_correction,
    determine_episode_type,
)


# ── _step1_5_b_pair_tension Feature Flag ─────────────────────────────────────

def test_step15b_feature_flag_off_returns_false(monkeypatch) -> None:
    """PAIR_TENSION_ENABLED OFF → (False, None) 보장."""
    monkeypatch.delenv("PAIR_TENSION_ENABLED", raising=False)
    state = {"pair_tension": {"PAIR_A": 90, "PAIR_B": 0, "PAIR_C": 0}}
    flag, pair = _step1_5_b_pair_tension(state)
    assert flag is False
    assert pair is None


def test_step15b_feature_flag_on_triggers(monkeypatch) -> None:
    monkeypatch.setenv("PAIR_TENSION_ENABLED", "true")
    state = {
        "pair_tension": {"PAIR_A": 80, "PAIR_B": 0, "PAIR_C": 0},
        "zero_block_just_appeared": False,
    }
    flag, pair = _step1_5_b_pair_tension(state)
    assert flag is True
    assert pair == "PAIR_A"


def test_step15b_below_threshold_no_trigger(monkeypatch) -> None:
    monkeypatch.setenv("PAIR_TENSION_ENABLED", "true")
    state = {
        "pair_tension": {"PAIR_A": 60, "PAIR_B": 60, "PAIR_C": 60},
        "zero_block_just_appeared": False,
    }
    flag, pair = _step1_5_b_pair_tension(state)
    assert flag is False
    assert pair is None


# ── STEP 4 조건 A (Draw 누적) ─────────────────────────────────────────────────

def test_step4_condition_a_draw_streak() -> None:
    """최근 2회 Draw + arc_day>=4 + 50<=tension<80 → CONFLICT."""
    result = _step4_dss_correction(
        base_type="STALEMATE",
        dss_score=40,
        arc_day=5,
        arc_tension=60,
        reversal_state="NONE",
        recent_outcomes=["DRAW", "DRAW"],
        act_phase="ACT_2",
        pair_trigger_flag=False,
    )
    assert result == "CONFLICT"


def test_step4_condition_a_only_one_draw_no_trigger() -> None:
    """Draw 1회만 → CONFLICT 조건 미충족."""
    result = _step4_dss_correction(
        base_type="STALEMATE",
        dss_score=40,
        arc_day=5,
        arc_tension=60,
        reversal_state="NONE",
        recent_outcomes=["DRAW", "HERO_VICTORY"],
        act_phase="ACT_2",
        pair_trigger_flag=False,
    )
    assert result == "STALEMATE"  # 변경 없음


# ── STEP 4 조건 B (PR-01 pair_trigger) ───────────────────────────────────────

def test_step4_condition_b_pair_trigger_only() -> None:
    """조건 A 미충족, 조건 B만 True → CONFLICT."""
    result = _step4_dss_correction(
        base_type="STALEMATE",
        dss_score=40,
        arc_day=3,           # arc_day < 4: 조건 A 불가
        arc_tension=40,      # tension < 50: 조건 A 불가
        reversal_state="NONE",
        recent_outcomes=["HERO_VICTORY", "HERO_VICTORY"],
        act_phase="ACT_1",
        pair_trigger_flag=True,
        triggered_pair="PAIR_A",
    )
    assert result == "CONFLICT"


# ── STEP 4 조건 A+B 동시 충족: 중복 격상 금지 ────────────────────────────────

def test_step4_a_and_b_both_true_single_conflict() -> None:
    """A+B 모두 True여도 CONFLICT는 1회만 적용 (이중 누적 없음)."""
    result = _step4_dss_correction(
        base_type="STALEMATE",
        dss_score=40,
        arc_day=5,
        arc_tension=60,
        reversal_state="NONE",
        recent_outcomes=["DRAW", "DRAW"],   # 조건 A True
        act_phase="ACT_2",
        pair_trigger_flag=True,              # 조건 B True
        triggered_pair="PAIR_A",
    )
    # CONFLICT가 한 번만 적용되고, 이중으로 다른 타입으로 가지 않음
    assert result == "CONFLICT"


# ── STEP 4 REVERSAL_DOWN + CONFLICT 충돌 ─────────────────────────────────────

def test_step4_reversal_down_plus_conflict_high_tension_battle_priority() -> None:
    """
    REVERSAL_DOWN + CONFLICT 동시 충돌 + arc_tension>=70 → BATTLE 우선.
    """
    result = _step4_dss_correction(
        base_type="TACTICAL",
        dss_score=40,
        arc_day=5,
        arc_tension=70,        # >= 70
        reversal_state="REVERSAL_DOWN",
        recent_outcomes=["DRAW", "DRAW"],
        act_phase="ACT_2",
        pair_trigger_flag=True,
        triggered_pair="PAIR_A",
    )
    assert result == "BATTLE"


def test_step4_reversal_down_conflict_low_tension_conflict() -> None:
    """
    REVERSAL_DOWN + 조건B True + arc_tension < 70 → CONFLICT.
    arc_tension < 70이면 BATTLE 우선 분기 미동작.
    조건 A는 50<=tension<80 + arc_day>=4 + Draw 2회 필요 → 미충족.
    조건 B만 True.
    """
    result = _step4_dss_correction(
        base_type="TACTICAL",
        dss_score=40,
        arc_day=5,
        arc_tension=40,            # < 70 (조건 A의 50도 미충족)
        reversal_state="REVERSAL_DOWN",
        recent_outcomes=["HERO_VICTORY", "HERO_VICTORY"],
        act_phase="ACT_2",
        pair_trigger_flag=True,
        triggered_pair="PAIR_A",
    )
    # REVERSAL_DOWN의 TACTICAL→BATTLE 보정 후, 조건 B로 CONFLICT 격상
    assert result == "CONFLICT"


# ── STEP 4 REVERSAL_UP은 PR-01과 무관 (정상 동작) ────────────────────────────

def test_step4_reversal_up_no_pair_trigger_tactical() -> None:
    result = _step4_dss_correction(
        base_type="BATTLE",
        dss_score=40,
        arc_day=3,
        arc_tension=40,
        reversal_state="REVERSAL_UP",
        recent_outcomes=[],
        act_phase="ACT_1",
        pair_trigger_flag=False,
    )
    assert result == "TACTICAL"


# ── determine_episode_type 통합: PAIR_TENSION_ENABLED OFF 백워드 호환 ──────

def test_determine_pair_tension_off_no_conflict_when_only_pair_trigger(
    monkeypatch,
) -> None:
    """
    Feature Flag OFF면 pair_tension이 90이어도 STEP 4-B 조건 B 비활성 → CONFLICT 발동 안 함.
    """
    monkeypatch.delenv("PAIR_TENSION_ENABLED", raising=False)
    monkeypatch.delenv("EPISODE_TYPE_ENGINE_ENABLED", raising=False)
    arc_state = {
        "arc_day": 3,
        "arc_tension": 40,
        "form3_activated": False,
        "form2_available": False,
        "pair_tension": {"PAIR_A": 90, "PAIR_B": 0, "PAIR_C": 0},
        "zero_block_just_appeared": False,
    }
    delta = {"reversal_state": "NONE"}
    result = determine_episode_type(arc_state, delta, risk_level="MEDIUM")
    # arc_day=3 → base TACTICAL
    assert result.episode_type == "TACTICAL"
    assert result.pair_trigger_flag is False
    assert result.triggered_pair is None


def test_determine_pair_tension_on_triggers_conflict(monkeypatch) -> None:
    """
    Feature Flag ON + pair_tension >= 70 → STEP 4-B 조건 B로 CONFLICT.
    """
    monkeypatch.setenv("PAIR_TENSION_ENABLED", "true")
    arc_state = {
        "arc_day": 3,
        "arc_tension": 40,
        "form3_activated": False,
        "form2_available": False,
        "pair_tension": {"PAIR_A": 90, "PAIR_B": 0, "PAIR_C": 0},
        "zero_block_just_appeared": False,
    }
    delta = {"reversal_state": "NONE"}
    result = determine_episode_type(arc_state, delta, risk_level="MEDIUM")
    assert result.episode_type == "CONFLICT"
    assert result.pair_trigger_flag is True
    assert result.triggered_pair == "PAIR_A"


def test_determine_pair_tension_on_but_below_threshold(monkeypatch) -> None:
    """ON이어도 임계 미만이면 트리거 안 됨."""
    monkeypatch.setenv("PAIR_TENSION_ENABLED", "true")
    arc_state = {
        "arc_day": 3,
        "arc_tension": 40,
        "form3_activated": False,
        "form2_available": False,
        "pair_tension": {"PAIR_A": 60, "PAIR_B": 60, "PAIR_C": 60},
        "zero_block_just_appeared": False,
    }
    delta = {"reversal_state": "NONE"}
    result = determine_episode_type(arc_state, delta, risk_level="MEDIUM")
    # arc_day=3 → TACTICAL 유지
    assert result.episode_type == "TACTICAL"
    assert result.pair_trigger_flag is False
