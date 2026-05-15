"""
Phase 2.3 G03 — pair_tension / edt_pressure / get_relevant_pair / 동률 선택 검증.

검증 항목:
- calc_edt_pressure: 가중합 공식 (PAIR_A*1.0 + PAIR_B*0.5 + PAIR_C*0.3)
- clamp_pair_value: 0~100 클램프
- get_pair_for_character: 캐릭터 → 페어 매핑
- get_relevant_pair: 양 캐릭터 모두 등장 시에만 페어 인정, 우선순위 A>B>C
- _select_highest_pair_over_threshold: 최고값 + 동률 시 A>B>C 우선
- check_pair_tension_trigger: STEP 1.5-B용
- update_pair_tension: PR-03/04/05/06 통합 (Draw/Defeat/Form2/Zero Block/CONFLICT/AFTERMATH/VillainDefeated)
- Feature Flag OFF 동작
"""
from __future__ import annotations

import pytest

from engine.arc.arc_state_engine import (
    EDT_PRESSURE_FORM3_BONUS_THRESHOLD,
    _select_highest_pair_over_threshold,
    calc_edt_pressure,
    check_pair_tension_trigger,
    clamp_pair_value,
    get_pair_for_character,
    get_relevant_pair,
    is_pair_tension_enabled,
    update_pair_tension,
)

# ── calc_edt_pressure 공식 ────────────────────────────────────────────────────

def test_edt_pressure_zero() -> None:
    assert calc_edt_pressure({"PAIR_A": 0, "PAIR_B": 0, "PAIR_C": 0}) == 0.0


def test_edt_pressure_max() -> None:
    """이론적 최대값: 100 + 50 + 30 = 180.0"""
    pt = {"PAIR_A": 100, "PAIR_B": 100, "PAIR_C": 100}
    assert calc_edt_pressure(pt) == 180.0


def test_edt_pressure_weights() -> None:
    """PAIR_A=10, B=20, C=30 → 10*1.0 + 20*0.5 + 30*0.3 = 29.0"""
    pt = {"PAIR_A": 10, "PAIR_B": 20, "PAIR_C": 30}
    assert calc_edt_pressure(pt) == 29.0


def test_edt_pressure_form3_threshold_realistic() -> None:
    """PAIR_A=80, B=60, C=40 → 80 + 30 + 12 = 122 (< 150)"""
    pt = {"PAIR_A": 80, "PAIR_B": 60, "PAIR_C": 40}
    assert calc_edt_pressure(pt) == 122.0
    assert calc_edt_pressure(pt) < EDT_PRESSURE_FORM3_BONUS_THRESHOLD


def test_edt_pressure_invalid_input() -> None:
    """dict가 아니면 0.0 반환 (방어 코드)."""
    assert calc_edt_pressure(None) == 0.0  # type: ignore[arg-type]
    assert calc_edt_pressure("invalid") == 0.0  # type: ignore[arg-type]


# ── clamp_pair_value ──────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "input_val,expected",
    [
        (-5, 0),       # 음수 → 0
        (0, 0),
        (50, 50),
        (100, 100),
        (150, 100),    # 초과 → 100
        (99.7, 99),    # float → int 변환 (truncation)
    ],
)
def test_clamp_pair_value(input_val: float, expected: int) -> None:
    assert clamp_pair_value(input_val) == expected


# ── get_pair_for_character ────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "char_id,expected",
    [
        ("CHAR_HERO_001", "PAIR_A"),  # EDT
        ("CHAR_HERO_003", "PAIR_A"),  # Leverage
        ("CHAR_HERO_002", "PAIR_B"),  # Iron Nuna
        ("CHAR_HERO_004", "PAIR_B"),  # Futures Girl
        ("CHAR_HERO_005", "PAIR_C"),  # Gold Bond
        ("UNKNOWN", None),
    ],
)
def test_get_pair_for_character(char_id: str, expected: str | None) -> None:
    assert get_pair_for_character(char_id) == expected


# ── get_relevant_pair: 양 캐릭터 모두 등장만 인정 ─────────────────────────────

def test_relevant_pair_solo_edt() -> None:
    """EDT 단독 등장 → PAIR_A 양쪽 모두 등장하지 않으므로 None."""
    assert get_relevant_pair(["CHAR_HERO_001"]) is None


def test_relevant_pair_full_pair_a() -> None:
    """EDT + Leverage 함께 → PAIR_A."""
    assert get_relevant_pair(["CHAR_HERO_001", "CHAR_HERO_003"]) == "PAIR_A"


def test_relevant_pair_full_pair_b() -> None:
    assert get_relevant_pair(["CHAR_HERO_002", "CHAR_HERO_004"]) == "PAIR_B"


def test_relevant_pair_priority_a_over_b() -> None:
    """A와 B 모두 양쪽 등장 시 PAIR_A 우선."""
    heroes = [
        "CHAR_HERO_001", "CHAR_HERO_003",  # PAIR_A
        "CHAR_HERO_002", "CHAR_HERO_004",  # PAIR_B
    ]
    assert get_relevant_pair(heroes) == "PAIR_A"


