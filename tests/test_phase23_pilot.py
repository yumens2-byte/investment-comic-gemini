"""
Phase 2.3 파일럿 — Feature Flag 전체 ON 상태에서 4 시나리오 종단 검증.

검증 시나리오:
1. BATTLE       — 평범한 전투, VS Bonus + crowd_modifier 통합 동작
2. EMERGENCE    — 신규 빌런 등장, Information Deficit + OUTCOME Demotion
3. AFTERMATH    — 전투 후 후일담, pair_tension 일괄 -10
4. CONFLICT     — pair_tension >= 70 트리거로 격상, narrative 프롬프트에 양 블록 모두 포함

각 시나리오에서:
- episode_type 판정이 기대대로
- BattleResult 보정이 기대대로
- narrative_user.j2 렌더링에 belief + pair_tension 블록이 포함되는지
"""
from __future__ import annotations

import pytest

from engine.arc.arc_state_engine import update_emergence_deficit, update_pair_tension
from engine.narrative.battle_calc import BattleResult, apply_v23_modifiers
from engine.narrative.episode_type_engine import determine_episode_type
from engine.narrative.prompt_tpl import render_user_prompt


# ── Feature Flag 전체 ON fixture ──────────────────────────────────────────────

@pytest.fixture(autouse=True)
def all_flags_on(monkeypatch):
    """이 모듈의 모든 테스트는 5개 Feature Flag 전체 ON."""
    monkeypatch.setenv("NARRATIVE_DEPTH_ENABLED", "true")
    monkeypatch.setenv("PAIR_TENSION_ENABLED", "true")
    monkeypatch.setenv("CROWD_MODIFIER_ENABLED", "true")
    monkeypatch.setenv("VILLAIN_SIGNATURE_BONUS_ENABLED", "true")
    monkeypatch.setenv("EMERGENCE_DEFICIT_ENABLED", "true")


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


HERO_BELIEF = {
    "want": "무너지지 않는 시스템을 만드는 것.",
    "need": "회복력의 본질을 깨닫는 것.",
    "fear": "팀이 무너지는 것.",
    "lie": "내가 강하면 충분하다.",
    "truth": "함께 있어야 강하다.",
    "contradiction": "리더지만 외롭다.",
}

VILLAIN_BELIEF_OIL_SHOCK = {
    "natural_disaster": True,
    "phenomenon": "에너지 가격 임계 초과 시 발현.",
    "attenuation": "가격이 회귀할 때 약화.",
    "revelation": "자연재해는 영원하지 않다.",
    "paradox": "파괴 후 자신도 사라진다.",
    "defeat_visual": "화염이 잦아든다.",
}


# ═══════════════════════════════════════════════════════════════════════════
# 시나리오 1: BATTLE — 평범한 전투, 모든 modifier 통합
# ═══════════════════════════════════════════════════════════════════════════

def test_pilot_battle_scenario() -> None:
    """
    Arc Day 2, 일반 BATTLE_PLUS.
    crowd_momentum=10 (+2), villain_signature=2 (+8).
    """
    arc_state = {
        "arc_day": 2,
        "arc_tension": 50,
        "form2_available": False,
        "form3_activated": False,
        "pair_tension": {"PAIR_A": 30, "PAIR_B": 0, "PAIR_C": 0},
        "edt_pressure": 30.0,
        "zero_block_just_appeared": False,
        "crowd_momentum": 10,
        "villain_signature": 2,
        "emergence_deficit_days": 0,
    }
    delta = {"reversal_state": "NONE"}

    # 1) 에피소드 타입 결정
    ep_result = determine_episode_type(arc_state, delta, risk_level="MEDIUM")
    assert ep_result.episode_type == "BATTLE_PLUS"  # arc_day=2 → BATTLE_PLUS
    assert ep_result.pair_trigger_flag is False     # PAIR_A=30 < 70

    # 2) 배틀 결과 보정
    original = _make_battle_result(hero_power=100, villain_power=90)
    arc_ctx = {
        "villain_signature": 2,
        "crowd_momentum": 10,
        "emergence_deficit_days": 0,
    }
    boosted = apply_v23_modifiers(original, arc_ctx, ep_result.episode_type)
    assert boosted.villain_power == 98     # +8 VS Bonus
    assert boosted.hero_power == 102       # round(10/4)=2
    assert boosted.balance == 4

    # 3) 프롬프트 렌더링: belief + pair 블록 모두 포함
    rendered = render_user_prompt(
        date="2026-05-15",
        episode_id="ep030",
        event_type="MARKET_SHOCK",
        delta=delta,
        battle_result={
            "hero_power": boosted.hero_power,
            "villain_power": boosted.villain_power,
            "balance": boosted.balance,
            "outcome": boosted.outcome,
        },
        hero_id="CHAR_HERO_001",
        villain_id="CHAR_VILLAIN_002",
        arc_context=arc_state,
        narrative_depth_enabled=True,
        pair_tension_enabled=True,
        hero_belief=HERO_BELIEF,
        villain_belief=VILLAIN_BELIEF_OIL_SHOCK,
        triggered_pair=None,
    )
    assert "Character Belief Sheet" in rendered
    assert "Pair Relationship Tension" in rendered
    assert "Triggered Pair" not in rendered  # 트리거 없음


