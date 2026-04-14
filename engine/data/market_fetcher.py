"""
engine/data/market_fetcher.py
yfinance 기반 시장 지표 수집.

수집 대상:
  SPY   — S&P 500 ETF (일간 변화율)
  QQQ   — 나스닥 100 ETF (일간 변화율)
  BTC-USD — 비트코인 USD 현재가
  USDKRW  — 달러/원 환율
  ^VIX  — VIX (FRED 백업용, 주로 FRED 값 사용)
  ^IXIC — 나스닥 종합지수 (일간 변화율)
"""

from __future__ import annotations

import logging

from engine.common.retry import api_retry

logger = logging.getLogger(__name__)


@api_retry()
def _fetch_ticker(ticker: str, period: str = "5d") -> dict:
    """
    yfinance 단일 티커 최근 종가 + 변화율 수집.

    Args:
        ticker: yfinance 티커 심볼.
        period: 데이터 기간 (기본 5일).

    Returns:
        {"close": float, "prev_close": float, "pct_change": float}
        또는 {"close": None, "prev_close": None, "pct_change": None}
    """
    import yfinance as yf

    data = yf.download(ticker, period=period, progress=False, auto_adjust=True)

    if data.empty or len(data) < 2:
        logger.warning("[yfinance] %s: 데이터 부족 (rows=%d)", ticker, len(data))
        return {"close": None, "prev_close": None, "pct_change": None}

    close_col = "Close"
    closes = data[close_col].dropna()

    if len(closes) < 2:
        return {"close": None, "prev_close": None, "pct_change": None}

    curr = float(closes.iloc[-1])
    prev = float(closes.iloc[-2])
    pct = round((curr - prev) / prev * 100, 4) if prev != 0 else 0.0

    return {"close": curr, "prev_close": prev, "pct_change": pct}


def fetch_all(target_date: str | None = None) -> dict[str, float | None]:
    """
    모든 시장 지표 수집.

    Returns:
        icg.daily_snapshots 컬럼명 → 값 딕셔너리.
        수집 실패 필드는 None.
    """
    result: dict[str, float | None] = {}

    # SPY 일간 변화율
    try:
        spy = _fetch_ticker("SPY")
        result["spy_change"] = spy["pct_change"]
        logger.info("[yfinance] SPY change=%.2f%%", spy["pct_change"] or 0)
    except Exception as exc:
        logger.warning("[yfinance] SPY 수집 실패: %s", exc)
        result["spy_change"] = None

    # NASDAQ 일간 변화율 (^IXIC)
    try:
        ixic = _fetch_ticker("^IXIC")
        result["nasdaq_change"] = ixic["pct_change"]
        logger.info("[yfinance] NASDAQ change=%.2f%%", ixic["pct_change"] or 0)
    except Exception as exc:
        logger.warning("[yfinance] NASDAQ 수집 실패: %s", exc)
        result["nasdaq_change"] = None

    # BTC-USD 현재가
    try:
        btc = _fetch_ticker("BTC-USD", period="2d")
        result["btc_usd"] = btc["close"]
        logger.info("[yfinance] BTC=%.0f USD", btc["close"] or 0)
    except Exception as exc:
        logger.warning("[yfinance] BTC-USD 수집 실패: %s", exc)
        result["btc_usd"] = None

    # USD/KRW 환율
    try:
        usdkrw = _fetch_ticker("USDKRW=X", period="2d")
        result["usdkrw"] = usdkrw["close"]
        logger.info("[yfinance] USDKRW=%.1f", usdkrw["close"] or 0)
    except Exception as exc:
        logger.warning("[yfinance] USDKRW 수집 실패: %s", exc)
        result["usdkrw"] = None

    return result
