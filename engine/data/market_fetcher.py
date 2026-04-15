"""
engine/data/market_fetcher.py
yfinance 기반 시장 지표 수집.

수집 대상:
  SPY     — S&P 500 ETF (일간 변화율)
  ^IXIC   — 나스닥 종합지수 (일간 변화율)
  BTC-USD — 비트코인 USD 현재가
  USDKRW  — 달러/원 환율

개선:
  - timeout=10 으로 단축 (기존 30초 → 10초)
  - ThreadPoolExecutor로 병렬 수집 (총 대기시간 단축)
  - 실패 시 즉시 None fallback (파이프라인 차단 없음)
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd

logger = logging.getLogger(__name__)

# 개별 티커 수집 최대 대기 시간 (초)
_TICKER_TIMEOUT_SEC = 12
# 전체 병렬 수집 최대 대기 시간 (초)
_TOTAL_TIMEOUT_SEC = 20


def _fetch_ticker_safe(ticker: str, period: str = "5d") -> dict:
    """
    yfinance 단일 티커 수집. timeout + MultiIndex 대응.
    실패 시 None 딕셔너리 반환 (예외 전파 없음).
    """
    try:
        import yfinance as yf

        # timeout 파라미터로 연결 시간 제한
        data = yf.download(
            ticker,
            period=period,
            progress=False,
            auto_adjust=True,
            timeout=_TICKER_TIMEOUT_SEC,
        )

        if data.empty or len(data) < 2:
            logger.warning("[yfinance] %s: 데이터 부족 (rows=%d)", ticker, len(data))
            return {"close": None, "prev_close": None, "pct_change": None}

        # yfinance 0.2.x+: MultiIndex 대응
        if isinstance(data.columns, pd.MultiIndex):
            close_cols = [c for c in data.columns if c[0] == "Close"]
            if not close_cols:
                return {"close": None, "prev_close": None, "pct_change": None}
            closes = data[close_cols[0]].dropna()
        else:
            closes = data["Close"].dropna()

        if len(closes) < 2:
            return {"close": None, "prev_close": None, "pct_change": None}

        curr = float(closes.iloc[-1])
        prev = float(closes.iloc[-2])
        pct = round((curr - prev) / prev * 100, 4) if prev != 0 else 0.0

        return {"close": curr, "prev_close": prev, "pct_change": pct}

    except Exception as exc:
        logger.warning("[yfinance] %s 수집 실패: %s", ticker, type(exc).__name__)
        return {"close": None, "prev_close": None, "pct_change": None}


def fetch_all(target_date: str | None = None) -> dict[str, float | None]:
    """
    모든 시장 지표 병렬 수집.

    ThreadPoolExecutor로 4개 티커를 동시에 수집.
    전체 최대 대기 시간: _TOTAL_TIMEOUT_SEC (20초)

    Returns:
        icg.daily_snapshots 컬럼명 → 값 딕셔너리.
        수집 실패 필드는 None.
    """
    result: dict[str, float | None] = {}

    # 수집 태스크 정의: (result_key, ticker, period, value_field)
    tasks = [
        ("spy_change",    "SPY",     "5d",  "pct_change"),
        ("nasdaq_change", "^IXIC",   "5d",  "pct_change"),
        ("btc_usd",       "BTC-USD", "2d",  "close"),
        ("usdkrw",        "USDKRW=X","2d",  "close"),
    ]

    # 병렬 수집
    with ThreadPoolExecutor(max_workers=4) as executor:
        future_map = {
            executor.submit(_fetch_ticker_safe, ticker, period): (key, ticker, field)
            for key, ticker, period, field in tasks
        }

        for future in as_completed(future_map, timeout=_TOTAL_TIMEOUT_SEC):
            key, ticker, field = future_map[future]
            try:
                data = future.result(timeout=1)
                value = data.get(field)
                result[key] = value
                if value is not None:
                    if "change" in key:
                        logger.info("[yfinance] %s change=%.2f%%", ticker, value)
                    else:
                        logger.info("[yfinance] %s=%.1f", ticker, value)
                else:
                    logger.warning("[yfinance] %s: None 반환", ticker)
            except Exception as exc:
                logger.warning("[yfinance] %s future 실패: %s", ticker, exc)
                result[key] = None

    # 타임아웃으로 완료되지 않은 태스크 None 처리
    for key, _, _, _ in tasks:
        if key not in result:
            logger.warning("[yfinance] %s: 전체 타임아웃으로 None 처리", key)
            result[key] = None

    return result