# ═══════════════════════════════════════════════════════════════════════════
# 시나리오 2: EMERGENCE — 신규 빌런 등장 + Deficit
# ═══════════════════════════════════════════════════════════════════════════

def test_pilot_emergence_scenario() -> None:
    """
    Arc Day 1 + villain_changed=True → EMERGENCE 강제.
    Information Deficit -10, OUTCOME Demotion 적용.
    """
    arc_state = {
        "arc_day": 1,
        "arc_tension": 30,
        "form2_available": False,
        "form3_activated": False,
        "pair_tension": {"PAIR_A": 0, "PAIR_B": 0, "PAIR_C": 0},
        "edt_pressure": 0.0,
        "zero_block_just_appeared": False,
        "crowd_momentum": 0,
        "villain_signature": 1,
        "emergence_deficit_days": 0,
    }
    delta = {"reversal_state": "NONE"}

    ep_result = determine_episode_type(
        arc_state, delta, risk_level="MEDIUM", villain_changed=True
    )
    assert ep_result.episode_type == "EMERGENCE"

    # 처음 EMERGENCE 발행 시 deficit_days는 update_emergence_deficit이 set
    # 배틀 결과 보정 단계: deficit_days=0 (아직 set 전), episode_type=EMERGENCE → -10
    original = _make_battle_result(hero_power=100, villain_power=90, outcome="HERO_VICTORY")
    arc_ctx = {
        "villain_signature": 1,
        "crowd_momentum": 0,
        "emergence_deficit_days": 0,
    }
    boosted = apply_v23_modifiers(original, arc_ctx, "EMERGENCE")
    # hero_power 100 - 10 = 90, balance 0, demotion: 0 >= -4 → -11
    assert boosted.hero_power == 90
    assert boosted.balance == -11
    # outcome 재판정: balance -11 → HERO_DEFEAT
    assert boosted.outcome == "HERO_DEFEAT"

    # update_emergence_deficit 후 days=2로 설정 (다음 EP에서 사용)
    next_state = update_emergence_deficit(arc_state, "EMERGENCE")
    assert next_state["emergence_deficit_days"] == 2


# ═══════════════════════════════════════════════════════════════════════════
# 시나리오 3: AFTERMATH — pair_tension 일괄 감소
# ═══════════════════════════════════════════════════════════════════════════

def test_pilot_aftermath_scenario() -> None:
    """
    Arc Day 6, AFTERMATH 기본 타입.
    PR-05: 모든 페어 -10.
    """
    arc_state = {
        "arc_day": 6,
        "arc_tension": 40,
        "form2_available": False,
        "form3_activated": False,
        "pair_tension": {"PAIR_A": 50, "PAIR_B": 40, "PAIR_C": 30},
        "edt_pressure": 79.0,
        "zero_block_just_appeared": False,
        "crowd_momentum": 5,
        "villain_signature": 1,
        "emergence_deficit_days": 0,
    }
    delta = {"reversal_state": "NONE"}

    ep_result = determine_episode_type(arc_state, delta, risk_level="MEDIUM")
    assert ep_result.episode_type == "AFTERMATH"

    # PR-05 적용 (update_pair_tension)
    updated_state = update_pair_tension(
        arc_state,
        outcome="HERO_VICTORY",
        episode_type="AFTERMATH",
        hero_ids=["CHAR_HERO_001"],
    )
    assert updated_state["pair_tension"]["PAIR_A"] == 40
    assert updated_state["pair_tension"]["PAIR_B"] == 30
    assert updated_state["pair_tension"]["PAIR_C"] == 20
    # edt_pressure 자동 재계산: 40 + 15 + 6 = 61.0
    assert updated_state["edt_pressure"] == 61.0


# ═══════════════════════════════════════════════════════════════════════════
# 시나리오 4: CONFLICT — pair_tension trigger + 격상
# ═══════════════════════════════════════════════════════════════════════════