def test_relevant_pair_one_member_only() -> None:
    """페어 1명만 있으면 인정 안 함."""
    assert get_relevant_pair(["CHAR_HERO_005"]) is None  # Gold Bond만, Zero Block 미정의


# ── _select_highest_pair_over_threshold: 동률 A>B>C ──────────────────────────

def test_select_highest_all_below() -> None:
    pt = {"PAIR_A": 50, "PAIR_B": 50, "PAIR_C": 50}
    # 임계값 70 미만 → None
    assert _select_highest_pair_over_threshold(pt) is None


def test_select_highest_single() -> None:
    pt = {"PAIR_A": 30, "PAIR_B": 80, "PAIR_C": 50}
    assert _select_highest_pair_over_threshold(pt) == "PAIR_B"


def test_select_highest_tie_prefers_a() -> None:
    """동률 시 A > B > C."""
    pt = {"PAIR_A": 75, "PAIR_B": 75, "PAIR_C": 75}
    assert _select_highest_pair_over_threshold(pt) == "PAIR_A"


def test_select_highest_tie_b_over_c() -> None:
    pt = {"PAIR_A": 30, "PAIR_B": 80, "PAIR_C": 80}
    assert _select_highest_pair_over_threshold(pt) == "PAIR_B"


def test_select_highest_boundary_exact_70() -> None:
    """경계값: 정확히 70은 트리거."""
    pt = {"PAIR_A": 70, "PAIR_B": 0, "PAIR_C": 0}
    assert _select_highest_pair_over_threshold(pt) == "PAIR_A"


def test_select_highest_just_under_threshold() -> None:
    pt = {"PAIR_A": 69, "PAIR_B": 69, "PAIR_C": 69}
    assert _select_highest_pair_over_threshold(pt) is None


# ── check_pair_tension_trigger: Zero Block 당일 PAIR_C 제외 ──────────────────

def test_pair_tension_trigger_basic() -> None:
    state = {
        "pair_tension": {"PAIR_A": 75, "PAIR_B": 0, "PAIR_C": 0},
        "zero_block_just_appeared": False,
    }
    flag, pair = check_pair_tension_trigger(state)
    assert flag is True
    assert pair == "PAIR_A"


def test_pair_tension_trigger_zero_block_just_appeared_excludes_c() -> None:
    """Zero Block 등장 당일 PAIR_C는 평가에서 제외."""
    state = {
        "pair_tension": {"PAIR_A": 0, "PAIR_B": 0, "PAIR_C": 80},
        "zero_block_just_appeared": True,
    }
    flag, pair = check_pair_tension_trigger(state)
    assert flag is False
    assert pair is None


def test_pair_tension_trigger_zero_block_other_pair_still_works() -> None:
    """Zero Block 당일이어도 PAIR_A/B 트리거는 작동."""
    state = {
        "pair_tension": {"PAIR_A": 80, "PAIR_B": 0, "PAIR_C": 90},
        "zero_block_just_appeared": True,
    }
    flag, pair = check_pair_tension_trigger(state)
    assert flag is True
    assert pair == "PAIR_A"


def test_pair_tension_trigger_no_pair_tension_field() -> None:
    """pair_tension 필드 자체가 없으면 False."""
    flag, pair = check_pair_tension_trigger({})
    assert flag is False
    assert pair is None


# ── update_pair_tension: PR-03 Draw → +5 ──────────────────────────────────────

def _base_state() -> dict:
    return {
        "pair_tension": {"PAIR_A": 0, "PAIR_B": 0, "PAIR_C": 0},
        "edt_pressure": 0.0,
    }


def test_update_pr03_draw_pair_a() -> None:
    state = _base_state()
    new_state = update_pair_tension(
        state,
        outcome="DRAW",
        episode_type="BATTLE",
        hero_ids=["CHAR_HERO_001", "CHAR_HERO_003"],
    )
    assert new_state["pair_tension"]["PAIR_A"] == 5
    # edt_pressure 자동 갱신 검증
    assert new_state["edt_pressure"] == 5.0


def test_update_pr03_defeat_pair_b() -> None:
    state = _base_state()
    new_state = update_pair_tension(
        state,
        outcome="HERO_DEFEAT",
        episode_type="BATTLE",
        hero_ids=["CHAR_HERO_002", "CHAR_HERO_004"],
    )
    assert new_state["pair_tension"]["PAIR_B"] == 10
    assert new_state["edt_pressure"] == 5.0  # 10 * 0.5


def test_update_pr03_form2_pair_a_only() -> None:
    """Form 2 → PAIR_A +20 (관련 페어 아니어도)."""
    state = _base_state()
    new_state = update_pair_tension(
        state,
        outcome="HERO_VICTORY",
        episode_type="BATTLE",
        hero_ids=["CHAR_HERO_001"],  # solo
        form_triggered=2,
    )
    assert new_state["pair_tension"]["PAIR_A"] == 20


