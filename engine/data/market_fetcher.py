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
  - 데이터 부족/일시 장애는 3회 재시도 후 None fallback
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from concurrent.futures import TimeoutError as FuturesTimeoutError

import pandas as pd
import requests

from engine.common.retry import api_retry
from engine.data import yfinance_client

logger = logging.getLogger(__name__)

# 개별 티커 수집 최대 대기 시간 (초)
_TICKER_TIMEOUT_SEC = 12
# 전체 병렬 수집 최대 대기 시간 (초)
_TOTAL_TIMEOUT_SEC = 45


@api_retry(max_attempts=3, min_wait=1.0, max_wait=10.0)
def _download_ticker(ticker: str, period: str) -> pd.DataFrame:
    """Download one yfinance ticker and retry empty responses."""
    data = yfinance_client.download(
        ticker,
        period=period,
        progress=False,
        auto_adjust=True,
        timeout=_TICKER_TIMEOUT_SEC,
    )
    if data.empty:
        raise ValueError(f"empty yfinance response for {ticker}")
    return data


@api_retry(max_attempts=3, min_wait=1.0, max_wait=10.0)
def _fetch_btc_usd_fallback() -> float:
    """Fetch a BTC/USD spot price from Coinbase when yfinance is temporarily sparse."""
    resp = requests.get(
        "https://api.coinbase.com/v2/prices/BTC-USD/spot",
        timeout=8,
    )
    resp.raise_for_status()
    amount = resp.json().get("data", {}).get("amount")
    if amount is None:
        raise ValueError("Coinbase BTC-USD spot amount missing")
    return float(amount)


def _extract_closes(data: pd.DataFrame, ticker: str) -> pd.Series:
    """Return non-null yfinance closes, including yfinance 0.2.x MultiIndex frames."""
    if isinstance(data.columns, pd.MultiIndex):
        close_cols = [c for c in data.columns if c[0] == "Close"]
        if not close_cols:
            raise ValueError(f"Close column missing for {ticker}")
        return data[close_cols[0]].dropna()
    return data["Close"].dropna()


def _fetch_ticker_safe(ticker: str, period: str = "5d") -> dict:
    """
    yfinance 단일 티커 수집. timeout + MultiIndex 대응.
    데이터 부족/일시 장애는 3회 재시도 후 None 딕셔너리 반환.
    """
    try:
        data = _download_ticker(ticker, period)

        closes = _extract_closes(data, ticker)

        if closes.empty:
            raise ValueError(f"close rows missing for {ticker}")

        curr = float(closes.iloc[-1])
        prev = None
        pct = None
        if len(closes) >= 2:
            prev = float(closes.iloc[-2])
            pct = round((curr - prev) / prev * 100, 4) if prev != 0 else 0.0
        else:
            logger.warning(
                "[yfinance] %s close row가 1개뿐이라 pct_change는 None 처리",
                ticker,
            )

        return {"close": curr, "prev_close": prev, "pct_change": pct}

    except Exception as exc:
        logger.warning("[yfinance] %s 수집 실패(3회 재시도 후): %s", ticker, type(exc).__name__)
        if ticker == "BTC-USD":
            try:
                close = _fetch_btc_usd_fallback()
                logger.info("[Coinbase] BTC-USD fallback=%.1f", close)
                return {"close": close, "prev_close": None, "pct_change": None}
            except Exception as fallback_exc:
                logger.warning(
                    "[Coinbase] BTC-USD fallback 실패(3회 재시도 후): %s",
                    type(fallback_exc).__name__,
                )
        return {"close": None, "prev_close": None, "pct_change": None}


def fetch_macro_overrides() -> dict[str, float | None]:
    """당일 이벤트 반영용 실시간 매크로 오버라이드 (FRED 지연 보정).

    2026-09-03: FRED VIXCLS/DCOILWTICO는 1~수영업일 지연 발표라 급변일 당일의
    VIX 급등·유가 급등이 스냅샷에 반영되지 않아 major event 판정이 구조적으로
    불가능했다 (oil_wti 5일 연속 동일값 정체가 물증). yfinance 실시간 종가를
    1순위로 쓰고, 수집 실패(None) 시 호출부에서 FRED 값을 유지한다.
    """
    tickers = {"vix": "^VIX", "oil_wti": "CL=F"}
    result: dict[str, float | None] = {}
    for col, ticker in tickers.items():
        info = _fetch_ticker_safe(ticker)
        close = info.get("close")
        result[col] = float(close) if close is not None else None
        if close is not None:
            logger.info("[yfinance] macro override %s(%s)=%.4f", col, ticker, close)
    return result


def fetch_all(target_date: str | None = None) -> dict[str, float | None]:
    """
    모든 시장 지표 병렬 수집.

    ThreadPoolExecutor로 4개 티커를 동시에 수집.
    전체 최대 대기 시간: _TOTAL_TIMEOUT_SEC (45초)

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

    # 병렬 수집 — TimeoutError 발생 시 None fallback 처리
    with ThreadPoolExecutor(max_workers=4) as executor:
        future_map = {
            executor.submit(_fetch_ticker_safe, ticker, period): (key, ticker, field)
            for key, ticker, period, field in tasks
        }

        try:
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

        except FuturesTimeoutError:
            # 전체 타임아웃 — 완료되지 않은 항목 None 처리 후 파이프라인 계속
            logger.warning(
                "[yfinance] 전체 타임아웃 (%ds) — 미완료 항목 None 처리",
                _TOTAL_TIMEOUT_SEC,
            )

    # 완료되지 않은 태스크 None 처리 (타임아웃 또는 기타 이유)
    for key, _, _, _ in tasks:
        if key not in result:
            logger.warning("[yfinance] %s: None 처리 (미완료)", key)
            result[key] = None

    return result
