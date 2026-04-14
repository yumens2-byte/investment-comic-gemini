"""
engine/data/fred_fetcher.py
FRED (St. Louis Fed) API에서 거시경제 지표 수집.

수집 지표:
  DFF        — 연방기금금리 (Fed Funds Rate)
  DGS10      — 미국 10년 국채 금리
  VIXCLS     — VIX (CBOE Volatility Index)
  DCOILWTICO — WTI 유가 (달러/배럴)
  DTWEXBGS   — 달러 인덱스
  BAMLH0A0HYM2 — HY 스프레드 (High Yield OAS)
"""

from __future__ import annotations

import logging
import os
from datetime import date, timedelta

from engine.common.retry import api_retry

logger = logging.getLogger(__name__)

# FRED 시리즈 ID 목록
_SERIES: dict[str, str] = {
    "fed_funds_rate": "DFF",
    "us10y": "DGS10",
    "vix": "VIXCLS",
    "oil_wti": "DCOILWTICO",
    "dollar_index": "DTWEXBGS",
    "hy_spread": "BAMLH0A0HYM2",
}


@api_retry()
def _fetch_series(fred_client, series_id: str, lookback_days: int = 10) -> float | None:
    """
    FRED 단일 시리즈에서 최근 유효값(NaN 제외) 반환.

    Args:
        fred_client: fredapi.Fred 인스턴스.
        series_id: FRED 시리즈 ID.
        lookback_days: 탐색할 과거 일수.

    Returns:
        최근 유효값 또는 None.
    """
    end = date.today()
    start = end - timedelta(days=lookback_days)

    data = fred_client.get_series(
        series_id,
        observation_start=start.strftime("%Y-%m-%d"),
        observation_end=end.strftime("%Y-%m-%d"),
    )

    # 최근 유효값(NaN 아닌 마지막 값) 반환
    valid = data.dropna()
    if valid.empty:
        logger.warning("[FRED] %s: 유효 데이터 없음 (lookback=%d일)", series_id, lookback_days)
        return None

    return float(valid.iloc[-1])


def fetch_all(target_date: str | None = None) -> dict[str, float | None]:
    """
    모든 FRED 지표 수집.

    Args:
        target_date: 'YYYY-MM-DD' 형식 (미사용, 인터페이스 일관성용).

    Returns:
        icg.daily_snapshots 컬럼명 → 값 딕셔너리.
        수집 실패 필드는 None.

    Raises:
        RuntimeError: FRED_API_KEY 누락 시.
    """
    from fredapi import Fred  # 지연 import (테스트 mock 용이)

    api_key = os.environ.get("FRED_API_KEY", "")
    if not api_key:
        raise RuntimeError("FRED_API_KEY 환경변수 누락.")

    fred = Fred(api_key=api_key)
    result: dict[str, float | None] = {}

    for col_name, series_id in _SERIES.items():
        try:
            value = _fetch_series(fred, series_id)
            result[col_name] = value
            logger.info("[FRED] %s(%s) = %s", col_name, series_id, value)
        except Exception as exc:
            logger.warning("[FRED] %s(%s) 수집 실패: %s", col_name, series_id, exc)
            result[col_name] = None

    return result
