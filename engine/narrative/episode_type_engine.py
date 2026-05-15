"""
engine/narrative/episode_type_engine.py
ICG 에피소드 타입 결정 엔진 v1.0

EDT 15_EPISODE_TYPE_ENGINE v1.4 기반 Python 구현.
9종 에피소드 타입 + Form 분기를 결정론적 로직으로 판정.

설계 기반:
    - EDT 15_EDT_EPISODE_TYPE_ENGINE_v1.0 (7종 기본)
    - EDT 15_EDT_EPISODE_TYPE_ENGINE_v1.3 (CONFLICT/EMERGENCE 추가)
    - EDT 15_EDT_EPISODE_TYPE_ENGINE_v1.4 (SEASON_FINALE)
    - ICG arc_state_engine.py (check_form2/check_form3)

배포 위치: engine/narrative/episode_type_engine.py
Feature Flag: EPISODE_TYPE_V3_ENABLED (env)

VERSION: 1.0.0
DATE: 2026-05-02
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Literal

VERSION = "1.0.0"

logger = logging.getLogger(__name__)

# ── 타입 상수 ─────────────────────────────────────────────────────────────────

EpisodeType = Literal[
    "BATTLE",
    "BATTLE_PLUS",
    "BATTLE_PLUS_FORM2",
    "BATTLE_PLUS_FORM3",
    "TACTICAL",
    "STALEMATE",
    "INTEL",
    "AFTERMATH",
    "FLASHBACK",
    "CONFLICT",
    "EMERGENCE",
    "SEASON_FINALE",
]

ActPhase = Literal["ACT_1", "ACT_2", "ACT_3"]

# ── ICG scenario_type 역변환 테이블 ──────────────────────────────────────────
# ICG 기존 battle_calc / asset_writer 호환 유지용

_EPISODE_TO_SCENARIO: dict[str, str] = {
    "BATTLE":             "ONE_VS_ONE",
    "BATTLE_PLUS":        "ONE_VS_ONE",
    "BATTLE_PLUS_FORM2":  "ONE_VS_ONE",
    "BATTLE_PLUS_FORM3":  "ONE_VS_ONE",
    "TACTICAL":           "NO_BATTLE",
    "STALEMATE":          "NO_BATTLE",
    "INTEL":              "NO_BATTLE",
    "AFTERMATH":          "NO_BATTLE",
    "FLASHBACK":          "NO_BATTLE",
    "CONFLICT":           "NO_BATTLE",
    "EMERGENCE":          "ONE_VS_ONE",
    "SEASON_FINALE":      "ALLIANCE",
}

# ── DSS 근사값 매핑 (ICG risk_level → EDT DSS 수치 근사) ──────────────────────

_RISK_TO_DSS: dict[str, int] = {
    "LOW":      15,
    "MEDIUM":   40,
    "HIGH":     60,
    "CRITICAL": 80,
}

# ── EPIC DSS 임계값 ───────────────────────────────────────────────────────────
_EPIC_DSS_THRESHOLD = 70

# ── Act 구조 (arc_day 기반) ───────────────────────────────────────────────────
_ACT_1_RANGE = range(1, 6)    # Day 1~5
_ACT_2_RANGE = range(6, 12)   # Day 6~11
# Act 3: Day 12+


# ── 결과 데이터클래스 ─────────────────────────────────────────────────────────

@dataclass
class EpisodeTypeResult:
    """에피소드 타입 결정 결과."""

    episode_type: str
    scenario_type: str                    # ICG 기존 호환용
    act_phase: str
    determined_by_step: str               # 결정된 STEP 이름
    reason: str                           # 결정 이유 1줄
    act_warning: str = ""                 # STEP 1.5 경고 (있을 경우)
    form_bonus: int = 0                   # Form 2/3 보너스 (battle_calc 전달용)
    recommended_heroes: list[str] = field(default_factory=list)
    slide_count: int = 8
    # ── v1.5 신규 ──
    triggered_pair: str | None = None     # STEP 1.5-B 결과 (PR-01 가중 출처)
    pair_trigger_flag: bool = False


# ── 슬라이드 수 테이블 ─────────────────────────────────────────────────────────

_SLIDE_COUNT: dict[str, int] = {
    "BATTLE":             8,
    "BATTLE_PLUS":        8,
    "BATTLE_PLUS_FORM2":  10,
    "BATTLE_PLUS_FORM3":  10,
    "TACTICAL":           8,
    "STALEMATE":          8,
    "INTEL":              8,
    "AFTERMATH":          8,
    "FLASHBACK":          8,
    "CONFLICT":           8,
    "EMERGENCE":          8,
    "SEASON_FINALE":      12,
}


# ── 메인 진입점 ───────────────────────────────────────────────────────────────

def determine_episode_type(
    arc_state: dict,
    delta: dict,
    risk_level: str = "MEDIUM",
    recent_outcomes: list[str] | None = None,
    villain_changed: bool = False,
    season_finale_manual: bool = False,
) -> EpisodeTypeResult:
    """
    에피소드 타입 결정 (EDT STEP 0~5 로직).

    Args:
        arc_state:            load_arc_state() 결과
        delta:                compute(curr, prev) 결과
        risk_level:           compute_risk_level_from_delta() 결과
        recent_outcomes:      최근 에피소드 OUTCOME 목록 (STEP 4 CONFLICT 판정용)
        villain_changed:      빌런 전환 여부 (STEP 0.5 EMERGENCE 판정용)
        season_finale_manual: 마스터 수동 SEASON_FINALE 실행 여부

    Returns:
        EpisodeTypeResult
    """
    if recent_outcomes is None:
        recent_outcomes = []

    arc_day = arc_state.get("arc_day") or 0
    arc_tension = arc_state.get("arc_tension") or 30
    form3_activated = arc_state.get("form3_activated") or False
    form2_available = arc_state.get("form2_available") or False
    reversal_state = delta.get("reversal_state") or "NONE"
    dss_score = _RISK_TO_DSS.get(risk_level, 40)
    act_phase = get_act_phase(arc_day)

    logger.info(
        "[EpisodeTypeEngine v%s] 판정 시작 "
        "(arc_day=%d tension=%d dss=%d risk=%s act=%s)",
        VERSION, arc_day, arc_tension, dss_score, risk_level, act_phase,
    )

    # ── SEASON_FINALE 수동 트리거 (최우선 수동 오버라이드) ─────────────────────
    if season_finale_manual:
        return _make_result(
            episode_type="SEASON_FINALE",
            step="MANUAL_OVERRIDE",
            reason="마스터 수동 실행: run episode SEASON_FINALE",
            arc_day=arc_day,
        )

    # ── STEP 0: Form 3 Post-Awakening 강제 ────────────────────────────────────
    result = _step0_form3_post(form3_activated, arc_state, arc_day)
    if result:
        return result

    # ── STEP 0.5: EMERGENCE 체크 ──────────────────────────────────────────────
    result = _step0_5_emergence(arc_day, villain_changed, form3_activated)
    if result:
        return result

    # ── STEP 1: EPIC 강제 체크 (DSS >= 70) ────────────────────────────────────
    result = _step1_epic(dss_score, arc_state, form2_available, form3_activated, arc_day)
    if result:
        return result

    # ── STEP 1.5: Act 필터 (경고만, 강제 없음) ────────────────────────────────
    act_warning = _step1_5_act_filter(arc_day, act_phase, dss_score)

    # ── STEP 1.5-B: 페어 텐션 체크 (v1.5 신설, Feature Flag 가드) ────────────
    pair_trigger_flag, triggered_pair = _step1_5_b_pair_tension(arc_state)

    # ── STEP 2: 새 빌런 등장 체크 (arc_day == 1) ──────────────────────────────
    result = _step2_new_villain(arc_day, act_warning, act_phase)
    if result:
        return result

    # ── STEP 3: Arc Day 기반 기본값 ───────────────────────────────────────────
    base_type = _step3_arc_day_base(arc_day)

    # ── STEP 4: DSS + REVERSAL + CONFLICT 보정 (PR-01 가중 통합) ──────────────
    corrected_type = _step4_dss_correction(
        base_type=base_type,
        dss_score=dss_score,
        arc_day=arc_day,
        arc_tension=arc_tension,
        reversal_state=reversal_state,
        recent_outcomes=recent_outcomes,
        act_phase=act_phase,
        pair_trigger_flag=pair_trigger_flag,    # v1.5 PR-01 조건 B
        triggered_pair=triggered_pair,
    )

    # ── STEP 3-F: Form 2/3 트리거 (BATTLE_PLUS 타입 시) ──────────────────────
    form_bonus = 0
    if corrected_type in ("BATTLE_PLUS", "BATTLE"):
        corrected_type, form_bonus = _step3f_form_check(
            episode_type=corrected_type,
            arc_state=arc_state,
            delta=delta,
        )

    reason = _make_reason(corrected_type, arc_day, dss_score, risk_level)
    return _make_result(
        episode_type=corrected_type,
        step="STEP_3_4",
        reason=reason,
        arc_day=arc_day,
        act_warning=act_warning,
        form_bonus=form_bonus,
        triggered_pair=triggered_pair,
        pair_trigger_flag=pair_trigger_flag,
    )


# ── STEP 함수들 ───────────────────────────────────────────────────────────────

def _step0_form3_post(
    form3_activated: bool,
    arc_state: dict,
    arc_day: int,
) -> EpisodeTypeResult | None:
    """STEP 0: Form 3 Post-Awakening 강제 (AFTERMATH 고정)."""
    if not form3_activated:
        return None
    countdown = arc_state.get("form3_countdown") or 0
    if countdown <= 0:
        return None
    logger.info("[EpisodeTypeEngine] STEP 0: Form 3 Post-Awakening → AFTERMATH 강제")
    return _make_result(
        episode_type="AFTERMATH",
        step="STEP_0",
        reason=f"Form 3 Post-Awakening 강제 (countdown={countdown})",
        arc_day=arc_day,
    )


def _step0_5_emergence(
    arc_day: int,
    villain_changed: bool,
    form3_activated: bool,
) -> EpisodeTypeResult | None:
    """STEP 0.5: EMERGENCE 체크 (arc_day==1 AND villain_changed)."""
    if form3_activated:
        return None
    if arc_day == 1 and villain_changed:
        logger.info("[EpisodeTypeEngine] STEP 0.5: 빌런 전환 감지 → EMERGENCE 권장")
        return _make_result(
            episode_type="EMERGENCE",
            step="STEP_0_5",
            reason="새 빌런 등장 (villain_changed=True, arc_day=1)",
            arc_day=arc_day,
        )
    return None


def _step1_epic(
    dss_score: int,
    arc_state: dict,
    form2_available: bool,
    form3_activated: bool,
    arc_day: int,
) -> EpisodeTypeResult | None:
    """STEP 1: EPIC 강제 체크 (DSS >= 70)."""
    if dss_score < _EPIC_DSS_THRESHOLD:
        return None

    from engine.arc.arc_state_engine import check_form2, check_form3

    is_edt = True  # ICG에서 EDT 히어로 기본 가정
    balance_estimate = 55  # EPIC 시 balance 충분 가정 (Form3 >= 50 조건 포함)

    if not form3_activated and check_form3(arc_state, balance_estimate, is_edt):
        logger.info("[EpisodeTypeEngine] STEP 1: EPIC + Form3 조건 충족")
        return _make_result(
            episode_type="BATTLE_PLUS_FORM3",
            step="STEP_1",
            reason=f"EPIC (DSS={dss_score}) + Form 3 5-AND 충족",
            arc_day=arc_day,
            form_bonus=40,
        )

    if check_form2(arc_state, balance_estimate, is_edt):
        logger.info("[EpisodeTypeEngine] STEP 1: EPIC + Form2 조건 충족")
        return _make_result(
            episode_type="BATTLE_PLUS_FORM2",
            step="STEP_1",
            reason=f"EPIC (DSS={dss_score}) + Form 2 4-AND 충족",
            arc_day=arc_day,
            form_bonus=20,
        )

    logger.info("[EpisodeTypeEngine] STEP 1: EPIC → BATTLE 강제")
    return _make_result(
        episode_type="BATTLE",
        step="STEP_1",
        reason=f"EPIC (DSS={dss_score} >= {_EPIC_DSS_THRESHOLD}) → 정면 전투",
        arc_day=arc_day,
    )


def _step1_5_act_filter(arc_day: int, act_phase: str, dss_score: int) -> str:
    """
    STEP 1.5: Act 필터 경고 생성 (강제 없음).

    Returns:
        경고 메시지 (없으면 빈 문자열)
    """
    if act_phase == "ACT_1" and dss_score >= _EPIC_DSS_THRESHOLD:
        return (
            f"⚠️ Act 필터 경고: Arc Day {arc_day} (Act 1) 구간에서 "
            "BATTLE+ 발동은 서사 현실감 저하 가능. 권장: EMERGENCE/TACTICAL"
        )
    if act_phase == "ACT_3":
        return (
            f"ℹ️ Act 3 (Day {arc_day}): BATTLE+ / AFTERMATH 권장 구간. "
            "Form 3 조건 점검 권장."
        )
    return ""


def _step1_5_b_pair_tension(arc_state: dict) -> tuple[bool, str | None]:
    """
    STEP 1.5-B (v1.5 신설): 페어 텐션 체크 — RULE PR-01 작동 위치.

    Feature Flag: PAIR_TENSION_ENABLED
    미활성 시: (False, None) 반환 → STEP 4-B 조건 B 비활성.

    Returns:
        (pair_tension_trigger_flag, triggered_pair)
    """
    if os.environ.get("PAIR_TENSION_ENABLED", "false").lower() != "true":
        return False, None
    try:
        from engine.arc.arc_state_engine import check_pair_tension_trigger
        flag, triggered = check_pair_tension_trigger(arc_state)
        if flag:
            logger.info(
                "[EpisodeTypeEngine] STEP 1.5-B: pair_tension trigger = %s "
                "(pair_tension=%s)",
                triggered, arc_state.get("pair_tension"),
            )
        return flag, triggered
    except Exception as exc:
        logger.warning(
            "[EpisodeTypeEngine] STEP 1.5-B 실패 (진행): %s", exc,
        )
        return False, None


def _step2_new_villain(
    arc_day: int,
    act_warning: str,
    act_phase: str,
) -> EpisodeTypeResult | None:
    """STEP 2: 새 빌런 등장 체크 (arc_day == 1 → BATTLE)."""
    if arc_day != 1:
        return None
    logger.info("[EpisodeTypeEngine] STEP 2: arc_day=1 → BATTLE 고정")
    return _make_result(
        episode_type="BATTLE",
        step="STEP_2",
        reason="새 빌런 첫 등장 (arc_day=1) → 첫 만남은 항상 전투",
        arc_day=arc_day,
        act_warning=act_warning,
    )


def _step3_arc_day_base(arc_day: int) -> str:
    """STEP 3: Arc Day 기반 기본 타입 결정. arc_day <= 0은 초기 상태로 BATTLE 처리."""
    if arc_day <= 0:
        return "BATTLE"
    mapping: dict[int, str] = {
        1:  "BATTLE",
        2:  "BATTLE_PLUS",
        3:  "TACTICAL",
        4:  "STALEMATE",
        5:  "INTEL",
        6:  "AFTERMATH",
    }
    if arc_day in mapping:
        return mapping[arc_day]
    return "FLASHBACK"  # Day 7+


def _step4_dss_correction(
    base_type: str,
    dss_score: int,
    arc_day: int,
    arc_tension: int,
    reversal_state: str,
    recent_outcomes: list[str],
    act_phase: str,
    pair_trigger_flag: bool = False,
    triggered_pair: str | None = None,
) -> str:
    """
    STEP 4: DSS + REVERSAL + CONFLICT 보정.

    EDT 15 v1.5 STEP 4 통합 (Phase 2.3):
        Step 4-A: DSS 기반 EPIC 보정 (기존)
        Step 4-B: CONFLICT 가중 — 조건 A (Draw 누적) OR 조건 B (PR-01 pair_tension)
        Step 4-C: REVERSAL 보정

    가중 중복 금지: 조건 A/B 동시 충족도 최대 1회만 CONFLICT 격상.
    """
    corrected = base_type

    # ── 4-A: 기존 DSS 보정 ────────────────────────────────────────────────────
    if dss_score >= 50 and arc_day in (3, 4):
        corrected = "TACTICAL"
    elif dss_score <= 15 and arc_day in (1, 2):
        corrected = "STALEMATE"

    # ── 4-C: REVERSAL 가중 ────────────────────────────────────────────────────
    if reversal_state == "REVERSAL_UP":
        if corrected in ("BATTLE", "BATTLE_PLUS", "STALEMATE"):
            corrected = "TACTICAL"
            logger.info("[EpisodeTypeEngine] STEP 4-B: REVERSAL_UP → TACTICAL 보정")
    elif reversal_state == "REVERSAL_DOWN":
        if corrected in ("TACTICAL", "STALEMATE", "INTEL"):
            corrected = "BATTLE"
            logger.info("[EpisodeTypeEngine] STEP 4-B: REVERSAL_DOWN → BATTLE 보정")

    # ── 4-B: CONFLICT 가중 (v1.5 — 조건 A 또는 조건 B) ───────────────────────
    cond_a = _check_conflict_conditions(arc_day, arc_tension, recent_outcomes, act_phase)
    cond_b = pair_trigger_flag  # v1.5 STEP 1.5-B 산출값

    if cond_a or cond_b:
        # REVERSAL_DOWN과 동시 충돌 처리 (기존 우선순위 유지)
        if reversal_state == "REVERSAL_DOWN" and arc_tension >= 70:
            corrected = "BATTLE"
            logger.info(
                "[EpisodeTypeEngine] STEP 4-C: REVERSAL_DOWN+CONFLICT 충돌 "
                "→ tension>=70 BATTLE 우선"
            )
        else:
            corrected = "CONFLICT"
            sources = []
            if cond_a:
                sources.append("조건A(Draw누적)")
            if cond_b:
                sources.append(f"조건B(PR-01:{triggered_pair})")
            logger.info(
                "[EpisodeTypeEngine] STEP 4-C: CONFLICT 가중 발동 (%s)",
                "+".join(sources),
            )

    return corrected


def _step3f_form_check(
    episode_type: str,
    arc_state: dict,
    delta: dict,
) -> tuple[str, int]:
    """
    STEP 3-F: BATTLE_PLUS 타입 시 Form 2/3 트리거 판정.

    Returns:
        (최종 episode_type, form_bonus)
    """
    try:
        from engine.arc.arc_state_engine import check_form2, check_form3

        is_edt = True
        balance_estimate = 25  # BATTLE 시 balance 양수 가정
        form3_activated = arc_state.get("form3_activated") or False

        if not form3_activated and check_form3(arc_state, balance_estimate, is_edt):
            logger.info("[EpisodeTypeEngine] STEP 3-F: Form 3 5-AND 충족")
            return "BATTLE_PLUS_FORM3", 40

        if check_form2(arc_state, balance_estimate, is_edt):
            logger.info("[EpisodeTypeEngine] STEP 3-F: Form 2 4-AND 충족")
            return "BATTLE_PLUS_FORM2", 20

    except Exception as _exc:
        logger.warning("[EpisodeTypeEngine] STEP 3-F Form 체크 실패 (진행): %s", _exc)

    return episode_type, 0


# ── 조건 판정 헬퍼 ────────────────────────────────────────────────────────────

def _check_conflict_conditions(
    arc_day: int,
    arc_tension: int,
    recent_outcomes: list[str],
    act_phase: str,
) -> bool:
    """
    CONFLICT 3-AND 조건 판정 (EDT 15 v1.3 STEP 4 확장-B).

    T1: 최근 2회 결과 = Draw 또는 Stalemate
    T2: 50 <= arc_tension < 80
    T3: arc_day >= 4
    추가: Act 2 구간 (arc_day 6~11) 권장 (강제 아님)
    """
    if arc_day < 4:
        return False
    if not (50 <= arc_tension < 80):
        return False
    if len(recent_outcomes) < 2:
        return False
    neutral_outcomes = {"DRAW", "STALEMATE", "Strategic Deliberation"}
    last_two = [o.upper() for o in recent_outcomes[:2]]
    t1 = all(o in neutral_outcomes or "DRAW" in o or "STALE" in o for o in last_two)
    return t1


# ── 유틸리티 ─────────────────────────────────────────────────────────────────

def get_act_phase(arc_day: int) -> str:
    """arc_day → Act 1/2/3 판정. arc_day <= 0은 초기 상태로 ACT_1 처리."""
    if arc_day <= 0 or arc_day in _ACT_1_RANGE:
        return "ACT_1"
    if arc_day in _ACT_2_RANGE:
        return "ACT_2"
    return "ACT_3"


def to_scenario_type(episode_type: str) -> str:
    """
    episode_type_v3 → ICG 기존 scenario_type 역변환.
    ICG battle_calc / asset_writer 호환 유지용.
    """
    return _EPISODE_TO_SCENARIO.get(episode_type, "ONE_VS_ONE")


def is_battle_type(episode_type: str) -> bool:
    """전투 포함 타입 여부."""
    return episode_type in (
        "BATTLE", "BATTLE_PLUS", "BATTLE_PLUS_FORM2", "BATTLE_PLUS_FORM3",
        "EMERGENCE", "SEASON_FINALE",
    )


def get_type_description(episode_type: str) -> str:
    """에피소드 타입 1줄 설명 (EPISODE GUIDE 출력용)."""
    desc = {
        "BATTLE":             "빌런과의 정면 전투",
        "BATTLE_PLUS":        "EDT가 특수 형태로 변환해 싸운다",
        "BATTLE_PLUS_FORM2":  "EDT Form 2 각성 — 강화 전투",
        "BATTLE_PLUS_FORM3":  "EDT Form 3 완전 각성 — 시스템급 전투",
        "TACTICAL":           "전략가의 눈으로 약점을 찾는다",
        "STALEMATE":          "전투 없이 버티는 긴장의 하루",
        "INTEL":              "Futures Girl이 신호를 먼저 잡는다",
        "AFTERMATH":          "전투 후 EDT의 독백과 재기 선언",
        "FLASHBACK":          "과거의 기억이 오늘을 말한다",
        "CONFLICT":           "히어로 진영 내부의 전략 갈등",
        "EMERGENCE":          "새 위협의 등장 — 첫 탐색전",
        "SEASON_FINALE":      "시즌 결전 — 전 히어로 총집결",
    }
    return desc.get(episode_type, episode_type)


# ── 결과 빌더 ─────────────────────────────────────────────────────────────────

def _make_result(
    episode_type: str,
    step: str,
    reason: str,
    arc_day: int,
    act_warning: str = "",
    form_bonus: int = 0,
    triggered_pair: str | None = None,
    pair_trigger_flag: bool = False,
) -> EpisodeTypeResult:
    """EpisodeTypeResult 생성 헬퍼."""
    act_phase = get_act_phase(arc_day)
    logger.info(
        "[EpisodeTypeEngine] 결정: %s (step=%s act=%s pair=%s)",
        episode_type, step, act_phase, triggered_pair,
    )
    return EpisodeTypeResult(
        episode_type=episode_type,
        scenario_type=to_scenario_type(episode_type),
        act_phase=act_phase,
        determined_by_step=step,
        reason=reason,
        act_warning=act_warning,
        form_bonus=form_bonus,
        slide_count=_SLIDE_COUNT.get(episode_type, 8),
        triggered_pair=triggered_pair,
        pair_trigger_flag=pair_trigger_flag,
    )


def _make_reason(
    episode_type: str,
    arc_day: int,
    dss_score: int,
    risk_level: str,
) -> str:
    """추천 이유 1줄 생성."""
    reasons: dict[str, str] = {
        "BATTLE":    f"Arc Day {arc_day} / DSS={dss_score} — 정면 전투",
        "BATTLE_PLUS": f"Arc Day {arc_day} / EDT 변환 전투가 유효",
        "TACTICAL":  f"Arc Day {arc_day} / {risk_level} — 전술 분석으로 돌파구",
        "STALEMATE": f"Arc Day {arc_day} / {risk_level} — 무리한 전투보다 수비",
        "INTEL":     f"Arc Day {arc_day} — Futures Girl이 신호 먼저 탐지",
        "AFTERMATH": "전투가 끝난 다음날 — 히어로의 내면을 보여줄 시간",
        "FLASHBACK": f"Arc Day {arc_day}일 이상 — 과거 유사 위기와 비교",
        "CONFLICT":  "연속 교착 + 긴장도 중간 — 진영 내 전략 갈등",
        "EMERGENCE": "새 빌런 첫 등장 — 첫 만남은 항상 전투",
    }
    return reasons.get(episode_type, f"{episode_type} (arc_day={arc_day})")


# ── Feature Flag 가드 ─────────────────────────────────────────────────────────

def is_enabled() -> bool:
    """EPISODE_TYPE_V3_ENABLED 환경변수 확인."""
    return os.environ.get("EPISODE_TYPE_V3_ENABLED", "false").lower() == "true"
