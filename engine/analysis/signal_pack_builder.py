"""Build a normalized signal pack from daily snapshot rows."""

from __future__ import annotations

from typing import Any


def _as_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _metric_signal(metric: str, row: dict[str, Any], domain: str, name: str) -> dict[str, Any]:
    curr = _as_float(row.get("curr"))
    pct = _as_float(row.get("pct"))
    return {
        "id": f"metric:{metric}",
        "domain": domain,
        "symbol": metric,
        "name": name,
        "value": curr,
        "change_pct": pct,
        "state": "available" if curr is not None else "Unknown",
        "confidence": 0.9 if curr is not None else 0.0,
        "raw": row,
    }


def _sector_signals(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    heatmap = snapshot.get("sector_heatmap") or {}
    sectors = heatmap.get("sectors") if isinstance(heatmap, dict) else None
    if not isinstance(sectors, list):
        return []
    signals: list[dict[str, Any]] = []
    for item in sectors:
        if not isinstance(item, dict):
            continue
        symbol = str(item.get("symbol") or item.get("name") or "sector")
        signals.append(
            {
                "id": str(item.get("id") or f"sector:{symbol}"),
                "domain": "sector",
                "symbol": symbol,
                "name": str(item.get("name") or symbol),
                "value": _as_float(item.get("value") if item.get("value") is not None else item.get("change_pct")),
                "change_pct": _as_float(item.get("change_pct")),
                "relative_pct": _as_float(item.get("relative_pct")),
                "state": str(item.get("state") or "Unknown"),
                "story_role": str(item.get("story_role") or "sector signal"),
                "scene_symbol": str(item.get("scene_symbol") or f"{symbol} sector board"),
                "confidence": _as_float(item.get("confidence")) or 0.0,
                "raw": item,
            }
        )
    return signals


def build_signal_pack(delta: dict[str, dict[str, Any]], snapshot: dict[str, Any]) -> dict[str, Any]:
    """Normalize scalar delta and JSONB enrichments for risk/story formulas."""
    metric_domains = {
        "VIX": ("volatility", "VIX"),
        "SPY": ("equity", "SPY daily change"),
        "NASDAQ": ("equity", "NASDAQ daily change"),
        "DGS10": ("rates", "US 10Y yield"),
        "WTI": ("commodity", "WTI oil"),
        "HY_SPREAD": ("credit", "High-yield spread"),
        "DXY": ("fx", "Dollar index"),
        "USDKRW": ("fx", "USD/KRW"),
        "BTC": ("crypto", "Bitcoin"),
        "CRYPTO_BASIS": ("crypto", "Crypto basis"),
        "FEAR_GREED": ("sentiment", "Fear & Greed"),
    }
    signals: list[dict[str, Any]] = []
    for metric, row in delta.items():
        domain, name = metric_domains.get(metric, ("market", metric))
        signals.append(_metric_signal(metric, row, domain, name))
    signals.extend(_sector_signals(snapshot))

    by_domain: dict[str, list[dict[str, Any]]] = {}
    for signal in signals:
        by_domain.setdefault(str(signal.get("domain") or "market"), []).append(signal)

    confidences = [float(s.get("confidence") or 0.0) for s in signals]
    data_confidence = round(sum(confidences) / len(confidences), 4) if confidences else 0.0

    return {
        "version": "pilot-1",
        "signals": signals,
        "by_domain": by_domain,
        "data_confidence": data_confidence,
        "sector_heatmap": snapshot.get("sector_heatmap"),
        "news_items": snapshot.get("news_items") or [],
        "economic_events": snapshot.get("event_calendar") or [],
    }
