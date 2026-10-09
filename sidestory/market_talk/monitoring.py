"""Read-only slot completion checks. Never generate, approve, retry or publish."""

from datetime import date, datetime, time, timedelta

from sidestory.market_talk.policy import KST, slot


def completed_day(now):
    day = now.astimezone(KST).date()
    if now < datetime.combine(day, time(23, 59), KST):
        day -= timedelta(days=1)
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return day


def watch(store, page, now, requested_day=""):
    day = date.fromisoformat(requested_day) if requested_day else completed_day(now)
    target = slot(now, day.isoformat())
    if day.weekday() >= 5:
        return {"status": "SKIPPED_WEEKEND", "slot_date": day.isoformat(), "allowed": False}
    if now < target.end:
        return {"status": "WATCH_PENDING", "slot_date": day.isoformat(), "allowed": False}
    start = datetime.combine(day, time.min, KST)
    deliveries = store.day_deliveries(page, start, start + timedelta(days=1))
    outcomes = store.slot_outcomes(page, day.isoformat())
    verified = [
        r
        for r in outcomes
        if r["status"] == "PUBLISHED" and r["reason_code"] == "PUBLISHED_VERIFIED"
    ]
    published = [d for d in deliveries if d["state"] == "PUBLISHED"]
    if any(d["state"] in {"SENDING", "UNKNOWN"} for d in deliveries):
        status, code = "WATCH_ALERT", "UNRESOLVED_DELIVERY"
    elif len(published) > 1:
        status, code = "WATCH_ALERT", "MULTIPLE_TALK_DELIVERIES"
    elif published and any(v["revision"] == published[0]["business_key"] for v in verified):
        status, code = "WATCH_OK", "PUBLISHED_VERIFIED"
    elif published:
        status, code = "WATCH_ALERT", "POSTED_UNVERIFIED"
    else:
        status, code = "WATCH_ALERT", "MISSED_PUBLICATION_SLOT"
    return {
        "status": status,
        "slot_date": day.isoformat(),
        "blockers": [code] if status == "WATCH_ALERT" else [],
        "allowed": False,
        "automatic_retry": False,
        "observed_outcomes": len(outcomes),
    }
