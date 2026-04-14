"""
engine/data/snapshot_writer.py
수집된 모든 지표를 icg.daily_snapshots에 UPSERT.

UNIQUE KEY: snapshot_date
"""

from __future__ import annotations

import logging
from datetime import date

logger = logging.getLogger(__name__)


def upsert(
    snapshot_date: str,
    fred_data: dict,
    market_data: dict,
    feargreed_data: dict,
    crypto_data: dict,
    sentiment_data: dict,
) -> None:
    """
    5개 fetcher 결과를 병합하여 icg.daily_snapshots에 upsert.

    Args:
        snapshot_date: 'YYYY-MM-DD' 형식.
        fred_data: fred_fetcher.fetch_all() 결과.
        market_data: market_fetcher.fetch_all() 결과.
        feargreed_data: feargreed_fetcher.fetch_all() 결과.
        crypto_data: crypto_fetcher.fetch_all() 결과.
        sentiment_data: sentiment_fetcher.fetch_all() 결과.
    """
    from engine.common.supabase_client import upsert_snapshot

    payload: dict = {
        **fred_data,
        **market_data,
        **feargreed_data,
        **crypto_data,
        **sentiment_data,
    }

    # None 값은 Supabase에 그대로 null 저장 (허용)
    upsert_snapshot(snapshot_date, payload)

    non_null = sum(1 for v in payload.values() if v is not None)
    logger.info(
        "[snapshot_writer] upsert 완료 date=%s 필드=%d/%d",
        snapshot_date,
        non_null,
        len(payload),
    )


def today_str() -> str:
    """오늘 날짜를 KST 기준 'YYYY-MM-DD' 문자열로 반환."""
    return date.today().strftime("%Y-%m-%d")
