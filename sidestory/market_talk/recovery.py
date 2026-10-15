"""Read-only watchdog planning; no generation, reservation, Graph or POST calls."""
from __future__ import annotations

import argparse
import json
import os
from datetime import date, datetime, time, timedelta
from pathlib import Path

from sidestory.market_talk.policy import KST, timestamp

TERMINAL = {"CONTENT_HOLD", "MODEL_HOLD", "RESULT_PERSISTENCE_HOLD", "RETRY_EXHAUSTED"}
RETRYABLE_CODES = {
    "DB_API_FAILURE", "PROVIDER_TIMEOUT", "PROVIDER_CONNECTION_FAILURE",
}


def audit_day(now):
    day = now.astimezone(KST).date() - timedelta(days=1)
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return day


def plan(snapshot, mode="recovery"):
    """Plans use a single DB snapshot and its clock, never the event's timestamp."""
    now = timestamp(snapshot["db_now"])
    day = date.fromisoformat(snapshot["slot_date"])
    result = {"slot_date": day.isoformat(), "action": "none", "allowed": False,
              "db_now": now.isoformat(), "revision": ""}
    def stop(status):
        return {**result, "status": status}

    deliveries = snapshot.get("deliveries") or []
    if snapshot.get("unresolved", 0):
        return stop("RECONCILE_REQUIRED")
    published = [r for r in deliveries if r["state"] == "PUBLISHED"]
    if len(published) > 1:
        return stop("MULTIPLE_TALK_DELIVERIES")
    if published:
        row = published[0]
        result["revision"] = row["revision"]
        if row.get("verified"):
            return stop("WATCH_OK")
        recovery = snapshot.get("recovery") or {}
        if recovery.get("verification_retry_count", 0) >= 3:
            return stop("VERIFY_EXHAUSTED")
        if recovery.get("lease_expires_at") and timestamp(recovery["lease_expires_at"]) > now:
            return stop("IN_PROGRESS")
        if recovery.get("next_retry_at") and timestamp(recovery["next_retry_at"]) > now:
            return stop("RETRY_WAIT")
        if not row.get("post_id"):
            return stop("RECONCILE_REQUIRED")
        return {**stop("VERIFY_REQUIRED"), "action": "verify"}
    if mode == "audit":
        return stop("MISSED_FINAL")
    if day != now.astimezone(KST).date() or day.weekday() >= 5:
        return stop("OUTSIDE_RECOVERY_DAY")
    policy = snapshot.get("policy") or {}
    if not policy.get("enabled"):
        return stop("CHANNEL_HOLD")
    if policy.get("policy_version") != 5 or day < date.fromisoformat(policy["effective_from"]):
        return stop("POLICY_NOT_EFFECTIVE")
    slot = snapshot.get("slot")
    if slot:
        if slot.get("policy_version") != 5:
            return stop("LEGACY_SLOT")
        result.update(due_at=slot["due_at"], normal_end=slot["normal_end"],
                      recovery_end=slot["window_end"])
        if now >= timestamp(slot["window_end"]):
            return stop("MISSED_FINAL")
        if mode == "normal" and now >= timestamp(slot["normal_end"]):
            return stop("PENDING_RECOVERY")
        if now < timestamp(slot["due_at"]):
            return stop("WAITING_SLOT")
    else:
        if now >= datetime.combine(day, time(23, 30), KST):
            return stop("MISSED_FINAL")
        if mode == "normal" and now >= datetime.combine(day, time(18), KST):
            return stop("PENDING_RECOVERY")
        if now < datetime.combine(day, time(13), KST):
            return stop("WAITING_SLOT")
    if deliveries and any(r["state"] != "RETRY_WAIT" for r in deliveries):
        return stop("RECONCILE_REQUIRED")
    recovery = snapshot.get("recovery") or {}
    if recovery.get("lease_expires_at") and timestamp(recovery["lease_expires_at"]) > now:
        return stop("IN_PROGRESS")
    if recovery.get("execution_count", 0) >= 3:
        return stop("RETRY_EXHAUSTED")
    if recovery.get("last_status") == "HOLD":
        return stop("HOLD")
    if recovery.get("next_retry_at") and timestamp(recovery["next_retry_at"]) > now:
        return stop("RETRY_WAIT")
    drafts, models = snapshot.get("drafts") or [], snapshot.get("models") or []
    if len(drafts) > 1:
        return stop("MULTIPLE_DRAFTS")
    if any(m["state"] != "COMPLETE" for m in models):
        return stop("MODEL_HOLD")
    if snapshot.get("cost_count", 0) > len(models) or (not drafts and models):
        return stop("RESULT_PERSISTENCE_HOLD")
    if drafts:
        row = drafts[0]
        result["revision"] = row["revision"]
        if row["status"] == "CONTENT_HOLD":
            return stop("CONTENT_HOLD")
        if row["status"] == "DRAFT" and any(m["phase"] == "review" for m in models):
            return stop("RESULT_PERSISTENCE_HOLD")
        if row["status"] not in {"DRAFT", "APPROVED"}:
            return stop("RECONCILE_REQUIRED")
    return {**stop("RECOVERY_ELIGIBLE" if slot else "NO_RUN"),
            "action": "normal" if mode == "normal" else "recovery"}


