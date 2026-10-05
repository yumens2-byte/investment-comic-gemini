"""ICE DXY daily close via yfinance (ticker DX-Y.NYB). Failures return None (fallback path)."""
from __future__ import annotations

import logging
import math
from datetime import date, timedelta
from typing import Any

from sidestory.core.dollar import DollarCandidate, DollarIndexKind

logger = logging.getLogger(__name__)
TICKER = "DX-Y.NYB"
LOOKBACK_DAYS = 14
WEEK_BARS = 5


def candidate_from_closes(closes: list[tuple[date, float]], on_or_before: date
                          ) -> DollarCandidate | None:
    """Pure part: [(bar_date, close)] → candidate for the latest bar <= on_or_before."""
    bars = sorted((d, float(c)) for d, c in closes
                  if d <= on_or_before and c is not None and math.isfinite(float(c)))
    if not bars:
        return None
    bar_date, close = bars[-1]
    change = None
    if len(bars) > WEEK_BARS:
        base = bars[-1 - WEEK_BARS][1]
        if base:
            change = (close - base) / base * 100.0
    return DollarCandidate(kind=DollarIndexKind.DXY, value=close, as_of=bar_date.isoformat(),
                           source=f"yfinance:{TICKER}", change_pct_1w=change)


def _closes_from_frame(frame: Any) -> list[tuple[date, float]]:
    if frame is None or getattr(frame, "empty", True):
        return []
    column = frame["Close"]
    if hasattr(column, "columns"):  # MultiIndex columns (newer yfinance) → first ticker
        column = column.iloc[:, 0]
    return [(idx.date() if hasattr(idx, "date") else idx, float(val))
            for idx, val in column.dropna().items()]


class YFinanceDxySource:
    def __init__(self, downloader=None):
        self._download = downloader

    def dxy_close(self, on_or_before: date) -> DollarCandidate | None:
        try:
            download = self._download
            if download is None:
                import yfinance as yf

                download = yf.download
            frame = download(
                TICKER,
                start=(on_or_before - timedelta(days=LOOKBACK_DAYS)).isoformat(),
                end=(on_or_before + timedelta(days=1)).isoformat(),  # end is exclusive
                interval="1d", progress=False, auto_adjust=False, threads=False,
            )
            return candidate_from_closes(_closes_from_frame(frame), on_or_before)
        except Exception as exc:  # network / parsing → fallback to main broad index
            logger.warning("[sidestory] DXY fetch failed: %s", exc)
            return None
