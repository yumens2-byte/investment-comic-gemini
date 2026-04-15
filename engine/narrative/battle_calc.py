"""
engine/narrative/battle_calc.py
EDT Battle Engine v2.4 이식.

원칙:
- 순수 함수 (pure function) — 외부 상태 없음. 같은 입력 → 같은 출력.
- Claude는 이 결과를 '해석'만 한다. 승패 결과를 Claude가 변경하는 것은 BattleOverride 예외.
- doc 07: Battle & Narrative Engine as Code 기반.
- doc 16a: balance 기반 6단계 outcome 테이블.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Outcome = Literal[
    "HERO_VICTORY",  # balance >= 30
    "HERO_TACTICAL_VICTORY",  # balance >= 10
    "DRAW",  # -5 ~ +9
    "VILLAIN_TEMP_VICTORY",  # -10 ~ -6
    "HERO_DEFEAT",  # -30 ~ -11
    "SYSTEM_COLLAPSE",  # <= -31
]

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

    def to_dict(self) -> dict:
        """Claude 컨텍스트 주입용 dict 변환."""
        return {
            "hero_id": self.hero_id,
            "villain_id": self.villain_id,
            "hero_power": self.hero_power,
            "villain_power": self.villain_power,
            "balance": self.balance,
            "outcome": self.outcome,
            "hero_power_breakdown": self.hero_power_breakdown,
            "villain_power_breakdown": self.villain_power_breakdown,
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
    except Exception:
        _hero_cfg = {}

    # ── 캐릭터별 특수 시너지 ──────────────────────────────────────────────────
    if hero_id == "CHAR_HERO_003" and market_context.get("oil_shock"):
        breakdown["oil_synergy"] = _hero_cfg.get("oil_synergy", 8)

    if hero_id == "CHAR_HERO_005" and market_context.get("vix", 0) > 30:
        breakdown["defensive_mode"] = _hero_cfg.get("oil_synergy", 12)

    if hero_id == "CHAR_HERO_001" and market_context.get("system_stress", False):
        breakdown["systemic_resolve"] = _hero_cfg.get("oil_synergy", 10)

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
    balance → Outcome 변환 테이블 (doc 16a 기준).

    balance >= 30:        HERO_VICTORY
    10 <= balance < 30:   HERO_TACTICAL_VICTORY
    -5 <= balance < 10:   DRAW
    -10 <= balance < -5:  VILLAIN_TEMP_VICTORY
    -30 <= balance < -10: HERO_DEFEAT
    balance < -30:        SYSTEM_COLLAPSE
    """
    if balance >= 30:
        return "HERO_VICTORY"
    if balance >= 10:
        return "HERO_TACTICAL_VICTORY"
    if balance >= -5:
        return "DRAW"
    if balance >= -10:
        return "VILLAIN_TEMP_VICTORY"
    if balance >= -30:
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