def retryable(report):
    # Once a paid call or POST might have happened, do not replay.
    return (
        report.get("phase") in {"source", "page_identity", "queue", "talk_preflight"}
        and not report.get("outcome_unknown")
        and bool(set(report.get("blockers", [])) & RETRYABLE_CODES)
    )


def recovery_enabled():
    return all(os.environ.get(name, "false").lower() == "true" for name in (
        "MARKET_TALK_WATCHDOG_AUTO_RECOVERY_ENABLED", "MARKET_TALK_SCHEDULE_ENABLED",
        "MARKET_TALK_AUTO_ENABLED", "MARKET_TALK_LIVE",
    ))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit", action="store_true")
    parser.add_argument("--final", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args(argv)
    report = {"status": "WATCH_ALERT", "action": "none", "slot_date": "", "revision": ""}
    try:
        from sidestory.market_talk.__main__ import connection
        from sidestory.market_talk.store_v5 import TalkStoreV5
        store = TalkStoreV5(connection())
        store.require_hardening()
        page = os.environ["FACE_PAGE_ID"]
        # DB clock; do not derive the target day from a delayed event.
        clock = store.snapshot(page, date(2000, 1, 1))
        now = timestamp(clock["db_now"])
        day = audit_day(now) if args.audit or (args.final and now.astimezone(KST).hour < 13) else now.astimezone(KST).date()
        report = plan(store.snapshot(page, day), "audit" if args.audit else "recovery")
        if args.audit or args.final or not recovery_enabled():
            report["planned_action"] = report["action"]
            report["action"] = "none"
        report["mode"] = "read_only"
    except Exception:
        report.update(status="DB_UNAVAILABLE", action="none")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False))
    if args.github_output:
        # Only allowlisted action, ISO date and DB revision are exported.
        action = report["action"] if report["action"] in {"normal", "recovery", "verify"} else "none"
        day = report.get("slot_date", "")
        revision = report.get("revision", "")
        if day:
            date.fromisoformat(day)
        if revision and (len(revision) != 64 or any(c not in "0123456789abcdef" for c in revision)):
            raise ValueError("invalid revision")
        with args.github_output.open("a") as output:
            output.write(f"action={action}\nslot_date={day}\nrevision={revision}\n")
    return 1 if report["status"] in {"DB_UNAVAILABLE", "RECONCILE_REQUIRED",
                                    "MISSED_FINAL", "VERIFY_EXHAUSTED"} else 0


if __name__ == "__main__":
    raise SystemExit(main())
