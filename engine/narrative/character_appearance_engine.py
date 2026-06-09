"""
Character Appearance Engine v2.

점수 기반 히어로/빌런/중립 등장 판단을 담당한다. 기존 selector를 즉시
대체하지 않고 feature flag 배선에서만 사용될 수 있도록 순수 함수로 구성한다.
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

Faction = Literal["HERO", "VILLAIN", "NEUTRAL"]

HERO_PRIMARY_THRESHOLD = 60
HERO_SUPPORT_THRESHOLD = 45
HERO_NO_BATTLE_THRESHOLD = 50
VILLAIN_THRESHOLD = 60
VILLAIN_SUPPORT_THRESHOLD = 50
VILLAIN_SUPPORT_MAX_GAP = 25
NEUTRAL_THRESHOLD = 25

HERO_IDS = [
    "CHAR_HERO_001",
    "CHAR_HERO_002",
    "CHAR_HERO_003",
    "CHAR_HERO_004",
    "CHAR_HERO_005",
]

VILLAIN_IDS = [
    "CHAR_VILLAIN_001",
    "CHAR_VILLAIN_002",
    "CHAR_VILLAIN_003",
    "CHAR_VILLAIN_004",
    "CHAR_VILLAIN_005",
    "CHAR_VILLAIN_006",
]

VILLAIN_TO_COUNTER_HERO = {
    "CHAR_VILLAIN_001": "CHAR_HERO_002",
    "CHAR_VILLAIN_002": "CHAR_HERO_003",
    "CHAR_VILLAIN_003": "CHAR_HERO_005",
    "CHAR_VILLAIN_004": "CHAR_HERO_004",
    "CHAR_VILLAIN_005": "CHAR_HERO_001",
    "CHAR_VILLAIN_006": "CHAR_HERO_001",
}

VILLAIN_DOMAIN = {
    "CHAR_VILLAIN_001": "rates",
    "CHAR_VILLAIN_002": "commodity",
    "CHAR_VILLAIN_003": "liquidity",
    "CHAR_VILLAIN_004": "volatility",
    "CHAR_VILLAIN_005": "momentum",
    "CHAR_VILLAIN_006": "geopolitics",
}

LEGACY_VILLAIN_TO_HERO = {
    "CHAR_VILLAIN_001": "CHAR_HERO_002",
    "CHAR_VILLAIN_002": "CHAR_HERO_003",
    "CHAR_VILLAIN_003": "CHAR_HERO_005",
    "CHAR_VILLAIN_004": "CHAR_HERO_001",
    "CHAR_VILLAIN_005": "CHAR_HERO_001",
    "CHAR_VILLAIN_006": "CHAR_HERO_004",
}


@dataclass(frozen=True)
class CharacterAppearanceDecision:
    """단일 캐릭터 등장 판단 결과."""

    char_id: str
    faction: Faction
    appear: bool
    role: str
    score: int
    threshold: int
    rank: int = 0
    reasons: list[str] = field(default_factory=list)
    score_breakdown: dict[str, int] = field(default_factory=dict)
    metrics_used: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CharacterSelectionResult:
    """시나리오별 최종 캐릭터 선택 결과."""

    scenario_type: str
    event_type: str
    risk_level: str
    primary_hero: str
    support_heroes: list[str]
    primary_villain: str | None
    neutral_guests: list[CharacterAppearanceDecision]
    all_candidates: list[CharacterAppearanceDecision]
    selection_reason: str
    support_villains: list[str] = field(default_factory=list)
    villain_roles: dict[str, str] = field(default_factory=dict)
    villain_selection_reason: dict[str, str] = field(default_factory=dict)

    @property
    def heroes(self) -> list[str]:
        return [self.primary_hero, *self.support_heroes]

    @property
    def villains(self) -> list[str]:
        return [v for v in [self.primary_villain, *self.support_villains] if v]

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": "character-appearance-v2",
            "scenario_type": self.scenario_type,
            "event_type": self.event_type,
            "risk_level": self.risk_level,
            "primary_hero": self.primary_hero,
            "support_heroes": self.support_heroes,
            "heroes": self.heroes,
            "primary_villain": self.primary_villain,
            "support_villains": self.support_villains,
            "villains": self.villains,
            "villain_roles": self.villain_roles,
            "villain_selection_reason": self.villain_selection_reason,
            "neutral_guests": [d.to_dict() for d in self.neutral_guests],
            "all_candidates": [d.to_dict() for d in self.all_candidates],
            "selection_reason": self.selection_reason,
        }


def _metric(delta: dict, key: str, field: str = "curr", default: float = 0.0) -> float:
    val = delta.get(key, {}).get(field)
    if val is None:
        return default
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _add(
    breakdown: dict[str, int],
    reasons: list[str],
    key: str,
    score: int,
    reason: str,
) -> None:
    if score:
        breakdown[key] = breakdown.get(key, 0) + score
        reasons.append(reason)


def _decision(
    *,
    char_id: str,
    faction: Faction,
    role: str,
    threshold: int,
    breakdown: dict[str, int],
    reasons: list[str],
    metrics_used: dict[str, Any],
) -> CharacterAppearanceDecision:
    score = sum(breakdown.values())
    return CharacterAppearanceDecision(
        char_id=char_id,
        faction=faction,
        appear=score >= threshold,
        role=role,
        score=score,
        threshold=threshold,
        reasons=reasons,
        score_breakdown=breakdown,
        metrics_used=metrics_used,
    )


def score_villain(
    villain_id: str,
    delta: dict,
    event_type: str,
    arc_context: dict | None = None,
    recent_outcomes: list[str] | None = None,
) -> CharacterAppearanceDecision:
    """시장 delta 기반 빌런 후보 점수화."""
    arc_context = arc_context or {}
    recent_outcomes = recent_outcomes or []
    et = (event_type or "NORMAL").upper()
    wti_curr = _metric(delta, "WTI")
    wti_pct = _metric(delta, "WTI", "pct")
    vix_curr = _metric(delta, "VIX")
    vix_pct = _metric(delta, "VIX", "pct")
    dgs10_curr = _metric(delta, "DGS10")
    dgs10_pct = _metric(delta, "DGS10", "pct")
    hy_curr = _metric(delta, "HY_SPREAD")
    spy_pct = _metric(delta, "SPY", "pct")
    nasdaq_pct = _metric(delta, "NASDAQ", "pct")
    dxy_pct = _metric(delta, "DXY", "pct")
    usdkrw_pct = _metric(delta, "USDKRW", "pct")
    btc_pct = _metric(delta, "BTC", "pct")

    b: dict[str, int] = {}
    r: list[str] = []

    if villain_id == "CHAR_VILLAIN_001":
        if dgs10_curr >= 5.5:
            _add(b, r, "dgs10_lv3", 65, "DGS10 >= 5.5 Debt Titan critical trigger")
        elif dgs10_curr >= 5.0:
            _add(b, r, "dgs10_lv2", 50, "DGS10 >= 5.0 Debt Titan active trigger")
        elif dgs10_curr >= 4.8:
            _add(b, r, "dgs10_trigger", 40, "DGS10 >= 4.8 Debt Titan trigger")
        if hy_curr >= 500:
            _add(b, r, "hy_debt_stress", 25, "HY spread >= 500 reinforces debt stress")
        if dgs10_pct >= 5:
            _add(b, r, "rate_jump", 15, "DGS10 daily pct change >= 5%")
    elif villain_id == "CHAR_VILLAIN_002":
        if wti_pct >= 8:
            _add(b, r, "wti_pct_lv2", 60, "WTI pct >= 8 Oil Shock high trigger")
        elif wti_pct >= 5:
            _add(b, r, "wti_pct_trigger", 45, "WTI pct >= 5 Oil Shock trigger")
        if wti_curr >= 110:
            _add(b, r, "wti_abs_lv3", 60, "WTI >= 110 Oil Shock critical level")
        elif wti_curr >= 100:
            _add(b, r, "wti_abs_high", 40, "WTI >= 100 Oil Shock high level")
        elif wti_curr >= 90:
            _add(b, r, "wti_abs_active", 25, "WTI >= 90 Oil Shock active level")
    elif villain_id == "CHAR_VILLAIN_003":
        if hy_curr >= 700:
            _add(b, r, "hy_liquidity_critical", 70, "HY spread >= 700 Liquidity critical trigger")
        elif hy_curr >= 500:
            _add(b, r, "hy_liquidity_lv3", 50, "HY spread >= 500 Liquidity active trigger")
        elif hy_curr >= 400:
            _add(b, r, "hy_liquidity_lv2", 35, "HY spread >= 400 Liquidity watch trigger")
        if btc_pct <= -5:
            _add(b, r, "btc_liquidity_ripple", 15, "BTC <= -5% liquidity ripple")
        if dxy_pct >= 1:
            _add(b, r, "dxy_tightening", 10, "DXY >= +1% tightens liquidity")
        if usdkrw_pct >= 1:
            _add(b, r, "usdkrw_tightening", 10, "USDKRW >= +1% tightens offshore liquidity")
        if et == "AFTERMATH":
            _add(b, r, "aftermath_fit", 20, "AFTERMATH fits Liquidity Leviathan")
        if any(o in {"HERO_DEFEAT", "SYSTEM_COLLAPSE"} for o in recent_outcomes[:1]):
            _add(b, r, "post_defeat_liquidity", 15, "Recent severe outcome leaves liquidity scar")
    elif villain_id == "CHAR_VILLAIN_004":
        if vix_curr >= 40:
            _add(b, r, "vix_lv3", 70, "VIX >= 40 Volatility critical trigger")
        elif vix_curr >= 30:
            _add(b, r, "vix_lv2", 50, "VIX >= 30 Volatility active trigger")
        elif vix_curr >= 28:
            _add(b, r, "vix_trigger", 40, "VIX >= 28 Volatility trigger")
        if vix_pct >= 20:
            _add(b, r, "vix_spike", 25, "VIX pct >= 20 shock spike")
        if et == "SHOCK":
            _add(b, r, "shock_fit", 20, "SHOCK event fits Volatility Hydra")
        if spy_pct <= -2:
            _add(b, r, "spy_riskoff", 10, "SPY <= -2% reinforces volatility")
        if nasdaq_pct <= -2:
            _add(b, r, "nasdaq_riskoff", 10, "NASDAQ <= -2% reinforces volatility")
    elif villain_id == "CHAR_VILLAIN_005":
        if spy_pct <= -3:
            _add(b, r, "spy_cascade", 50, "SPY <= -3 Algorithm Reaper trigger")
        if nasdaq_pct <= -3:
            _add(b, r, "nasdaq_cascade", 40, "NASDAQ <= -3 Algorithm Reaper trigger")
        if vix_curr >= 35:
            _add(b, r, "vix_algo_lv3", 30, "VIX >= 35 supports algorithmic fear")
        elif vix_curr >= 28:
            _add(b, r, "vix_algo_lv2", 20, "VIX >= 28 supports algorithmic fear")
        if et == "INTEL":
            _add(b, r, "intel_uncertainty", 10, "INTEL episode allows data-shadow antagonist")
    elif villain_id == "CHAR_VILLAIN_006":
        if wti_curr >= 115:
            _add(b, r, "wti_war_lv3", 60, "WTI >= 115 War Dominion critical proxy")
        elif wti_curr >= 95:
            _add(b, r, "wti_war_lv2", 35, "WTI >= 95 War Dominion active proxy")
        if wti_pct >= 8:
            _add(b, r, "oil_geopolitical_proxy", 20, "WTI pct >= 8 can proxy geopolitical stress")
        if et == "BATTLE":
            _add(b, r, "battle_fit", 10, "BATTLE event supports War Dominion")

    if et == "BATTLE" and villain_id in {"CHAR_VILLAIN_001", "CHAR_VILLAIN_002", "CHAR_VILLAIN_005", "CHAR_VILLAIN_006"}:
        _add(b, r, "battle_event_fit", 10, "BATTLE event fit")

    sig = int(arc_context.get("villain_signature", 1) or 1)
    if sig == 3:
        _add(b, r, "arc_signature_lv3", 20, "Arc villain signature Lv.3")
    elif sig == 2:
        _add(b, r, "arc_signature_lv2", 10, "Arc villain signature Lv.2")

    return _decision(
        char_id=villain_id,
        faction="VILLAIN",
        role="PRIMARY_ANTAGONIST",
        threshold=VILLAIN_THRESHOLD,
        breakdown=b,
        reasons=r,
        metrics_used={
            "WTI.curr": wti_curr,
            "WTI.pct": wti_pct,
            "VIX.curr": vix_curr,
            "VIX.pct": vix_pct,
            "DGS10.curr": dgs10_curr,
            "HY_SPREAD.curr": hy_curr,
            "SPY.pct": spy_pct,
            "NASDAQ.pct": nasdaq_pct,
        },
    )


def score_hero(
    hero_id: str,
    delta: dict,
    scenario_type: str,
    event_type: str,
    villain_id: str | None,
    arc_context: dict | None = None,
) -> CharacterAppearanceDecision:
    """시장 delta + 시나리오 기반 히어로 후보 점수화."""
    arc_context = arc_context or {}
    st = (scenario_type or "ONE_VS_ONE").upper()
    et = (event_type or "NORMAL").upper()
    vix_curr = _metric(delta, "VIX")
    vix_pct = _metric(delta, "VIX", "pct")
    wti_curr = _metric(delta, "WTI")
    wti_pct = _metric(delta, "WTI", "pct")
    dgs10_curr = _metric(delta, "DGS10")
    dgs10_pct = _metric(delta, "DGS10", "pct")
    hy_curr = _metric(delta, "HY_SPREAD")
    spy_pct = _metric(delta, "SPY", "pct")
    nasdaq_pct = _metric(delta, "NASDAQ", "pct")
    fg_curr = _metric(delta, "FEAR_GREED")
    crypto_basis_curr = _metric(delta, "CRYPTO_BASIS")
    tension = int(arc_context.get("tension", arc_context.get("arc_tension", 0)) or 0)
    system_stress = vix_curr > 35 and hy_curr > 700

    b: dict[str, int] = {}
    r: list[str] = []

    if hero_id == "CHAR_HERO_001":
        if system_stress:
            _add(b, r, "system_stress", 35, "Systemic stress calls EDT")
        if vix_curr >= 35:
            _add(b, r, "vix_crisis", 30, "VIX >= 35 crisis leadership")
        elif vix_curr >= 28:
            _add(b, r, "vix_high", 20, "VIX >= 28 requires system leadership")
        if spy_pct <= -3:
            _add(b, r, "spy_collapse", 25, "SPY <= -3 system defense")
        if nasdaq_pct <= -3:
            _add(b, r, "nasdaq_collapse", 15, "NASDAQ <= -3 system defense")
        if villain_id in {"CHAR_VILLAIN_005", "CHAR_VILLAIN_006"}:
            _add(b, r, "counter_villain", 20, "EDT counters algorithm/war systemic threat")
        if st == "NO_BATTLE" and vix_curr < 16 and spy_pct > 0:
            _add(b, r, "calm_growth", 35, "Calm positive market fits EDT solo growth")
    elif hero_id == "CHAR_HERO_002":
        if dgs10_curr >= 5.0:
            _add(b, r, "rate_lv2", 45, "DGS10 >= 5.0 calls Iron Nuna")
        elif dgs10_curr >= 4.8:
            _add(b, r, "rate_trigger", 35, "DGS10 >= 4.8 calls Iron Nuna")
        if dgs10_pct >= 5:
            _add(b, r, "rate_jump", 15, "DGS10 pct >= 5 defensive response")
        if hy_curr >= 500:
            _add(b, r, "credit_lv3", 30, "HY spread >= 500 credit defense")
        elif hy_curr >= 400:
            _add(b, r, "credit_lv2", 20, "HY spread >= 400 credit defense")
        if villain_id == "CHAR_VILLAIN_001":
            _add(b, r, "counter_debt", 20, "Iron Nuna counters Debt Titan")
        if villain_id == "CHAR_VILLAIN_003":
            _add(b, r, "counter_liquidity", 15, "Iron Nuna supports liquidity defense")
        if st == "NO_BATTLE" and 16 <= vix_curr <= 20 and -0.5 <= spy_pct <= 0.8:
            _add(b, r, "calm_analysis", 20, "Sideways calm market fits analysis")
    elif hero_id == "CHAR_HERO_003":
        if wti_pct >= 8:
            _add(b, r, "oil_pct_lv2", 50, "WTI pct >= 8 calls Leverage")
        elif wti_pct >= 5:
            _add(b, r, "oil_pct_trigger", 40, "WTI pct >= 5 calls Leverage")
        if wti_curr >= 100:
            _add(b, r, "oil_abs_high", 30, "WTI >= 100 energy crisis")
        elif wti_curr >= 90:
            _add(b, r, "oil_abs_active", 20, "WTI >= 90 energy stress")
        if villain_id == "CHAR_VILLAIN_002":
            _add(b, r, "counter_oil", 20, "Leverage counters Oil Shock Titan")
        if spy_pct >= 1.0:
            _add(b, r, "spy_momentum", 15, "SPY >= +1% momentum")
        if nasdaq_pct >= 1.5:
            _add(b, r, "nasdaq_momentum", 15, "NASDAQ >= +1.5% momentum")
        if fg_curr >= 70:
            _add(b, r, "greed_momentum", 10, "Fear & Greed >= 70")
        if st == "NO_BATTLE" and spy_pct > 1.0:
            _add(b, r, "solo_momentum", 25, "NO_BATTLE strong SPY momentum")
    elif hero_id == "CHAR_HERO_004":
        if vix_curr >= 35:
            _add(b, r, "vix_signal_lv3", 45, "VIX >= 35 calls Futures Girl")
        elif vix_curr >= 28:
            _add(b, r, "vix_signal", 35, "VIX >= 28 calls Futures Girl")
        if vix_pct >= 20:
            _add(b, r, "vix_pct_signal", 25, "VIX pct >= 20 signal detection")
        if villain_id == "CHAR_VILLAIN_004":
            _add(b, r, "counter_volatility", 20, "Futures Girl counters Volatility Hydra")
        if abs(nasdaq_pct) >= 2:
            _add(b, r, "nasdaq_volatility", 15, "NASDAQ absolute move >= 2%")
        if abs(crypto_basis_curr) >= 1:
            _add(b, r, "basis_signal", 10, "Crypto basis extreme signal")
        if et == "SHOCK":
            _add(b, r, "shock_fit", 20, "SHOCK event fits Futures Girl")
        if et == "INTEL":
            _add(b, r, "intel_fit", 15, "INTEL event fits Futures Girl")
    elif hero_id == "CHAR_HERO_005":
        if vix_curr >= 30:
            _add(b, r, "vix_defense", 30, "VIX >= 30 calls Gold Bond defense")
        if hy_curr >= 500:
            _add(b, r, "credit_wall", 30, "HY spread >= 500 calls Gold Bond")
        if fg_curr and fg_curr <= 25:
            _add(b, r, "fear_absorption", 20, "Fear & Greed <= 25")
        if spy_pct <= -2:
            _add(b, r, "spy_defense", 20, "SPY <= -2 defensive shield")
        if dgs10_curr >= 4.8:
            _add(b, r, "rate_defense", 15, "DGS10 >= 4.8 defensive allocation")
        if villain_id == "CHAR_VILLAIN_003":
            _add(b, r, "counter_liquidity", 20, "Gold Bond counters Liquidity Leviathan")
        if villain_id == "CHAR_VILLAIN_001":
            _add(b, r, "counter_debt", 15, "Gold Bond supports debt defense")
        if st == "NO_BATTLE" and vix_curr > 18:
            _add(b, r, "solo_defense", 20, "NO_BATTLE but VIX > 18 defensive observation")
        if et == "AFTERMATH":
            _add(b, r, "aftermath_fit", 15, "AFTERMATH fits defensive recovery")

    if tension >= 75:
        _add(b, r, "arc_high_tension", 15, "Arc tension >= 75")
    elif tension >= 50:
        _add(b, r, "arc_moderate_tension", 8, "Arc tension >= 50")

    role = "PRIMARY_HERO" if st != "ALLIANCE" else "HERO_CANDIDATE"
    threshold = HERO_NO_BATTLE_THRESHOLD if st == "NO_BATTLE" else HERO_PRIMARY_THRESHOLD
    return _decision(
        char_id=hero_id,
        faction="HERO",
        role=role,
        threshold=threshold,
        breakdown=b,
        reasons=r,
        metrics_used={
            "VIX.curr": vix_curr,
            "VIX.pct": vix_pct,
            "WTI.curr": wti_curr,
            "WTI.pct": wti_pct,
            "DGS10.curr": dgs10_curr,
            "HY_SPREAD.curr": hy_curr,
            "SPY.pct": spy_pct,
            "NASDAQ.pct": nasdaq_pct,
            "FEAR_GREED.curr": fg_curr,
        },
    )


def score_neutral_guests(delta: dict, curr_row: dict | None = None) -> list[CharacterAppearanceDecision]:
    """중립/게스트 후보 점수화. 현재 데이터로 가능한 2종을 지원한다."""
    curr_row = curr_row or {}
    decisions: list[CharacterAppearanceDecision] = []

    us10y = float(curr_row.get("us10y") or _metric(delta, "DGS10"))
    yield_curve = float(curr_row.get("yield_curve") or 0.0)
    dgs10_pct = _metric(delta, "DGS10", "pct")
    b: dict[str, int] = {}
    r: list[str] = []
    if yield_curve < -0.5:
        _add(b, r, "inversion_deep", 60, "Yield curve < -0.5 deep inversion")
    elif yield_curve < 0:
        _add(b, r, "inversion", 40, "Yield curve inverted")
    if us10y >= 5.0:
        _add(b, r, "us10y_lv2", 50, "US10Y >= 5.0")
    elif us10y >= 4.5:
        _add(b, r, "us10y_high", 35, "US10Y >= 4.5")
    elif 3.0 <= us10y < 4.5 and yield_curve >= 0:
        _add(b, r, "observer_rate", 25, "US10Y 3.0~4.5 with normal curve")
    if dgs10_pct >= 5:
        _add(b, r, "rate_jump", 15, "DGS10 pct >= 5")
    score = sum(b.values())
    if yield_curve < -0.5 or score >= 70:
        role = "ARBITRATOR"
    elif score >= 45:
        role = "WARNER"
    elif score >= 25:
        role = "OBSERVER"
    else:
        role = "ABSENT"
    decisions.append(_decision(
        char_id="SENTINEL_YIELD",
        faction="NEUTRAL",
        role=role,
        threshold=NEUTRAL_THRESHOLD,
        breakdown=b,
        reasons=r,
        metrics_used={"us10y": us10y, "yield_curve": yield_curve, "DGS10.pct": dgs10_pct},
    ))

    basis_state = str(curr_row.get("crypto_basis_state", "Unknown"))
    sentiment_state = str(curr_row.get("btc_sentiment_state", "Unknown"))
    basis_spread = curr_row.get("crypto_basis_spread")
    social = curr_row.get("btc_social_sentiment")
    crypto_basis = float(basis_spread if basis_spread is not None else _metric(delta, "CRYPTO_BASIS"))
    btc_pct = _metric(delta, "BTC", "pct")
    b = {}
    r = []
    basis_score = 3 if basis_state == "Premium" or crypto_basis > 1 else 1 if basis_state == "Discount" or crypto_basis < -1 else 2
    sentiment_score = 1 if sentiment_state == "Bullish" or (social is not None and social > 70) else 3 if sentiment_state == "Bearish" or (social is not None and social < 50) else 2
    if basis_state == "Unknown" and sentiment_state == "Unknown" and basis_spread is None and social is None:
        pass
    else:
        if abs(basis_score - sentiment_score) >= 2:
            _add(b, r, "basis_sentiment_divergence", 60, "Basis and sentiment fully diverge")
        if basis_state in {"Premium", "Discount"} or abs(crypto_basis) >= 1:
            _add(b, r, "basis_extreme", 35, "Crypto basis extreme")
        if sentiment_state in {"Bullish", "Bearish"}:
            _add(b, r, "sentiment_extreme", 25, "BTC sentiment directional")
        if abs(btc_pct) >= 5:
            _add(b, r, "btc_volatility", 20, "BTC absolute move >= 5%")
    if b.get("basis_sentiment_divergence", 0):
        role = "DOUBLE_AGENT"
    elif b.get("basis_extreme", 0):
        role = "BROKER"
    elif b.get("sentiment_extreme", 0):
        role = "INFORMANT"
    else:
        role = "ABSENT"
    decisions.append(_decision(
        char_id="CRYPTO_SHADE",
        faction="NEUTRAL",
        role=role,
        threshold=NEUTRAL_THRESHOLD,
        breakdown=b,
        reasons=r,
        metrics_used={
            "crypto_basis_state": basis_state,
            "btc_sentiment_state": sentiment_state,
            "crypto_basis_spread": crypto_basis,
            "BTC.pct": btc_pct,
        },
    ))
    return decisions



def _multi_villain_max() -> int:
    try:
        return max(1, min(int(os.environ.get("MULTI_VILLAIN_MAX", "2")), 3))
    except ValueError:
        return 2


def _select_support_villains(
    villain_decisions: list[CharacterAppearanceDecision],
    primary_villain: str | None,
    scenario_type: str,
) -> tuple[list[str], dict[str, str], dict[str, str]]:
    """Pick deterministic secondary villains behind a feature flag."""
    roles: dict[str, str] = {}
    reasons: dict[str, str] = {}
    if primary_villain:
        roles[primary_villain] = "PRIMARY_THREAT"
        reasons[primary_villain] = "primary villain selected by top score or legacy fallback"
    if (
        not primary_villain
        or os.environ.get("MULTI_VILLAIN_ENABLED", "false").lower() != "true"
        or scenario_type not in {"ALLIANCE", "VILLAIN_PACT"}
    ):
        return [], roles, reasons

    primary_decision = next((d for d in villain_decisions if d.char_id == primary_villain), None)
    primary_score = primary_decision.score if primary_decision else VILLAIN_THRESHOLD
    primary_domain = VILLAIN_DOMAIN.get(primary_villain)
    support: list[str] = []
    for decision in villain_decisions:
        if decision.char_id == primary_villain:
            continue
        if decision.score < VILLAIN_SUPPORT_THRESHOLD:
            continue
        if primary_score - decision.score > VILLAIN_SUPPORT_MAX_GAP:
            continue
        if VILLAIN_DOMAIN.get(decision.char_id) == primary_domain:
            continue
        support.append(decision.char_id)
        roles[decision.char_id] = "SECONDARY_THREAT"
        reasons[decision.char_id] = (
            f"support score {decision.score}>={VILLAIN_SUPPORT_THRESHOLD} "
            f"within gap {VILLAIN_SUPPORT_MAX_GAP} of primary {primary_score}"
        )
        if len(support) >= _multi_villain_max() - 1:
            break
    return support, roles, reasons

def _rank(decisions: list[CharacterAppearanceDecision]) -> list[CharacterAppearanceDecision]:
    ranked = sorted(decisions, key=lambda d: (d.score, d.char_id), reverse=True)
    return [
        CharacterAppearanceDecision(
            **{**d.to_dict(), "rank": idx}
        )
        for idx, d in enumerate(ranked, 1)
    ]


def resolve_character_selection(
    *,
    delta: dict,
    event_type: str,
    scenario_type: str,
    risk_level: str,
    base_hero_id: str,
    base_villain_id: str,
    arc_context: dict | None = None,
    curr_row: dict | None = None,
    recent_outcomes: list[str] | None = None,
) -> CharacterSelectionResult:
    """시나리오별 최종 히어로/빌런/중립 캐릭터를 점수 기반으로 선택한다."""
    st = (scenario_type or "ONE_VS_ONE").upper()
    villain_decisions = _rank([
        score_villain(v, delta, event_type, arc_context, recent_outcomes)
        for v in VILLAIN_IDS
    ])

    if st == "NO_BATTLE":
        primary_villain = None
    else:
        top_villain = villain_decisions[0]
        primary_villain = top_villain.char_id if top_villain.appear else base_villain_id

    support_villains, villain_roles, villain_selection_reason = _select_support_villains(
        villain_decisions, primary_villain, st
    )

    hero_decisions = _rank([
        score_hero(h, delta, st, event_type, primary_villain, arc_context)
        for h in HERO_IDS
    ])
    top_hero = hero_decisions[0]
    if top_hero.appear:
        primary_hero = top_hero.char_id
        hero_reason = f"top hero score {top_hero.score}>={top_hero.threshold}"
    elif primary_villain:
        primary_hero = LEGACY_VILLAIN_TO_HERO.get(primary_villain, base_hero_id)
        hero_reason = "hero threshold not met; legacy villain counter fallback"
    else:
        primary_hero = base_hero_id
        hero_reason = "NO_BATTLE hero threshold not met; base hero fallback"

    support_heroes: list[str] = []
    if st == "ALLIANCE":
        support_pool = [d for d in hero_decisions if d.char_id != primary_hero]
        support = next((d for d in support_pool if d.score >= HERO_SUPPORT_THRESHOLD), None)
        if support is None and primary_villain:
            counter = VILLAIN_TO_COUNTER_HERO.get(primary_villain)
            if counter and counter != primary_hero:
                support_heroes = [counter]
            else:
                support_heroes = [d.char_id for d in support_pool[:1]]
        elif support is not None:
            support_heroes = [support.char_id]

    neutral_decisions = _rank(score_neutral_guests(delta, curr_row))
    neutral_guests = [d for d in neutral_decisions if d.appear]

    if st == "NO_BATTLE":
        reason = f"NO_BATTLE: {hero_reason}; villain suppressed"
    elif st == "ALLIANCE":
        reason = (
            f"ALLIANCE: villains={[primary_villain, *support_villains] if primary_villain else []}; "
            f"primary={primary_hero}; support={support_heroes}; {hero_reason}"
        )
    else:
        reason = f"ONE_VS_ONE: villain={primary_villain}; primary={primary_hero}; {hero_reason}"

    return CharacterSelectionResult(
        scenario_type=st,
        event_type=event_type,
        risk_level=risk_level,
        primary_hero=primary_hero,
        support_heroes=support_heroes,
        primary_villain=primary_villain,
        neutral_guests=neutral_guests,
        all_candidates=[*hero_decisions, *villain_decisions, *neutral_decisions],
        selection_reason=reason,
        support_villains=support_villains,
        villain_roles=villain_roles,
        villain_selection_reason=villain_selection_reason,
    )