def test_update_pr03_zero_block_pair_c_plus_30() -> None:
    state = _base_state()
    new_state = update_pair_tension(
        state,
        outcome="HERO_VICTORY",
        episode_type="BATTLE",
        hero_ids=["CHAR_HERO_001"],
        zero_block_appeared=True,
    )
    assert new_state["pair_tension"]["PAIR_C"] == 30
    assert new_state["zero_block_just_appeared"] is True


def test_update_pr04_conflict_minus_30() -> None:
    """CONFLICT 발행 → 임계 이상 페어 -30."""
    state = {
        "pair_tension": {"PAIR_A": 75, "PAIR_B": 0, "PAIR_C": 0},
        "edt_pressure": 75.0,
    }
    new_state = update_pair_tension(
        state,
        outcome="DRAW",
        episode_type="CONFLICT",
        hero_ids=["CHAR_HERO_001", "CHAR_HERO_003"],
    )
    assert new_state["pair_tension"]["PAIR_A"] == 45  # 75-30
    # CONFLICT 분기에서 PR-03 Draw는 적용 안 됨 (else 분기)


def test_update_pr05_aftermath_minus_10_all() -> None:
    """AFTERMATH → 모든 페어 -10."""
    state = {
        "pair_tension": {"PAIR_A": 50, "PAIR_B": 40, "PAIR_C": 30},
        "edt_pressure": 0.0,
    }
    new_state = update_pair_tension(
        state,
        outcome="DRAW",
        episode_type="AFTERMATH",
        hero_ids=["CHAR_HERO_001"],
    )
    assert new_state["pair_tension"]["PAIR_A"] == 40
    assert new_state["pair_tension"]["PAIR_B"] == 30
    assert new_state["pair_tension"]["PAIR_C"] == 20


def test_update_pr06_villain_defeated_minus_15() -> None:
    state = {
        "pair_tension": {"PAIR_A": 50, "PAIR_B": 40, "PAIR_C": 30},
        "edt_pressure": 0.0,
    }
    new_state = update_pair_tension(
        state,
        outcome="HERO_VICTORY",
        episode_type="BATTLE",
        hero_ids=["CHAR_HERO_001"],
        villain_defeated=True,
    )
    assert new_state["pair_tension"]["PAIR_A"] == 35
    assert new_state["pair_tension"]["PAIR_B"] == 25
    assert new_state["pair_tension"]["PAIR_C"] == 15


def test_update_clamp_at_100() -> None:
    """PR-03 누적 시 100 클램프."""
    state = {
        "pair_tension": {"PAIR_A": 95, "PAIR_B": 0, "PAIR_C": 0},
        "edt_pressure": 0.0,
    }
    new_state = update_pair_tension(
        state,
        outcome="HERO_VICTORY",
        episode_type="BATTLE",
        hero_ids=["CHAR_HERO_001"],
        form_triggered=2,  # +20
    )
    assert new_state["pair_tension"]["PAIR_A"] == 100  # 95+20 클램프


def test_update_clamp_at_0() -> None:
    """AFTERMATH 음수 → 0 클램프."""
    state = {
        "pair_tension": {"PAIR_A": 5, "PAIR_B": 0, "PAIR_C": 0},
        "edt_pressure": 0.0,
    }
    new_state = update_pair_tension(
        state,
        outcome="DRAW",
        episode_type="AFTERMATH",
        hero_ids=["CHAR_HERO_001"],
    )
    assert new_state["pair_tension"]["PAIR_A"] == 0
    assert new_state["pair_tension"]["PAIR_B"] == 0
    assert new_state["pair_tension"]["PAIR_C"] == 0


def test_update_immutable_input() -> None:
    """입력 state는 변경되지 않아야 함 (deep copy)."""
    state = _base_state()
    state_copy = {**state, "pair_tension": dict(state["pair_tension"])}
    update_pair_tension(
        state,
        outcome="DRAW",
        episode_type="BATTLE",
        hero_ids=["CHAR_HERO_001", "CHAR_HERO_003"],
    )
    assert state["pair_tension"] == state_copy["pair_tension"]


# ── Feature Flag ─────────────────────────────────────────────────────────────

def test_is_pair_tension_enabled_default_false(monkeypatch) -> None:
    monkeypatch.delenv("PAIR_TENSION_ENABLED", raising=False)
    assert is_pair_tension_enabled() is False


def test_is_pair_tension_enabled_true(monkeypatch) -> None:
    monkeypatch.setenv("PAIR_TENSION_ENABLED", "true")
    assert is_pair_tension_enabled() is True


def test_is_pair_tension_enabled_case_insensitive(monkeypatch) -> None:
    monkeypatch.setenv("PAIR_TENSION_ENABLED", "TRUE")
    assert is_pair_tension_enabled() is True