def test_pilot_conflict_scenario() -> None:
    """
    Arc Day 3, base TACTICAL.
    PAIR_A = 80 → STEP 1.5-B 트리거 → STEP 4-B 조건B로 CONFLICT 격상.
    렌더링 시 Triggered Pair 경고 출력.
    """
    arc_state = {
        "arc_day": 3,
        "arc_tension": 40,
        "form2_available": False,
        "form3_activated": False,
        "pair_tension": {"PAIR_A": 80, "PAIR_B": 0, "PAIR_C": 0},
        "edt_pressure": 80.0,
        "zero_block_just_appeared": False,
        "crowd_momentum": 0,
        "villain_signature": 1,
        "emergence_deficit_days": 0,
    }
    delta = {"reversal_state": "NONE"}

    ep_result = determine_episode_type(arc_state, delta, risk_level="MEDIUM")
    assert ep_result.episode_type == "CONFLICT"
    assert ep_result.pair_trigger_flag is True
    assert ep_result.triggered_pair == "PAIR_A"

    # PR-04 적용: CONFLICT 종결 후 해당 페어 -30
    updated_state = update_pair_tension(
        arc_state,
        outcome="DRAW",
        episode_type="CONFLICT",
        hero_ids=["CHAR_HERO_001", "CHAR_HERO_003"],
    )
    assert updated_state["pair_tension"]["PAIR_A"] == 50  # 80-30
    assert updated_state["edt_pressure"] == 50.0

    # 프롬프트에 Triggered Pair 경고 포함
    rendered = render_user_prompt(
        date="2026-05-16",
        episode_id="ep031",
        event_type="VOLATILITY_SURGE",
        delta=delta,
        battle_result={"balance": 0, "outcome": "DRAW"},
        hero_id="CHAR_HERO_001",
        villain_id="CHAR_VILLAIN_002",
        arc_context=arc_state,
        narrative_depth_enabled=True,
        pair_tension_enabled=True,
        hero_belief=HERO_BELIEF,
        villain_belief=VILLAIN_BELIEF_OIL_SHOCK,
        triggered_pair="PAIR_A",
    )
    assert "Triggered Pair" in rendered
    assert "PAIR_A" in rendered


# ═══════════════════════════════════════════════════════════════════════════
# 통합: 다단계 시퀀스 (EMERGENCE → BATTLE → AFTERMATH)
# ═══════════════════════════════════════════════════════════════════════════

def test_pilot_multi_episode_sequence() -> None:
    """
    EMERGENCE → 다음 EP에서 deficit_days=1 (-5 잔류) → 그 다음 EP 0.
    """
    arc_state = {
        "arc_day": 1,
        "arc_tension": 30,
        "pair_tension": {"PAIR_A": 0, "PAIR_B": 0, "PAIR_C": 0},
        "edt_pressure": 0.0,
        "zero_block_just_appeared": False,
        "crowd_momentum": 0,
        "villain_signature": 1,
        "emergence_deficit_days": 0,
    }

    # EP1: EMERGENCE 발행 → days=2 설정
    state_after_ep1 = update_emergence_deficit(arc_state, "EMERGENCE")
    assert state_after_ep1["emergence_deficit_days"] == 2

    # EP2: BATTLE → modifier -10 (days >= 2)
    original2 = _make_battle_result(hero_power=100, villain_power=90)
    arc_ctx_ep2 = {
        "villain_signature": 1,
        "crowd_momentum": 0,
        "emergence_deficit_days": state_after_ep1["emergence_deficit_days"],
    }
    boosted2 = apply_v23_modifiers(original2, arc_ctx_ep2, "BATTLE")
    assert boosted2.hero_power == 90  # -10
    # 그 후 deficit decrement
    state_after_ep2 = update_emergence_deficit(state_after_ep1, "BATTLE")
    assert state_after_ep2["emergence_deficit_days"] == 1

    # EP3: BATTLE → modifier -5 (days == 1)
    original3 = _make_battle_result(hero_power=100, villain_power=90)
    arc_ctx_ep3 = {
        "villain_signature": 1,
        "crowd_momentum": 0,
        "emergence_deficit_days": state_after_ep2["emergence_deficit_days"],
    }
    boosted3 = apply_v23_modifiers(original3, arc_ctx_ep3, "BATTLE")
    assert boosted3.hero_power == 95  # -5
    state_after_ep3 = update_emergence_deficit(state_after_ep2, "BATTLE")
    assert state_after_ep3["emergence_deficit_days"] == 0

    # EP4: BATTLE → modifier 0 (days == 0)
    arc_ctx_ep4 = {
        "villain_signature": 1,
        "crowd_momentum": 0,
        "emergence_deficit_days": state_after_ep3["emergence_deficit_days"],
    }
    boosted4 = apply_v23_modifiers(
        _make_battle_result(hero_power=100, villain_power=90), arc_ctx_ep4, "BATTLE"
    )
    assert boosted4.hero_power == 100  # 변경 없음
