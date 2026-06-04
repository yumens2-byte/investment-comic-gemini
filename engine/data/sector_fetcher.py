"""
engine/data/sector_fetcher.py
S&P 500 sector ETF heatmap collection for story/risk enrichment.

The fetcher is intentionally best-effort: every ticker failure becomes an
Unknown/None row so the market pipeline can continue and the narrative layer can
still use whatever sector evidence is available.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from concurrent.futures import TimeoutError as FuturesTimeoutError
from datetime import date
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

_TICKER_TIMEOUT_SEC = 12
_TOTAL_TIMEOUT_SEC = 25

SECTOR_ETFS: tuple[dict[str, str], ...] = (
    {"symbol": "XLK", "name": "Technology"},
    {"symbol": "XLF", "name": "Financials"},
    {"symbol": "XLE", "name": "Energy"},
    {"symbol": "XLV", "name": "Health Care"},
    {"symbol": "XLI", "name": "Industrials"},
    {"symbol": "XLY", "name": "Consumer Discretionary"},
    {"symbol": "XLP", "name": "Consumer Staples"},
    {"symbol": "XLU", "name": "Utilities"},
    {"symbol": "XLB", "name": "Materials"},
    {"symbol": "XLRE", "name": "Real Estate"},
    {"symbol": "XLC", "name": "Communication Services"},
)


def _extract_close_series(data: pd.DataFrame) -> pd.Series:
    if isinstance(data.columns, pd.MultiIndex):
        close_cols = [col for col in data.columns if col[0] == "Close"]
        if not close_cols:
            return pd.Series(dtype="float64")
        return data[close_cols[0]].dropna()
    if "Close" not in data:
        return pd.Series(dtype="float64")
    return data["Close"].dropna()


def _fetch_ticker_change(ticker: str, period: str = "5d") -> float | None:
    """Return latest close-to-close percent change for a ticker."""
    try:
        import yfinance as yf

        data = yf.download(
            ticker,
            period=period,
            progress=False,
            auto_adjust=True,
            timeout=_TICKER_TIMEOUT_SEC,
        )
        closes = _extract_close_series(data)
        if len(closes) < 2:
            logger.warning("[sector] %s: 데이터 부족 rows=%d", ticker, len(closes))
            return None
        curr = float(closes.iloc[-1])
        prev = float(closes.iloc[-2])
        return round((curr - prev) / prev * 100, 4) if prev else None
    except Exception as exc:
        logger.warning("[sector] %s 수집 실패: %s", ticker, type(exc).__name__)
        return None


def classify_sector_state(change_pct: float | None, relative_pct: float | None) -> str:
    """Classify sector state for analysis/story use."""
    if change_pct is None:
        return "Unknown"
    rel = relative_pct if relative_pct is not None else 0.0
    if rel >= 1.0 and change_pct > 0:
        return "leader"
    if rel >= 0.5:
        return "relative_safe"
    if rel <= -1.0 and change_pct < 0:
        return "laggard"
    if abs(change_pct) >= 2.0:
        return "volatile"
    return "neutral"


def _confidence(change_pct: float | None) -> float:
    return 0.92 if change_pct is not None else 0.0


def build_heatmap(
    sector_changes: dict[str, float | None],
    *,
    spy_change: float | None = None,
    as_of: str | None = None,
) -> dict[str, Any]:
    """Build a JSON-serializable sector heatmap from raw ticker changes."""
    rows: list[dict[str, Any]] = []
    for meta in SECTOR_ETFS:
        symbol = meta["symbol"]
        change = sector_changes.get(symbol)
        relative = round(change - spy_change, 4) if change is not None and spy_change is not None else None
        state = classify_sector_state(change, relative)
        rows.append(
            {
                "id": f"sector:{symbol}",
                "domain": "sector",
                "symbol": symbol,
                "name": meta["name"],
                "value": change,
                "unit": "pct",
                "change_pct": change,
                "relative_pct": relative,
                "rank": None,
                "state": state,
                "story_role": f"{meta['name']} sector {state}",
                "scene_symbol": f"{meta['name']} sector board",
                "source": "yfinance",
                "as_of": as_of or date.today().isoformat(),
                "confidence": _confidence(change),
            }
        )

    ranked = sorted(
        [row for row in rows if row["change_pct"] is not None],
        key=lambda row: row["change_pct"],
        reverse=True,
    )
    for idx, row in enumerate(ranked, 1):
        row["rank"] = idx

    leaders = ranked[:3]
    laggards = list(reversed(ranked[-3:])) if ranked else []
    coverage = round(len(ranked) / len(SECTOR_ETFS), 4)
    avg_change = round(
        sum(float(row["change_pct"]) for row in ranked) / len(ranked), 4
    ) if ranked else None

    return {
        "as_of": as_of or date.today().isoformat(),
        "source": "yfinance",
        "coverage": coverage,
        "spy_change": spy_change,
        "avg_change_pct": avg_change,
        "sectors": rows,
        "leaders": leaders,
        "laggards": laggards,
    }


def fetch_all(target_date: str | None = None, spy_change: float | None = None) -> dict[str, Any]:
    """Fetch the sector ETF heatmap as a daily_snapshots payload fragment."""
    sector_changes: dict[str, float | None] = {}
    with ThreadPoolExecutor(max_workers=min(8, len(SECTOR_ETFS))) as executor:
        future_map = {
            executor.submit(_fetch_ticker_change, meta["symbol"]): meta["symbol"]
            for meta in SECTOR_ETFS
        }
        try:
            for future in as_completed(future_map, timeout=_TOTAL_TIMEOUT_SEC):
                symbol = future_map[future]
                try:
                    sector_changes[symbol] = future.result(timeout=1)
                except Exception as exc:
                    logger.warning("[sector] %s future 실패: %s", symbol, exc)
                    sector_changes[symbol] = None
        except FuturesTimeoutError:
            logger.warning("[sector] 전체 타임아웃 (%ds)", _TOTAL_TIMEOUT_SEC)

    for meta in SECTOR_ETFS:
        sector_changes.setdefault(meta["symbol"], None)

    heatmap = build_heatmap(sector_changes, spy_change=spy_change, as_of=target_date)
    logger.info(
        "[sector] heatmap coverage=%.0f%% leaders=%s laggards=%s",
        heatmap["coverage"] * 100,
        [row["symbol"] for row in heatmap["leaders"]],
        [row["symbol"] for row in heatmap["laggards"]],
    )
    return {"sector_heatmap": heatmap}
