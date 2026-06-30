"""
engine/data/snapshot_writer.py
수집된 모든 지표를 icg.daily_snapshots에 UPSERT.

UNIQUE KEY: snapshot_date
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

from engine.common.schema_compat import extract_missing_column

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

_EXTENDED_FIELDS: tuple[str, ...] = (
    "sector_heatmap",
    "market_breadth",
    "rates_detail",
    "credit_detail",
    "fx_detail",
    "commodity_detail",
    "event_calendar",
    "news_items",
    "signal_quality",
    "data_quality",
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

# Public aliases for tests, docs, and pipeline gates.
EXPECTED_FIELDS = _EXPECTED_FIELDS
EXTENDED_FIELDS = _EXTENDED_FIELDS
CRITICAL_FIELDS = _CRITICAL_FIELDS

_UNKNOWN_SENTINELS = {"Unknown", "UNKNOWN", ""}


class CriticalDataMissingError(RuntimeError):
    """Raised when a snapshot is unsafe for autopublish because core fields are missing."""

    def __init__(
        self,
        critical_missing: list[str],
        *,
        context: str = "",
        quality: dict | None = None,
    ):
        self.critical_missing = critical_missing
        self.context = context
        self.quality = quality or {}
        suffix = f" ({context})" if context else ""
        super().__init__(
            "CRITICAL market data missing"
            f"{suffix}: {critical_missing}. "
            "자동 발행을 중단하고 데이터 소스/Secrets/네트워크를 확인하세요."
        )


def build_snapshot_payload(
    fred_data: dict,
    market_data: dict,
    feargreed_data: dict,
    crypto_data: dict,
    sentiment_data: dict,
    extended_data: dict | None = None,
) -> dict[str, Any]:
    """Merge fetcher outputs into the canonical daily_snapshots payload."""
    return {
        **fred_data,
        **market_data,
        **feargreed_data,
        **crypto_data,
        **sentiment_data,
        **(extended_data or {}),
    }


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


def enforce_critical_quality(payload: dict, *, context: str = "") -> dict[str, list[str]]:
    """Raise when critical market data needed for autopublish is missing.

    Returns the quality summary when the payload is safe. Callers can log or persist
    the returned summary without recomputing it.
    """
    quality = summarize_quality(payload)
    critical_missing = quality["critical_missing"]
    if critical_missing:
        raise CriticalDataMissingError(critical_missing, context=context, quality=quality)
    return quality


def _missing_schema_column_from_error(exc: Exception) -> str | None:
    """Extract a PostgREST schema-cache missing-column name from an exception.

    Backward-compatible wrapper. Delegates to the single source of truth in
    engine.common.schema_compat.extract_missing_column.
    """
    return extract_missing_column(exc)


def _upsert_snapshot_schema_compatible(snapshot_date: str, payload: dict[str, Any]) -> None:
    """Upsert snapshot payload, retrying without additive columns absent from DB schema.

    GitHub Actions can run code ahead of a Supabase migration/schema-cache refresh. In
    that case PostgREST returns PGRST204 for a newly-added optional column such as
    data_quality. The core market snapshot must still be saved, so we strip only the
    reported additive column and retry. Required/base columns remain fail-fast.
    """
    from engine.common.supabase_client import upsert_snapshot

    remaining = dict(payload)
    stripped: list[str] = []
    while True:
        try:
            upsert_snapshot(snapshot_date, remaining)
            if stripped:
                logger.warning(
                    "[snapshot_writer] DB schema missing optional columns; "
                    "upsert retried without fields=%s. Apply pending migrations.",
                    stripped,
                )
            return
        except Exception as exc:
            missing_column = _missing_schema_column_from_error(exc)
            if not missing_column or missing_column not in remaining:
                raise
            if missing_column not in _EXTENDED_FIELDS:
                raise
            stripped.append(missing_column)
            remaining.pop(missing_column, None)


def upsert_payload(snapshot_date: str, payload: dict[str, Any]) -> None:
    """Upsert a canonical daily_snapshots payload without re-merging fetcher parts."""
    _upsert_snapshot_schema_compatible(snapshot_date, payload)

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

    present_extended = [key for key in _EXTENDED_FIELDS if key in payload]
    if present_extended:
        logger.info(
            "[snapshot_writer] 확장 데이터 포함 date=%s fields=%s",
            snapshot_date,
            present_extended,
        )


def upsert(
    snapshot_date: str,
    fred_data: dict,
    market_data: dict,
    feargreed_data: dict,
    crypto_data: dict,
    sentiment_data: dict,
    extended_data: dict | None = None,
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
        extended_data: optional P0/P1 enrichment JSONB fields.
    """
    payload = build_snapshot_payload(
        fred_data,
        market_data,
        feargreed_data,
        crypto_data,
        sentiment_data,
        extended_data,
    )

    # None 값은 Supabase에 그대로 null 저장 (허용)
    _upsert_snapshot_schema_compatible(snapshot_date, payload)

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

    present_extended = [key for key in _EXTENDED_FIELDS if key in payload]
    if present_extended:
        logger.info(
            "[snapshot_writer] 확장 데이터 포함 date=%s fields=%s",
            snapshot_date,
            present_extended,
        )


def today_str() -> str:
    """오늘 날짜를 KST 기준 'YYYY-MM-DD' 문자열로 반환."""
    return date.today().strftime("%Y-%m-%d")
