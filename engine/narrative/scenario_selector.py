"""
engine/narrative/scenario_selector.py
ICG 2차 고도화 — Scenario 결정 + EndingTone 결정 + risk_level 산출.
다른 모듈이 이 파일에만 의존하도록 단일 책임 유지.
"""

from __future__ import annotations

import logging
from typing import Literal

VERSION = "2.0.0"

logger = logging.getLogger(__name__)

# ── 타입 정의 ────────────────────────────────────────────────────────────────
ScenarioType = Literal["ONE_VS_ONE", "NO_BATTLE", "ALLIANCE"]
EndingTone   = Literal["OPTIMISTIC", "TENSE", "OMINOUS"]

# ── 결정 규칙 상수 ────────────────────────────────────────────────────────────
_ALLIANCE_RISK         = "HIGH"
_ALLIANCE_EVENT_TYPES  = frozenset({"BATTLE", "SHOCK"})
_NO_BATTLE_RISK        = "LOW"
_NO_BATTLE_EVENT_TYPES = frozenset({"NORMAL", "INTEL"})

_OMINOUS_OUTCOMES = frozenset({"SYSTEM_COLLAPSE", "HERO_DEFEAT"})
_TENSE_OUTCOMES   = frozenset({"DRAW", "VILLAIN_TEMP_VICTORY"})


def select_scenario(risk_level: str, event_type: str) -> ScenarioType:
    """
    risk_level × event_type 결정 트리.

        HIGH + (BATTLE|SHOCK) → ALLIANCE
        LOW  + (NORMAL|INTEL) → NO_BATTLE
        그 외                 → ONE_VS_ONE (기본값)

    Args:
        risk_level: "LOW" | "MEDIUM" | "HIGH" (대소문자 무관)
        event_type: 7종 중 하나 (대소문자 무관)

    Returns:
        ScenarioType 문자열
    """
    rl = (risk_level or "MEDIUM").upper()
    et = (event_type or "NORMAL").upper()

    if rl == _ALLIANCE_RISK and et in _ALLIANCE_EVENT_TYPES:
        result: ScenarioType = "ALLIANCE"
    elif rl == _NO_BATTLE_RISK and et in _NO_BATTLE_EVENT_TYPES:
        result = "NO_BATTLE"
    else:
        result = "ONE_VS_ONE"

    logger.debug("[ScenarioSelector v%s] risk=%s event=%s → %s", VERSION, rl, et, result)
    return result


def select_ending_tone(
    scenario: ScenarioType,
    outcome: str,
    risk_level: str,
) -> EndingTone:
    """
    Scenario × Outcome × RiskLevel → EndingTone 결정.

    규칙:
        NO_BATTLE                              → OPTIMISTIC (항상)
        SYSTEM_COLLAPSE | HERO_DEFEAT          → OMINOUS
        ALLIANCE + PYRRHIC_VICTORY             → OMINOUS
        HIGH risk + VILLAIN_TEMP_VICTORY       → OMINOUS
        DRAW | VILLAIN_TEMP_VICTORY            → TENSE
        그 외                                  → OPTIMISTIC

    Args:
        scenario:   ScenarioType
        outcome:    battle_result.outcome 값
        risk_level: "LOW" | "MEDIUM" | "HIGH"

    Returns:
        EndingTone 문자열
    """
    if scenario == "NO_BATTLE":
        return "OPTIMISTIC"

    rl = (risk_level or "MEDIUM").upper()

    if outcome in _OMINOUS_OUTCOMES:
        return "OMINOUS"
    if scenario == "ALLIANCE" and outcome == "PYRRHIC_VICTORY":
        return "OMINOUS"
    if rl == "HIGH" and outcome == "VILLAIN_TEMP_VICTORY":
        return "OMINOUS"
    if outcome in _TENSE_OUTCOMES:
        return "TENSE"

    return "OPTIMISTIC"


def compute_risk_level_from_delta(delta: dict) -> str:
    """
    delta 데이터에서 직접 risk_level 계산 (옵션 B — ICG 자체 계산).

    run_market.py의 step_analysis()에서 delta가 이미 계산된 상태이므로
    별도 DB 조회 없이 안정적으로 risk_level을 산출할 수 있다.

    Args:
        delta: compute(curr_row, prev_row) 결과 dict.
               {"VIX": {"curr": 22.5, "pct": ...}, "WTI": {"curr": 85, ...}, ...}

    Returns:
        "LOW" | "MEDIUM" | "HIGH"
    """
    vix = delta.get("VIX", {}).get("curr", 0) or 0
    wti = delta.get("WTI", {}).get("curr", 0) or 0

    if vix >= 30 or wti >= 100:
        rl = "HIGH"
    elif vix >= 20 or wti >= 70:
        rl = "MEDIUM"
    else:
        rl = "LOW"

    logger.info(
        "[ScenarioSelector v%s] risk_level 자체 계산: VIX=%.1f WTI=%.1f → %s",
        VERSION, vix, wti, rl,
    )
    return rl
