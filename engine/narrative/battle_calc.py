"""
engine/narrative/battle_calc.py
EDT Battle Engine v2.4 이식.

원칙:
- 순수 함수 (pure function) — 외부 상태 없음. 같은 입력 → 같은 출력.
- Claude는 이 결과를 '해석'만 한다. 승패 결과를 Claude가 변경하는 것은 BattleOverride 예외.
- doc 07: Battle & Narrative Engine as Code 기반.
- doc 16a: balance 기반 6단계 outcome 테이블.

v2.0 변경사항 (2026-04-18):
- Outcome에 PEACEFUL_GROWTH (NO_BATTLE 전용), PYRRHIC_VICTORY (ALLIANCE 전용) 추가
- battle_alliance() 함수 추가 — hero 2명 연합 vs villain 1명 강적
- resolve_alliance_outcome() 함수 추가 — ALLIANCE 전용 판정 (HERO_TACTICAL_VICTORY → PYRRHIC_VICTORY 재지정)

v2.3 변경사항 (2026-05-14, Phase 2.3):
- crowd_momentum_modifier() — RULE CM-01 (G08, EDT 04 v2.12)
- villain_signature_bonus() — RULE VS-01~05 (G09, EDT 04 v2.10)
- emergence_information_deficit() — RULE EMR-01 (G09)
- emergence_outcome_demotion() — RULE EMR-02 (G09)
- 모두 Feature Flag로 가드 (기본값 OFF, 후방 호환)
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Literal

logger = logging.getLogger(__name__)

Outcome = Literal[
    "HERO_VICTORY",           # balance >= 30
    "HERO_TACTICAL_VICTORY",  # balance >= 10  (ONE_VS_ONE 전용)
    "DRAW",                   # -5 ~ +9
    "VILLAIN_TEMP_VICTORY",   # -10 ~ -6
    "HERO_DEFEAT",            # -30 ~ -11
    "SYSTEM_COLLAPSE",        # <= -31
    "PEACEFUL_GROWTH",        # v2.0 — NO_BATTLE 전용, balance 없음
    "PYRRHIC_VICTORY",        # v2.0 — ALLIANCE 전용, balance 10~29
]

# ── Phase 2.3 신규 상수 (G08, G09) ─────────────────────────────────────────

# RULE CM-01: crowd_momentum Modifier 변환비 + 상한
# ICG는 crowd_momentum 범위 -20~+20 (F&G 기반) → EDT (-10~+10)의 2배 범위
# EDT 공식: modifier = cm / 2, 상한 ±5
# ICG 적용: modifier = round(cm / 4), 상한 ±5 (EDT와 동일한 효과 크기 유지)
_CROWD_MOMENTUM_DIVISOR = 4
_CROWD_MOMENTUM_MAX_ABS = 5

# RULE VS-01: Villain Signature Bonus by Level
# ICG의 villain_signature는 int (1/2/3)이므로 Level별 Power Bonus 매핑
_VILLAIN_SIGNATURE_BONUS_TABLE: dict[int, int] = {
    1: 0,    # Dormant/Normal
    2: 8,    # Active/Escalating
    3: 18,   # Critical/Strengthened
}

# RULE EMR-01: EMERGENCE Information Deficit
_EMERGENCE_DEFICIT_DAY_1 = -10
_EMERGENCE_DEFICIT_DAY_2 = -5


# 빌런 Canon 이름 목록 (RULE 06)
CANON_VILLAIN_NAMES: set[str] = {
    "Oil Shock Titan",
    "Debt Titan",
    "Liquidity Leviathan",
    "Volatility Hydra",
    "Algorithm Reaper",
    "War Dominion",
}

# 히어로 Canon ID 목록
CANON_HERO_IDS: set[str] = {
    "CHAR_HERO_001",
    "CHAR_HERO_002",
    "CHAR_HERO_003",
    "CHAR_HERO_004",
    "CHAR_HERO_005",
}

# 빌런 Canon ID 목록
CANON_VILLAIN_IDS: set[str] = {
    "CHAR_VILLAIN_001",
    "CHAR_VILLAIN_002",
    "CHAR_VILLAIN_003",
    "CHAR_VILLAIN_004",
    "CHAR_VILLAIN_005",
    "CHAR_VILLAIN_006",
}


@dataclass(frozen=True)
class BattleResult:
    """전투 계산 결과. 불변(frozen) 데이터클래스 — Claude가 임의 수정 불가."""

    hero_id: str
    villain_id: str
    hero_power: int
    villain_power: int
    balance: int
    outcome: Outcome
    hero_power_breakdown: dict[str, int]
    villain_power_breakdown: dict[str, int]
    villain_ids: list[str] | None = None
    villain_power_breakdown_by_id: dict[str, dict[str, int]] | None = None
    encounter_type: str = "SINGLE_VILLAIN"
    villain_pact_state: str = "NONE"

    def to_dict(self) -> dict:
        """Claude 컨텍스트 주입용 dict 변환."""
        return {
            "hero_id": self.hero_id,
            "villain_id": self.villain_id,
            "villain_ids": self.villain_ids or [self.villain_id],
            "hero_power": self.hero_power,
            "villain_power": self.villain_power,
            "balance": self.balance,
            "outcome": self.outcome,
            "hero_power_breakdown": self.hero_power_breakdown,
            "villain_power_breakdown": self.villain_power_breakdown,
            "villain_power_breakdown_by_id": self.villain_power_breakdown_by_id or {self.villain_id: self.villain_power_breakdown},
            "encounter_type": self.encounter_type,
            "villain_pact_state": self.villain_pact_state,
        }


def calc_hero_power(
    hero_id: str,
    base: int,
    market_context: dict,
    arc_context: dict,
    form_bonus: int = 0,
) -> tuple[int, dict[str, int]]:
    """
    히어로 전투력 계산.

    Args:
        hero_id: 캐릭터 ID (예: CHAR_HERO_003).
        base: characters.yaml의 base_power.
        market_context: 시장 지표 딕셔너리.
            - oil_shock (bool): 유가 쇼크 여부
            - vix (float): 현재 VIX
            - wti_pct_3d (float): WTI 3일 변화율(%)
        arc_context: 에피소드 연속성 정보.
            - tension (int): 누적 긴장도 (0~100)
        form_bonus: 폼 각성 보너스 (기본 0).

    Returns:
        (총 전투력, 세부 breakdown dict)
    """
    breakdown: dict[str, int] = {"base": base}

    # 보너스 상수 — Notion에서 로드 (실패 시 기본값 사용)
    try:
        from engine.common.notion_loader import load_battle_constants

        _bc = load_battle_constants()
        _hero_cfg = _bc.get("HERO_BONUS_TABLE", {}).get(hero_id, {})
        # CHARACTER_BASE_POWER와 혼재 방지: int가 반환되면 빈 dict로 교체
        if not isinstance(_hero_cfg, dict):
            _hero_cfg = {}
    except Exception:
        _hero_cfg = {}

    # ── 캐릭터별 특수 시너지 ──────────────────────────────────────────────────
    if hero_id == "CHAR_HERO_003" and market_context.get("oil_shock"):
        breakdown["oil_synergy"] = _hero_cfg.get("oil_synergy", 8)

    if hero_id == "CHAR_HERO_005" and market_context.get("vix", 0) > 30:
        breakdown["defensive_mode"] = _hero_cfg.get("defensive_mode_bonus", 12)

    if hero_id == "CHAR_HERO_001" and market_context.get("system_stress", False):
        breakdown["systemic_resolve"] = _hero_cfg.get("systemic_resolve_bonus", 10)

    # ── Arc 긴장도 보너스 ────────────────────────────────────────────────────
    if arc_context.get("tension", 0) >= 75:
        breakdown["high_tension"] = _hero_cfg.get("high_tension_bonus", 5)
    elif arc_context.get("tension", 0) >= 50:
        breakdown["moderate_tension"] = 2

    # ── 폼 보너스 ────────────────────────────────────────────────────────────
    if form_bonus:
        breakdown["form_bonus"] = form_bonus

    total = sum(breakdown.values())
    return total, breakdown


def calc_villain_power(
    villain_id: str,
    base: int,
    market_context: dict,
) -> tuple[int, dict[str, int]]:
    """
    빌런 전투력 계산.

    Args:
        villain_id: 캐릭터 ID (예: CHAR_VILLAIN_002).
        base: characters.yaml의 base_power.
        market_context: 시장 지표 딕셔너리.
            - wti_pct_3d (float): WTI 3일 변화율(%)
            - vix (float): 현재 VIX
            - dgs10 (float): 미국 10년 국채 금리(%)
            - hy_spread (float): HY 스프레드(bp)

    Returns:
        (총 전투력, 세부 breakdown dict)
    """
    breakdown: dict[str, int] = {"base": base}

    # CHAR_VILLAIN_002 (Oil Shock Titan): WTI 3일 변화율 × 1.5, 최대 +25
    if villain_id == "CHAR_VILLAIN_002":
        wti_delta = market_context.get("wti_pct_3d", 0)
        oil_bonus = min(int(abs(wti_delta) * 1.5), 25)
        if oil_bonus > 0:
            breakdown["oil_intensity"] = oil_bonus

    # CHAR_VILLAIN_004 (Volatility Hydra): (VIX - 20) × 1.2
    if villain_id == "CHAR_VILLAIN_004":
        vix = market_context.get("vix", 0)
        if vix > 20:
            breakdown["vix_amp"] = max(0, int((vix - 20) * 1.2))

    # CHAR_VILLAIN_001 (Debt Titan): 금리 상승 시 보너스
    if villain_id == "CHAR_VILLAIN_001":
        dgs10 = market_context.get("dgs10", 0)
        if dgs10 > 4.8:
            breakdown["rate_surge"] = min(int((dgs10 - 4.8) * 20), 20)

    # CHAR_VILLAIN_003 (Liquidity Leviathan): HY 스프레드 급등 시 보너스
    if villain_id == "CHAR_VILLAIN_003":
        hy_spread = market_context.get("hy_spread", 0)
        if hy_spread > 500:
            breakdown["credit_panic"] = min(int((hy_spread - 500) / 50), 15)

    total = sum(breakdown.values())
    return total, breakdown


def resolve_outcome(balance: int) -> Outcome:
    """
    balance → Outcome 변환 테이블.
    임계값은 Notion battle_constants에서 로드 (fallback: 하드코딩 제거됨).
    """
    try:
        from engine.common.notion_loader import load_battle_constants

        _bc = load_battle_constants()
        _thr = _bc.get("OUTCOME_THRESHOLDS", {})
        hero_v = _thr.get("HERO_VICTORY", 30)
        hero_tv = _thr.get("HERO_TACTICAL_VICTORY", 10)
        draw_l = _thr.get("DRAW_LOWER", -5)
        villain_tv = _thr.get("VILLAIN_TEMP_VICTORY", -10)
        hero_d = _thr.get("HERO_DEFEAT", -30)
    except Exception:
        hero_v, hero_tv, draw_l, villain_tv, hero_d = 30, 10, -5, -10, -30

    if balance >= hero_v:
        return "HERO_VICTORY"
    if balance >= hero_tv:
        return "HERO_TACTICAL_VICTORY"
    if balance >= draw_l:
        return "DRAW"
    if balance >= villain_tv:
        return "VILLAIN_TEMP_VICTORY"
    if balance >= hero_d:
        return "HERO_DEFEAT"
    return "SYSTEM_COLLAPSE"


def battle(
    hero_id: str,
    hero_base: int,
    villain_id: str,
    villain_base: int,
    market_context: dict,
    arc_context: dict,
    form_bonus: int = 0,
) -> BattleResult:
    """
    전투 계산 진입점. 순수 함수.

    Args:
        hero_id: 히어로 캐릭터 ID.
        hero_base: 히어로 base_power (characters.yaml).
        villain_id: 빌런 캐릭터 ID.
        villain_base: 빌런 base_power (characters.yaml).
        market_context: 시장 지표.
        arc_context: 에피소드 연속성 정보.
        form_bonus: 폼 각성 보너스.

    Returns:
        BattleResult — Claude에 '변경 불가 입력'으로 전달.

    Raises:
        ValueError: hero_id 또는 villain_id가 Canon 외 값인 경우.
    """
    from engine.common.exceptions import UnknownCharacterError

    if hero_id not in CANON_HERO_IDS:
        raise UnknownCharacterError(hero_id)
    if villain_id not in CANON_VILLAIN_IDS:
        raise UnknownCharacterError(villain_id)

    hero_power, hero_breakdown = calc_hero_power(
        hero_id, hero_base, market_context, arc_context, form_bonus
    )
    villain_power, villain_breakdown = calc_villain_power(villain_id, villain_base, market_context)

    balance = hero_power - villain_power
    outcome = resolve_outcome(balance)

    return BattleResult(
        hero_id=hero_id,
        villain_id=villain_id,
        hero_power=hero_power,
        villain_power=villain_power,
        balance=balance,
        outcome=outcome,
        hero_power_breakdown=hero_breakdown,
        villain_power_breakdown=villain_breakdown,
    )


def select_characters_for_event(
    event_type: str,
    delta: dict,
) -> tuple[str, str]:
    """
    event_type + delta 기반으로 히어로/빌런 자동 선택.

    Returns:
        (hero_id, villain_id) 튜플.
    """
    # 빌런 선택 로직
    villain_id: str
    if event_type in ("BATTLE", "SHOCK"):
        wti_pct = delta.get("WTI", {}).get("pct", 0)
        vix_curr = delta.get("VIX", {}).get("curr", 0)
        dgs10_curr = delta.get("DGS10", {}).get("curr", 0)

        if wti_pct >= 5:
            villain_id = "CHAR_VILLAIN_002"  # Oil Shock Titan
        elif vix_curr > 28:
            villain_id = "CHAR_VILLAIN_004"  # Volatility Hydra
        elif dgs10_curr > 4.8:
            villain_id = "CHAR_VILLAIN_001"  # Debt Titan
        else:
            villain_id = "CHAR_VILLAIN_004"  # 기본: Volatility Hydra
    elif event_type == "AFTERMATH":
        villain_id = "CHAR_VILLAIN_003"  # Liquidity Leviathan
    else:
        villain_id = "CHAR_VILLAIN_005"  # Algorithm Reaper (INTEL/NORMAL)

    # 히어로 선택 로직 — 빌런에 대응하는 히어로
    _villain_to_hero: dict[str, str] = {
        "CHAR_VILLAIN_001": "CHAR_HERO_002",  # Debt Titan → Iron Nuna
        "CHAR_VILLAIN_002": "CHAR_HERO_003",  # Oil Shock Titan → Leverage
        "CHAR_VILLAIN_003": "CHAR_HERO_005",  # Liquidity Leviathan → Gold Bond
        "CHAR_VILLAIN_004": "CHAR_HERO_001",  # Volatility Hydra → EDT
        "CHAR_VILLAIN_005": "CHAR_HERO_001",  # Algorithm Reaper → EDT
        "CHAR_VILLAIN_006": "CHAR_HERO_004",  # War Dominion → Futures Girl
    }
    hero_id = _villain_to_hero.get(villain_id, "CHAR_HERO_001")

    return hero_id, villain_id


# ── v2.0 신규: ALLIANCE 전투 계산 ─────────────────────────────────────────────


def resolve_alliance_outcome(balance: int) -> Outcome:
    """
    ALLIANCE Outcome 결정.

    ONE_VS_ONE 대비 핵심 차이:
        balance 10~29 → PYRRHIC_VICTORY (HERO_TACTICAL_VICTORY 대신)
        → "이겼지만 큰 대가" 서사를 담기 위한 ALLIANCE 전용 판정.

    Args:
        balance: hero_power - villain_power 결과값.

    Returns:
        Outcome — HERO_TACTICAL_VICTORY 절대 반환 안 함.
    """
    if balance >= 30:
        return "HERO_VICTORY"
    elif balance >= 10:
        return "PYRRHIC_VICTORY"       # 🆕 ALLIANCE 전용
    elif balance >= -5:
        return "DRAW"
    elif balance >= -10:
        return "VILLAIN_TEMP_VICTORY"
    elif balance >= -30:
        return "HERO_DEFEAT"
    else:
        return "SYSTEM_COLLAPSE"


def battle_alliance(
    hero_ids: list[str],
    hero_bases: list[int],
    villain_id: str,
    villain_base: int,
    market_context: dict,
    arc_context: dict,
) -> BattleResult:
    """
    ALLIANCE 전투 계산.

    설계 의도:
        - hero 2명 연합 → 시너지 감쇠 0.85 적용 (연합은 완벽하지 않다)
        - villain은 1.25 강화 적용 (ALLIANCE가 발동될 만큼 강한 적)
        - resolve_alliance_outcome으로 PYRRHIC_VICTORY 판정

    Args:
        hero_ids:       히어로 ID 리스트 (2개, [main_hero, support_hero])
        hero_bases:     각 히어로 base_power 리스트 (hero_ids와 동일 순서)
        villain_id:     빌런 ID
        villain_base:   빌런 base_power
        market_context: 시장 지표
        arc_context:    에피소드 연속성 정보

    Returns:
        BattleResult — hero_id는 hero_ids[0] (후방 호환)

    Raises:
        ValueError: villain_id가 Canon 외 값인 경우
        ValueError: hero_ids가 CANON_HERO_IDS 외 값 포함 시
    """
    from engine.common.exceptions import UnknownCharacterError

    # Canon 검증
    for h_id in hero_ids:
        if h_id not in CANON_HERO_IDS:
            raise UnknownCharacterError(h_id)
    if villain_id not in CANON_VILLAIN_IDS:
        raise UnknownCharacterError(villain_id)

    # 히어로 개별 전투력 계산
    hero_results = [
        calc_hero_power(h_id, h_base, market_context, arc_context)
        for h_id, h_base in zip(hero_ids, hero_bases)
    ]
    total_raw = sum(power for power, _ in hero_results)

    # 연합 시너지 감쇠 0.85 적용
    hero_power = int(total_raw * 0.85)

    # 합산 breakdown (키 충돌 시 합산)
    combined_hero_breakdown: dict[str, int] = {}
    for _, bd in hero_results:
        for k, v in bd.items():
            combined_hero_breakdown[k] = combined_hero_breakdown.get(k, 0) + v
    # 감쇠 반영 표시
    combined_hero_breakdown["alliance_decay"] = -(total_raw - hero_power)

    # 빌런 강화 1.25 적용
    villain_power_raw, villain_breakdown = calc_villain_power(
        villain_id, villain_base, market_context
    )
    villain_power = int(villain_power_raw * 1.25)
    villain_breakdown = dict(villain_breakdown)  # frozen dict 방어 복사
    villain_breakdown["alliance_threat_bonus"] = villain_power - villain_power_raw

    balance = hero_power - villain_power
    outcome = resolve_alliance_outcome(balance)

    return BattleResult(
        hero_id=hero_ids[0],              # 후방 호환: 주 히어로 ID
        villain_id=villain_id,
        hero_power=hero_power,
        villain_power=villain_power,
        balance=balance,
        outcome=outcome,
        hero_power_breakdown=combined_hero_breakdown,
        villain_power_breakdown=villain_breakdown,
    )


def battle_multi_villain(
    hero_ids: list[str],
    hero_bases: list[int],
    villain_ids: list[str],
    villain_bases: list[int],
    market_context: dict,
    arc_context: dict,
) -> BattleResult:
    """Calculate a deterministic encounter with one primary and optional support villains.

    The first villain is the primary threat. Support villains are decayed to avoid
    runaway power inflation and the combined villain power is capped at 1.75x the
    primary villain power.
    """
    from engine.common.exceptions import UnknownCharacterError

    if not hero_ids:
        raise UnknownCharacterError("MISSING_HERO")
    if not villain_ids:
        raise UnknownCharacterError("MISSING_VILLAIN")
    for h_id in hero_ids:
        if h_id not in CANON_HERO_IDS:
            raise UnknownCharacterError(h_id)
    for v_id in villain_ids:
        if v_id not in CANON_VILLAIN_IDS:
            raise UnknownCharacterError(v_id)

    hero_results = [
        calc_hero_power(h_id, h_base, market_context, arc_context)
        for h_id, h_base in zip(hero_ids, hero_bases)
    ]
    hero_raw = sum(power for power, _ in hero_results)
    hero_power = int(hero_raw * 0.85) if len(hero_ids) > 1 else hero_raw
    hero_breakdown: dict[str, int] = {}
    for _, bd in hero_results:
        for k, v in bd.items():
            hero_breakdown[k] = hero_breakdown.get(k, 0) + v
    if len(hero_ids) > 1:
        hero_breakdown["alliance_decay"] = -(hero_raw - hero_power)

    villain_breakdown_by_id: dict[str, dict[str, int]] = {}
    adjusted_villain_powers: list[int] = []
    raw_villain_powers: list[int] = []
    for idx, (v_id, v_base) in enumerate(zip(villain_ids, villain_bases)):
        raw_power, bd = calc_villain_power(v_id, v_base, market_context)
        raw_villain_powers.append(raw_power)
        adjusted = raw_power if idx == 0 else int(raw_power * 0.60)
        bd = dict(bd)
        if idx > 0:
            bd["support_decay"] = adjusted - raw_power
        adjusted_villain_powers.append(adjusted)
        villain_breakdown_by_id[v_id] = bd

    pact_bonus = 0
    if len(villain_ids) > 1:
        pact_bonus = min(10, 5 * (len(villain_ids) - 1))
    villain_power_uncapped = sum(adjusted_villain_powers) + pact_bonus
    primary_power = raw_villain_powers[0]
    cap = int(primary_power * 1.75)
    villain_power = min(villain_power_uncapped, cap)

    combined_villain_breakdown: dict[str, int] = {"primary": adjusted_villain_powers[0]}
    for idx, power in enumerate(adjusted_villain_powers[1:], 1):
        combined_villain_breakdown[f"support_{idx}"] = power
    if pact_bonus:
        combined_villain_breakdown["villain_pact_bonus"] = pact_bonus
    if villain_power < villain_power_uncapped:
        combined_villain_breakdown["villain_power_cap"] = villain_power - villain_power_uncapped

    balance = hero_power - villain_power
    outcome = resolve_alliance_outcome(balance) if len(hero_ids) > 1 else resolve_outcome(balance)
    return BattleResult(
        hero_id=hero_ids[0],
        villain_id=villain_ids[0],
        hero_power=hero_power,
        villain_power=villain_power,
        balance=balance,
        outcome=outcome,
        hero_power_breakdown=hero_breakdown,
        villain_power_breakdown=combined_villain_breakdown,
        villain_ids=villain_ids,
        villain_power_breakdown_by_id=villain_breakdown_by_id,
        encounter_type="MULTI_VILLAIN" if len(villain_ids) > 1 else "SINGLE_VILLAIN",
        villain_pact_state="DUAL_PRESSURE" if len(villain_ids) > 1 else "NONE",
    )

# ════════════════════════════════════════════════════════════════════════════
# Phase 2.3 신규 Modifier 함수 (G08, G09)
# 기존 battle() / battle_alliance() 결과를 보강.
# Feature Flag로 가드 — 미활성 시 0 반환 (배틀 결과 변경 없음).
# ════════════════════════════════════════════════════════════════════════════


def crowd_momentum_modifier(crowd_momentum: int) -> int:
    """
    RULE CM-01 — crowd_momentum을 Hero Power 보정값으로 변환.

    EDT 04 v2.12 공식 (ICG 범위 -20~+20 적응):
        modifier = round(crowd_momentum / 4)
        clamp: -5 ~ +5

    Feature Flag: CROWD_MODIFIER_ENABLED

    Args:
        crowd_momentum: 현재 arc_state.crowd_momentum (-20 ~ +20)

    Returns:
        Hero Power에 더할 정수 (-5 ~ +5). 미활성 시 0.
    """
    if os.environ.get("CROWD_MODIFIER_ENABLED", "false").lower() != "true":
        return 0
    raw = round(crowd_momentum / _CROWD_MOMENTUM_DIVISOR)
    return max(-_CROWD_MOMENTUM_MAX_ABS, min(_CROWD_MOMENTUM_MAX_ABS, raw))


def villain_signature_bonus(villain_signature: int) -> int:
    """
    RULE VS-01 — villain_signature Level → Villain Power Bonus.

    매핑 (EDT 02 v2.19 기반):
        Lv.1 (Normal/Dormant):    +0
        Lv.2 (Active/Escalating): +8
        Lv.3 (Critical):          +18

    Feature Flag: VILLAIN_SIGNATURE_BONUS_ENABLED

    Args:
        villain_signature: arc_state.villain_signature (1/2/3)

    Returns:
        Villain Power에 더할 정수. 미활성 시 0.
    """
    if os.environ.get("VILLAIN_SIGNATURE_BONUS_ENABLED", "false").lower() != "true":
        return 0
    return _VILLAIN_SIGNATURE_BONUS_TABLE.get(int(villain_signature or 1), 0)


def emergence_information_deficit(arc_context: dict, episode_type: str) -> int:
    """
    RULE EMR-01 — EMERGENCE Information Deficit.

    EMERGENCE 에피소드 또는 직후 1 EP 잔류 기간에 Hero Power 감산.
        EMERGENCE 당일:        -10
        emergence_deficit_days >= 2: -10
        emergence_deficit_days == 1: -5
        그 외:                  0

    Feature Flag: EMERGENCE_DEFICIT_ENABLED

    Args:
        arc_context:  build_arc_context() 결과 (emergence_deficit_days 포함)
        episode_type: 이번 에피소드 타입

    Returns:
        Hero Power에 더할 음수 또는 0. 미활성 시 0.
    """
    if os.environ.get("EMERGENCE_DEFICIT_ENABLED", "false").lower() != "true":
        return 0
    if episode_type == "EMERGENCE":
        return _EMERGENCE_DEFICIT_DAY_1
    days = arc_context.get("emergence_deficit_days") or 0
    if days >= 2:
        return _EMERGENCE_DEFICIT_DAY_1
    if days == 1:
        return _EMERGENCE_DEFICIT_DAY_2
    return 0


def emergence_outcome_demotion(balance: int, episode_type: str) -> tuple[int, str]:
    """
    RULE EMR-02 — EMERGENCE 타입 OUTCOME 격하 (1단계).

    Arc 첫날 완벽 승리는 서사 현실감 저하 → 1단계 격하.
        Balance >= +30   → HERO_TACTICAL_VICTORY
        Balance +10~+29  → DRAW
        Balance -4~+9    → HERO_DEFEAT
        그 이하          → 유지

    Args:
        balance:      battle balance
        episode_type: 에피소드 타입

    Returns:
        (보정된 balance, 격하 사유).
        EMERGENCE 아니거나 Feature Flag OFF면 (원본 balance, "")
    """
    if os.environ.get("EMERGENCE_DEFICIT_ENABLED", "false").lower() != "true":
        return balance, ""
    if episode_type != "EMERGENCE":
        return balance, ""

    if balance >= 30:
        # HERO_VICTORY → HERO_TACTICAL_VICTORY (balance 29로 격하)
        return 29, "EMR-02: Victory → Tactical (EMERGENCE 첫날)"
    if balance >= 10:
        # HERO_TACTICAL_VICTORY → DRAW (balance 9로 격하)
        return 9, "EMR-02: Tactical → Draw (EMERGENCE 첫날)"
    if balance >= -4:
        # DRAW → HERO_DEFEAT (balance -11로 격하)
        return -11, "EMR-02: Draw → Defeat (EMERGENCE 첫날)"
    return balance, ""


def apply_v23_modifiers(
    result: BattleResult,
    arc_context: dict,
    episode_type: str,
) -> BattleResult:
    """
    기존 battle() / battle_alliance() 결과에 Phase 2.3 Modifier 3종을 후처리 적용.

    적용 순서 (EDT 04 v2.12 STEP 4~8 준용):
        STEP 4 (G09):   Villain Signature Bonus → Villain Power
        STEP 4 (G09):   EMERGENCE Information Deficit → Hero Power
        STEP 4.5 (G08): crowd_momentum Modifier → Hero Power
        STEP 5:         Battle Balance = Hero - Villain
        STEP 8:         EMERGENCE OUTCOME Demotion → Outcome 재산출

    Feature Flag 모두 OFF 시 입력 result를 그대로 반환.

    Args:
        result:       battle() 또는 battle_alliance() 결과
        arc_context:  build_arc_context() 결과
        episode_type: 결정된 에피소드 타입 (EMERGENCE 등)

    Returns:
        보정된 BattleResult (불변 객체이므로 새 인스턴스).
    """
    # 모든 Flag OFF면 입력 그대로
    if (
        os.environ.get("CROWD_MODIFIER_ENABLED", "false").lower() != "true"
        and os.environ.get("VILLAIN_SIGNATURE_BONUS_ENABLED", "false").lower() != "true"
        and os.environ.get("EMERGENCE_DEFICIT_ENABLED", "false").lower() != "true"
    ):
        return result

    new_hero_power = result.hero_power
    new_villain_power = result.villain_power
    new_hero_bd = dict(result.hero_power_breakdown)
    new_villain_bd = dict(result.villain_power_breakdown)

    # ── G09: Villain Signature Bonus ─────────────────────────────────────
    vs_bonus = villain_signature_bonus(arc_context.get("villain_signature", 1) or 1)
    if vs_bonus:
        new_villain_power += vs_bonus
        new_villain_bd["villain_signature"] = vs_bonus
        logger.info(
            "[BattleCalc v2.3] STEP 4 — Villain Signature Bonus +%d "
            "(Lv.%d)", vs_bonus, arc_context.get("villain_signature", 1) or 1,
        )

    # ── G09: EMERGENCE Information Deficit ───────────────────────────────
    deficit = emergence_information_deficit(arc_context, episode_type)
    if deficit:
        new_hero_power += deficit
        new_hero_bd["emergence_deficit"] = deficit
        logger.info(
            "[BattleCalc v2.3] STEP 4 — EMERGENCE Information Deficit %d", deficit,
        )

    # ── G08: crowd_momentum Modifier ─────────────────────────────────────
    cm_mod = crowd_momentum_modifier(arc_context.get("crowd_momentum", 0) or 0)
    if cm_mod:
        new_hero_power += cm_mod
        new_hero_bd["crowd_momentum"] = cm_mod
        logger.info(
            "[BattleCalc v2.3] STEP 4.5 — crowd_momentum Modifier %+d "
            "(arc.crowd=%d)",
            cm_mod, arc_context.get("crowd_momentum", 0) or 0,
        )

    # ── STEP 5: Balance 재산출 ───────────────────────────────────────────
    new_balance = new_hero_power - new_villain_power

    # ── STEP 8: EMERGENCE OUTCOME Demotion ───────────────────────────────
    demoted_balance, demote_reason = emergence_outcome_demotion(
        new_balance, episode_type
    )
    if demote_reason:
        new_balance = demoted_balance
        new_hero_bd["emergence_demotion"] = demote_reason
        logger.info("[BattleCalc v2.3] STEP 8 — %s", demote_reason)

    # ── Outcome 재판정 ───────────────────────────────────────────────────
    # ALLIANCE 시나리오 보존: 입력 outcome이 PYRRHIC이면 resolve_alliance_outcome 사용
    if result.outcome in ("PYRRHIC_VICTORY",) or (
        result.hero_power_breakdown.get("alliance_decay") is not None
    ):
        new_outcome = resolve_alliance_outcome(new_balance)
    elif result.outcome == "PEACEFUL_GROWTH":
        # NO_BATTLE은 Modifier 적용 안 함 (PEACEFUL_GROWTH 유지)
        new_outcome = "PEACEFUL_GROWTH"
    else:
        new_outcome = resolve_outcome(new_balance)

    return BattleResult(
        hero_id=result.hero_id,
        villain_id=result.villain_id,
        hero_power=new_hero_power,
        villain_power=new_villain_power,
        balance=new_balance,
        outcome=new_outcome,
        hero_power_breakdown=new_hero_bd,
        villain_power_breakdown=new_villain_bd,
    )
