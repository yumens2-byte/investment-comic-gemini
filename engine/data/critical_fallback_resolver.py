"""Resolve missing critical market data with auditable fallback metadata.

The resolver runs after fetchers build the canonical snapshot payload and before
CriticalDataGate.  It never invents values: it can only copy a non-missing value
from an allowed fallback source that is fresh enough for the field policy.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from engine.data.snapshot_writer import CRITICAL_FIELDS, summarize_quality

logger = logging.getLogger(__name__)

_VERSION = "2026-06-20.v1"
_UNKNOWN_SENTINELS = {None, "", "Unknown", "UNKNOWN"}


@dataclass(frozen=True)
class FallbackPolicy:
    max_age_days: int
    strategy: str = "previous_snapshot"
    confidence: float = 0.70


# Conservative stale windows: market-direction sensitive fields get the shortest
# window, slow-moving macro fields get a longer window.
_FALLBACK_POLICIES: dict[str, FallbackPolicy] = {
    "btc_usd": FallbackPolicy(max_age_days=2, confidence=0.72),
    "fear_greed": FallbackPolicy(max_age_days=3, confidence=0.82),
    "usdkrw": FallbackPolicy(max_age_days=2, confidence=0.70),
    "spy_change": FallbackPolicy(max_age_days=1, confidence=0.62),
    "nasdaq_change": FallbackPolicy(max_age_days=1, confidence=0.62),
    "us10y": FallbackPolicy(max_age_days=3, confidence=0.74),
    "vix": FallbackPolicy(max_age_days=1, confidence=0.60),
    "oil_wti": FallbackPolicy(max_age_days=3, confidence=0.72),
}


def _is_missing(value: Any) -> bool:
    return value in _UNKNOWN_SENTINELS


def _parse_date(value: Any) -> date | None:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if value is None:
        return None
    try:
        return datetime.fromisoformat(str(value)[:10]).date()
    except ValueError:
        return None


def _age_days(snapshot_date: str, fallback_date: Any) -> int | None:
    target = _parse_date(snapshot_date)
    source = _parse_date(fallback_date)
    if target is None or source is None:
        return None
    return (target - source).days


def _load_recent_snapshots(snapshot_date: str, *, limit: int = 10) -> list[dict[str, Any]]:
    """Load previous daily_snapshots rows for fallback candidates.

    This function is intentionally tiny and isolated so tests can monkeypatch it
    without needing Supabase credentials.
    """
    from engine.common.supabase_client import icg_table

    rows = (
        icg_table("daily_snapshots")
        .select("*")
        .lt("snapshot_date", snapshot_date)
        .order("snapshot_date", desc=True)
        .limit(limit)
        .execute()
    )
    return rows.data or []


def _fallback_from_previous_snapshot(
    *,
    field: str,
    snapshot_date: str,
    recent_snapshots: list[dict[str, Any]],
) -> tuple[Any, dict[str, Any] | None, str | None]:
    policy = _FALLBACK_POLICIES[field]
    for row in recent_snapshots:
        fallback_date = row.get("snapshot_date")
        age = _age_days(snapshot_date, fallback_date)
        if age is None:
            return None, None, f"{field}: fallback snapshot date invalid"
        if age < 0:
            continue
        if age > policy.max_age_days:
            return (
                None,
                None,
                f"{field}: stale source too old age_days={age} max={policy.max_age_days}",
            )
        value = row.get(field)
        if _is_missing(value):
            continue
        trace = {
            "field": field,
            "strategy": policy.strategy,
            "source": "daily_snapshots",
            "as_of": str(fallback_date),
            "age_days": age,
            "value_type": "stale_snapshot_value",
            "confidence": policy.confidence,
        }
        return value, trace, None
    return None, None, f"{field}: no eligible previous snapshot fallback"


def resolve_critical_fallbacks(
    *,
    snapshot_date: str,
    payload: dict[str, Any],
    source_status: dict[str, Any] | None = None,
    recent_snapshots: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Fill missing critical fields from allowed stale sources.

    Args:
        snapshot_date: Target snapshot date in YYYY-MM-DD format.
        payload: Canonical snapshot payload built from fetchers.
        source_status: Optional diagnostics from fetchers.
        recent_snapshots: Optional test/worker injected previous snapshot rows.

    Returns:
        A tuple of (resolved_payload, data_quality_metadata).
    """
    resolved_payload = dict(payload)
    quality_before = summarize_quality(resolved_payload)
    missing_before = list(quality_before["critical_missing"])
    fallbacks: list[dict[str, Any]] = []
    blocked_fields: list[str] = []

    if missing_before:
        if recent_snapshots is None:
            try:
                recent_snapshots = _load_recent_snapshots(snapshot_date)
            except Exception as exc:
                logger.warning("[CriticalFallback] previous snapshot lookup failed: %s", exc)
                recent_snapshots = []
        for field in missing_before:
            if field not in _FALLBACK_POLICIES:
                blocked_fields.append(f"{field}: no fallback policy")
                continue
            value, trace, block_reason = _fallback_from_previous_snapshot(
                field=field,
                snapshot_date=snapshot_date,
                recent_snapshots=recent_snapshots,
            )
            if trace is not None and not _is_missing(value):
                resolved_payload[field] = value
                fallbacks.append(trace)
            elif block_reason:
                blocked_fields.append(block_reason)

    quality_after = summarize_quality(resolved_payload)
    missing_after = list(quality_after["critical_missing"])
    status = "complete"
    if missing_after:
        status = "blocked"
    elif fallbacks:
        status = "resolved_with_fallback"

    data_quality = {
        "critical_fallback_version": _VERSION,
        "status": status,
        "missing_before": missing_before,
        "missing_after": missing_after,
        "fallbacks": fallbacks,
        "blocked_fields": blocked_fields,
        "source_status": source_status or {},
        "critical_fields": list(CRITICAL_FIELDS),
    }

    if missing_before or fallbacks or blocked_fields:
        logger.info(
            "[CriticalFallback] status=%s missing_before=%s resolved=%s blocked=%s",
            status,
            missing_before,
            [item["field"] for item in fallbacks],
            blocked_fields,
        )

    return resolved_payload, data_quality
