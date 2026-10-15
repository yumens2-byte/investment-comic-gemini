"""Persisted weekday afternoon scheduling. The database arbitrates competing polls."""

import secrets
from datetime import date, datetime, time

from sidestory.market_talk.policy import KST, PolicyError, Slot, timestamp


def candidate_slot(now, requested_day="", randbelow=None):
    if now.tzinfo is None:
        raise PolicyError("AWARE_CLOCK_REQUIRED", "slot")
    day = date.fromisoformat(requested_day) if requested_day else now.astimezone(KST).date()
    if day != now.astimezone(KST).date():
        raise PolicyError("SLOT_DATE_MISMATCH", "slot")
    if day.weekday() >= 5:
        raise PolicyError("SKIPPED_WEEKEND", "slot")
    minute = (randbelow or secrets.randbelow)(271)
    return Slot(
        day,
        datetime.combine(day, time(13 + minute // 60, minute % 60), KST),
        datetime.combine(day, time(18), KST),
    )


def saved_slot(row):
    if not isinstance(row, dict):
        raise PolicyError("SLOT_UNAVAILABLE", "slot")
    try:
        day = date.fromisoformat(row["slot_date"])
        due, end = timestamp(row["due_at"]), timestamp(row["window_end"])
        if row.get("policy_version") in (4, "market-talk-4", 5, "market-talk-5"):
            if (
                day.weekday() >= 5
                or not datetime.combine(day, time(13), KST)
                <= due
                <= datetime.combine(day, time(17, 30), KST)
                or due.second
                or due.microsecond
                or end != datetime.combine(
                    day, time(23, 30) if row.get("policy_version") in (5, "market-talk-5")
                    else time(18), KST
                )
            ):
                raise ValueError()
        if row.get("policy_version") in (5, "market-talk-5") and timestamp(
            row.get("normal_end")
        ) != datetime.combine(day, time(18), KST):
            raise ValueError()
        if due.astimezone(KST).date() != day or end.astimezone(KST).date() != day or due >= end:
            raise ValueError()
    except (KeyError, TypeError, ValueError):
        raise PolicyError("SLOT_INVALID", "slot") from None
    return Slot(day, due, end)


def ensure_slot(store, page, now, requested_day=""):
    candidate = candidate_slot(now, requested_day)
    result = saved_slot(store.ensure_schedule(page, candidate.day, candidate.due))
    if result.day != candidate.day:
        raise PolicyError("SLOT_DATE_MISMATCH", "slot")
    return result


def slot_status(target, now):
    if now.tzinfo is None:
        raise PolicyError("AWARE_CLOCK_REQUIRED", "slot")
    if target.day.weekday() >= 5:
        return "SKIPPED_WEEKEND"
    if now >= target.end:
        return "MISSED_WINDOW"
    if now < target.due:
        return "WAITING_SLOT"
    return "READY"
