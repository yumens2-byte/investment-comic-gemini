"""Pure slot and source policies. Thresholds are screening bounds, not verified prices."""

import math
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

from sidestory.market_talk.content import digest

KST = timezone(timedelta(hours=9))
SOURCE_VIEW = "market_talk_source_v1"
FIELDS = ("vix", "us10y", "oil_wti", "spy_change", "nasdaq_change", "fear_greed")
LEGACY_FIELDS = (*FIELDS, "snapshot_date", "dollar_index", "hy_spread")
UNITS = {
    "vix": "index",
    "us10y": "percent",
    "oil_wti": "USD_per_barrel",
    "spy_change": "percent",
    "nasdaq_change": "percent",
    "fear_greed": "index",
}
# Broad operational sanity checks only. Negative WTI futures are possible.
BOUNDS = {
    "vix": (0, 200),
    "us10y": (-10, 30),
    "oil_wti": (-100, 1000),
    "spy_change": (-100, 100),
    "nasdaq_change": (-100, 100),
    "fear_greed": (0, 100),
}


class PolicyError(ValueError):
    def __init__(self, code, phase="source"):
        self.code, self.phase = code, phase
        super().__init__(code)


def timestamp(value):
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.tzinfo is None:
            raise ValueError()
        return result
    except (ValueError, AttributeError, TypeError):
        raise PolicyError("SOURCE_TIMESTAMP_REQUIRED") from None


@dataclass(frozen=True)
class Slot:
    day: date
    due: datetime
    end: datetime

    def status(self, now):
        if self.day.weekday() >= 5:
            return "SKIPPED_WEEKEND"
        if now < self.due or now >= self.end:
            return "SKIPPED_OUTSIDE_WINDOW"
        return "READY"


def slot(now, requested_day=""):
    if now.tzinfo is None:
        raise PolicyError("AWARE_CLOCK_REQUIRED", "slot")
    day = date.fromisoformat(requested_day) if requested_day else now.astimezone(KST).date()
    return Slot(
        day, datetime.combine(day, time(18, 30), KST), datetime.combine(day, time(23, 59), KST)
    )


def scheduled_slot(now, requested_day=""):
    if requested_day:
        return slot(now, requested_day)
    today = slot(now)
    if now < today.due:
        previous = today.day - timedelta(days=1)
        while previous.weekday() >= 5:
            previous -= timedelta(days=1)
        return slot(now, previous.isoformat())
    return today


def source_hash(snapshot, policy_version):
    if policy_version != "market-talk-3":
        # v1/v2 revisions were hashed from the old projection; do not mutate them.
        snapshot = {k: snapshot[k] for k in LEGACY_FIELDS if k in snapshot}
    return digest(snapshot)


def validate_source(snapshot, now):
    """Require explicit upstream provenance. Never manufacture a provider/session."""
    try:
        day = date.fromisoformat(snapshot["snapshot_date"])
    except (ValueError, KeyError, TypeError):
        raise PolicyError("SOURCE_DATE_INVALID") from None
    if not 0 <= (now.astimezone(KST).date() - day).days <= 3:
        raise PolicyError("SOURCE_STALE")
    for field in FIELDS:
        value = snapshot.get(field)
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
        ):
            raise PolicyError("SOURCE_VALUE_INVALID")
        low, high = BOUNDS[field]
        if not low <= value <= high:
            raise PolicyError("SOURCE_VALUE_OUT_OF_RANGE")
    created = timestamp(snapshot.get("created_at"))
    if created > now + timedelta(minutes=5) or now - created > timedelta(days=4):
        raise PolicyError("SOURCE_COLLECTION_TIME_INVALID")
    quality = snapshot.get("data_quality")
    if not isinstance(quality, dict) or quality.get("status") != "complete":
        raise PolicyError("SOURCE_QUALITY_REQUIRED")
    for key in ("fallbacks", "missing_after", "blocked_fields"):
        if quality.get(key) != []:
            raise PolicyError("SOURCE_QUALITY_BLOCKED")
    sources = quality.get("source_status")
    if not isinstance(sources, dict):
        raise PolicyError("SOURCE_SESSION_REQUIRED")
    equity_sessions = set()
    for field in FIELDS:
        meta = sources.get(field)
        if not isinstance(meta, dict) or meta.get("status") != "ok":
            raise PolicyError("SOURCE_SESSION_REQUIRED")
        if not isinstance(meta.get("provider"), str) or not meta["provider"].strip():
            raise PolicyError("SOURCE_PROVIDER_REQUIRED")
        if meta.get("unit") != UNITS[field]:
            raise PolicyError("SOURCE_UNIT_MISMATCH")
        observed = timestamp(meta.get("observed_at"))
        if observed > now + timedelta(minutes=5) or now - observed > timedelta(days=4):
            raise PolicyError("SOURCE_OBSERVATION_STALE")
        try:
            session = date.fromisoformat(meta["market_session_date"])
        except (ValueError, KeyError, TypeError):
            raise PolicyError("SOURCE_SESSION_REQUIRED") from None
        if not 0 <= (day - session).days <= 3 or session > observed.astimezone(KST).date():
            raise PolicyError("SOURCE_SESSION_INVALID")
        if field in {"vix", "spy_change", "nasdaq_change"}:
            equity_sessions.add(session)
    if len(equity_sessions) != 1:
        raise PolicyError("SOURCE_SESSION_MISMATCH")
    return snapshot
