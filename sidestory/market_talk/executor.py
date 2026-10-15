"""Actions normal/recovery worker. Defaults to a read-only plan; no dispatch API."""
from __future__ import annotations

import argparse
import json
import os
from datetime import date
from pathlib import Path
from uuid import uuid4

from sidestory.market_talk.content import utcnow
from sidestory.market_talk.diagnostics import failure_report
from sidestory.market_talk.policy import KST, timestamp
from sidestory.market_talk.recovery import plan, recovery_enabled, retryable


def execute(client, store, page, *, day, mode, run, automatic, publish_one, verify_one):
    snapshot = store.snapshot(page, day)
    decision = plan(snapshot, "normal" if mode == "normal" else "recovery")
    if decision["action"] == "none":
        return decision
    if mode == "verify" and decision["action"] != "verify":
        return {**decision, "action": "none", "status": "VERIFY_BLOCKED"}
    if decision["action"] == "verify":
        store.mode = "verify"
    else:
        # Schedules are created only for an eligible current day.
        from sidestory.market_talk.scheduling import ensure_slot
        ensure_slot(store, page, timestamp(snapshot["db_now"]), day.isoformat())
    claim = store.claim(page, day, run)
    if claim["status"] != "CLAIMED":
        return {**decision, **claim, "action": "none"}
    try:
        if store.mode == "verify":
            report = verify_one(decision["revision"])
        else:
            report = automatic(timestamp(claim["db_now"]))
            if report["status"] == "AUTO_APPROVED":
                report = {**report, **publish_one(report["revision"])}
        report.setdefault("slot_date", day.isoformat())
        report.setdefault("run_id", run)
        store.record_outcome(page, day.isoformat(), run,
                             "verify" if store.mode == "verify" else "automate", report)
        store.complete(page, day, report,
                       retryable=report.get("status") == "POSTED_UNVERIFIED" or retryable(report))
        report["outcome_recorded"] = True
        return report
    except Exception as exc:
        report = failure_report(exc, "execution")
        report.update(slot_date=day.isoformat(), run_id=run)
        try:
            store.record_outcome(page, day.isoformat(), run,
                                 "verify" if store.mode == "verify" else "automate", report)
            store.complete(page, day, report, retryable=retryable(report))
            report["outcome_recorded"] = True
        except Exception:
            report.update(outcome_recorded=False, automatic_retry=False)
        return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["normal", "recovery", "verify"], default="normal")
    parser.add_argument("--slot-date", default="")
    parser.add_argument("--revision", default="")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    report = {"status": "BLOCKED", "blockers": ["WORKER_UNAVAILABLE"]}
    try:
        from sidestory.market_talk.__main__ import (
            ROOT, connection, current, flag, live_publisher, publish_live,
        )
        from sidestory.market_talk.automation import automatic_draft
        from sidestory.market_talk.service import verify_publication
        from sidestory.market_talk.store_v5 import TalkStoreV5
        client = connection()
        store = TalkStoreV5(client, owner=str(uuid4()), mode=args.mode)
        store.require_hardening()
        page = os.environ["FACE_PAGE_ID"]
        clock = store.snapshot(page, date(2000, 1, 1))
        now = timestamp(clock["db_now"])
        day = date.fromisoformat(args.slot_date) if args.slot_date else now.astimezone(KST).date()
        if args.revision:
            row = store.item(args.revision)
            if row["page_id"] != page:
                raise ValueError("Page mismatch")
            from sidestory.market_talk.content import Draft
            exact_day = Draft.model_validate(row["payload"]).due_at.astimezone(KST).date()
            if args.slot_date and day != exact_day:
                raise ValueError("slot mismatch")
            day = exact_day
            if args.mode != "verify":
                raise ValueError("exact revision is supported by verify only")
        if not args.live:
            report = {**plan(store.snapshot(page, day)), "mode": "read_only"}
        elif args.mode != "normal" and not recovery_enabled():
            report = {"status": "BLOCKED", "blockers": ["RECOVERY_DISABLED"]}
        elif not all(flag(name) for name in ("MARKET_TALK_LIVE", "MARKET_TALK_AUTO_ENABLED",
                                            "MARKET_TALK_SCHEDULE_ENABLED")):
            report = {"status": "BLOCKED", "blockers": ["LIVE_GATES_DISABLED"]}
        elif flag("DRY_RUN", "true"):
            report = {"status": "BLOCKED", "blockers": ["LIVE_GATES_DISABLED"]}
        else:
            def automatic(at):
                return automatic_draft(
                    client, store, page, canon_path=ROOT / "config/characters.yaml",
                    allowed=set(filter(None, os.environ.get("MARKET_TALK_CHARACTER_IDS", "").split(","))),
                    now=at, source_commit=os.environ.get("GITHUB_SHA", ""),
                    model=os.environ.get("MARKET_TALK_MODEL", ""),
                    input_rate=os.environ.get("MARKET_TALK_INPUT_USD_PER_MTOK", "0"),
                    output_rate=os.environ.get("MARKET_TALK_OUTPUT_USD_PER_MTOK", "0"),
                    current=current, slot_date=day.isoformat(),
                    page_check=lambda: live_publisher(page).check(),
                )
            report = execute(
                client, store, page, day=day, mode=args.mode,
                run=os.environ.get("GITHUB_RUN_ID", "local") + ":" + os.environ.get("GITHUB_RUN_ATTEMPT", "1"),
                automatic=automatic,
                publish_one=lambda revision: publish_live(client, store, page, revision, utcnow()),
                verify_one=lambda revision: verify_publication(
                    revision, store, live_publisher(page), now=utcnow()),
            )
    except Exception as exc:
        report = failure_report(exc, "execution")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["status"] in {
        "PUBLISHED", "WATCH_OK", "ALREADY_PUBLISHED", "WAITING_SLOT",
        "PENDING_RECOVERY", "IN_PROGRESS", "RETRY_WAIT",
    } else 1


if __name__ == "__main__":
    raise SystemExit(main())
