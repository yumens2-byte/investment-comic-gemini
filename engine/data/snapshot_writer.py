"""
engine/data/snapshot_writer.py
수집된 모든 지표를 icg.daily_snapshots에 UPSERT.

UNIQUE KEY: snapshot_date
"""

from __future__ import annotations

import logging
from datetime import date

logger = logging.getLogger(__name__)


_EXPECTED_FIELDS: tuple[str, ...] = (
    "fed_funds_rate",
    "us10y",
    "vix",
    "oil_wti",
    "dollar_index",
    "hy_spread",
    "yield_curve",
    "spy_change",
    "nasdaq_change",
    "btc_usd",
    "usdkrw",
    "fear_greed",
    "fear_greed_label",
    "crypto_basis_spread",
    "crypto_basis_state",
    "btc_social_sentiment",
    "btc_sentiment_state",
)

_CRITICAL_FIELDS: tuple[str, ...] = (
    "us10y",
    "vix",
    "oil_wti",
    "spy_change",
    "nasdaq_change",
    "btc_usd",
    "usdkrw",
    "fear_greed",
)

_UNKNOWN_SENTINELS = {"Unknown", "UNKNOWN", ""}


def _is_missing_quality_value(value: object) -> bool:
    """Return True when a snapshot value should be treated as missing for quality logs."""
    return value is None or value in _UNKNOWN_SENTINELS


def summarize_quality(payload: dict) -> dict[str, list[str]]:
    """Build a small data-quality summary for market snapshot operations."""
    missing = [key for key in _EXPECTED_FIELDS if _is_missing_quality_value(payload.get(key))]
    critical_missing = [key for key in _CRITICAL_FIELDS if key in missing]
    optional_missing = [key for key in missing if key not in _CRITICAL_FIELDS]
    return {
        "missing": missing,
        "critical_missing": critical_missing,
        "optional_missing": optional_missing,
    }


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

    quality = summarize_quality(payload)
    non_null = sum(1 for v in payload.values() if v is not None)
    logger.info(
        "[snapshot_writer] upsert 완료 date=%s 필드=%d/%d missing=%d",
        snapshot_date,
        non_null,
        len(payload),
        len(quality["missing"]),
    )
    if quality["critical_missing"]:
        logger.warning(
            "[snapshot_writer] CRITICAL 데이터 누락 date=%s fields=%s",
            snapshot_date,
            quality["critical_missing"],
        )
    if quality["optional_missing"]:
        logger.warning(
            "[snapshot_writer] 보조/스토리 강화 데이터 누락 date=%s fields=%s",
            snapshot_date,
            quality["optional_missing"],
        )


def today_str() -> str:
    """오늘 날짜를 KST 기준 'YYYY-MM-DD' 문자열로 반환."""
    return date.today().strftime("%Y-%m-%d")
