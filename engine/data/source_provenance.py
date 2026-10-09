"""Field provenance: never substitute a collection date for a provider date."""

from __future__ import annotations

from datetime import date, datetime, timezone
from math import isfinite
from typing import Any

UNITS = {
    "vix": "index",
    "us10y": "percent",
    "oil_wti": "USD_per_barrel",
    "spy_change": "percent",
    "nasdaq_change": "percent",
    "fear_greed": "index",
    "btc_usd": "USD",
    "usdkrw": "KRW_per_USD",
    "fed_funds_rate": "percent",
    "dollar_index": "index",
    "hy_spread": "percent",
    "yield_curve": "percent",
}


def provenance(
    *,
    field: str,
    provider: str,
    instrument: str,
    value: Any,
    session: Any = None,
    source_timestamp: datetime | None = None,
    fetched_at: datetime | None = None,
    status: str = "ok",
    **extra: Any,
) -> dict:
    """observed_at means response observation, not an invented market close time.

    Daily series expose a date only; preserve that precision separately. Exact
    provider timestamps, when available, are used for observed_at instead.
    """
    fetched = fetched_at or datetime.now(timezone.utc)
    if fetched.tzinfo is None:
        raise ValueError("fetched_at must be timezone-aware")
    session_date = None
    if isinstance(session, (datetime, date)):
        session_date = session.date() if isinstance(session, datetime) else session
    elif isinstance(session, str):
        try:
            session_date = date.fromisoformat(session)
        except ValueError:
            pass
    numeric = isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value)
    if not numeric:
        status = "missing" if value is None else "invalid_value"
    elif session_date is None:
        status = "metadata_missing"
    if source_timestamp is not None and source_timestamp.tzinfo is None:
        raise ValueError("source_timestamp must be timezone-aware")
    observed = source_timestamp or fetched
    result = {
        "status": status,
        "provider": provider,
        "instrument": instrument,
        "unit": UNITS[field],
        "value": value if numeric else None,
        "observed_at": observed.isoformat(),
        "observed_at_kind": "provider_timestamp" if source_timestamp else "response_received",
        "fetched_at": fetched.isoformat(),
        "market_session_date": session_date.isoformat() if session_date else None,
        "source_time_precision": "timestamp" if source_timestamp else "date",
        **extra,
    }
    if source_timestamp:
        result["source_timestamp"] = source_timestamp.isoformat()
    return result
