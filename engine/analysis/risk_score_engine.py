"""Composite market risk scoring for the market-data pilot."""

from __future__ import annotations

from typing import Any


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


def _as_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _metric(signal_pack: dict[str, Any], symbol: str) -> dict[str, Any]:
    for signal in signal_pack.get("signals") or []:
        if signal.get("symbol") == symbol:
            return signal
    return {}


def _score_volatility(signal_pack: dict[str, Any]) -> float:
    vix = _as_float(_metric(signal_pack, "VIX").get("value")) or 0.0
    vix_pct = abs(_as_float(_metric(signal_pack, "VIX").get("change_pct")) or 0.0)
    return _clamp((vix - 12) * 3.0 + vix_pct * 0.7)


def _score_equity_breadth(signal_pack: dict[str, Any]) -> float:
    spy = _as_float(_metric(signal_pack, "SPY").get("value")) or 0.0
    nasdaq = _as_float(_metric(signal_pack, "NASDAQ").get("value")) or 0.0
    sector_signals = signal_pack.get("by_domain", {}).get("sector", [])
    laggards = sum(1 for s in sector_signals if s.get("state") == "laggard")
    avg_sector = 0.0
    sector_changes = [_as_float(s.get("change_pct")) for s in sector_signals]
    sector_changes = [v for v in sector_changes if v is not None]
    if sector_changes:
        avg_sector = sum(sector_changes) / len(sector_changes)
    drawdown = max(0.0, -spy) * 18 + max(0.0, -nasdaq) * 12 + max(0.0, -avg_sector) * 10
    return _clamp(drawdown + laggards * 5)


def _score_rates(signal_pack: dict[str, Any]) -> float:
    dgs10 = _as_float(_metric(signal_pack, "DGS10").get("value")) or 0.0
    dgs10_pct = abs(_as_float(_metric(signal_pack, "DGS10").get("change_pct")) or 0.0)
    return _clamp(max(0.0, dgs10 - 3.5) * 28 + dgs10_pct * 1.3)


def _score_credit(signal_pack: dict[str, Any]) -> float:
    hy = _as_float(_metric(signal_pack, "HY_SPREAD").get("value")) or 0.0
    # FRED HY OAS may be stored in percentage points. Treat >50 as bp-like, otherwise pct-like.
    hy_pct_points = hy / 100 if hy > 50 else hy
    return _clamp(max(0.0, hy_pct_points - 3.0) * 24)


def _score_fx(signal_pack: dict[str, Any]) -> float:
    dxy_pct = abs(_as_float(_metric(signal_pack, "DXY").get("change_pct")) or 0.0)
    usdkrw_pct = abs(_as_float(_metric(signal_pack, "USDKRW").get("change_pct")) or 0.0)
    return _clamp(dxy_pct * 12 + usdkrw_pct * 10)


def _score_commodity(signal_pack: dict[str, Any]) -> float:
    wti = _as_float(_metric(signal_pack, "WTI").get("value")) or 0.0
    wti_pct = abs(_as_float(_metric(signal_pack, "WTI").get("change_pct")) or 0.0)
    return _clamp(max(0.0, wti - 70) * 1.2 + wti_pct * 4)


def _score_crypto(signal_pack: dict[str, Any]) -> float:
    basis = abs(_as_float(_metric(signal_pack, "CRYPTO_BASIS").get("value")) or 0.0)
    btc_pct = abs(_as_float(_metric(signal_pack, "BTC").get("change_pct")) or 0.0)
    return _clamp(basis * 20 + btc_pct * 2)


def _score_news_calendar(signal_pack: dict[str, Any]) -> float:
    events = signal_pack.get("economic_events") or []
    news = signal_pack.get("news_items") or []
    max_importance = max([_as_float(e.get("importance")) or 0.0 for e in events if isinstance(e, dict)] or [0.0])
    news_score = max([_as_float(n.get("relevance_score")) or 0.0 for n in news if isinstance(n, dict)] or [0.0]) * 30
    return _clamp(max_importance * 10 + news_score)


def _risk_level(score: float) -> str:
    if score >= 65:
        return "HIGH"
    if score >= 35:
        return "MEDIUM"
    return "LOW"


def compute(signal_pack: dict[str, Any]) -> dict[str, Any]:
    """Compute composite risk score, domain pressure, and trace."""
    domain_scores = {
        "volatility": _score_volatility(signal_pack),
        "equity_breadth": _score_equity_breadth(signal_pack),
        "rates": _score_rates(signal_pack),
        "credit": _score_credit(signal_pack),
        "fx": _score_fx(signal_pack),
        "commodity": _score_commodity(signal_pack),
        "crypto": _score_crypto(signal_pack),
        "news_calendar": _score_news_calendar(signal_pack),
    }
    risk_score = _clamp(
        0.20 * domain_scores["volatility"]
        + 0.20 * domain_scores["equity_breadth"]
        + 0.15 * domain_scores["rates"]
        + 0.15 * domain_scores["credit"]
        + 0.10 * domain_scores["fx"]
        + 0.10 * domain_scores["commodity"]
        + 0.05 * domain_scores["crypto"]
        + 0.05 * domain_scores["news_calendar"]
    )
    shock_score = max(domain_scores.values())
    sorted_domains = sorted(domain_scores.items(), key=lambda item: item[1], reverse=True)
    risk_drivers = [
        {"domain": domain, "score": round(score, 2), "reason": f"{domain} pressure"}
        for domain, score in sorted_domains[:3]
        if score > 0
    ]
    return {
        "version": "pilot-1",
        "risk_score": round(risk_score, 2),
        "risk_level": _risk_level(risk_score),
        "shock_score": round(shock_score, 2),
        "domain_scores": {k: round(v, 2) for k, v in domain_scores.items()},
        "dominant_domain": sorted_domains[0][0] if sorted_domains else "market",
        "risk_drivers": risk_drivers,
        "data_confidence": signal_pack.get("data_confidence", 0.0),
    }
