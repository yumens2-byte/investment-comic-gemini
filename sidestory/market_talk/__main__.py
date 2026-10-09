"""python -m sidestory.market_talk --help. Defaults to read-only inspection."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from uuid import uuid4

from sidestory.market_talk.content import Context, Draft, canon, utcnow
from sidestory.market_talk.diagnostics import failure_report, phase_call
from sidestory.market_talk.monitoring import watch
from sidestory.market_talk.policy import (
    KST,
    SOURCE_VIEW,
    scheduled_slot,
    source_hash,
    validate_source,
)
from sidestory.market_talk.service import (
    approve,
    inspect,
    publish,
    verified_receipt,
    verify_publication,
)
from sidestory.market_talk.store import TalkStore

ROOT = Path(__file__).resolve().parents[2]


def flag(name, default="false"):
    value = os.environ.get(name, default).strip().lower()
    if value not in {"true", "false"}:
        raise ValueError(f"{name} must be true or false")
    return value == "true"


def connection():
    from supabase import create_client

    url, key = os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_KEY")
    if not url or not key:
        raise ValueError("database credentials missing")
    return create_client(url, key)


def current(client, context):
    fields = canon(
        ROOT / "config/characters.yaml",
        context.character_id,
        set(filter(None, os.environ.get("MARKET_TALK_CHARACTER_IDS", "").split(","))),
    )
    rows = (
        client.schema("icg_side")
        .table(SOURCE_VIEW)
        .select("*")
        .eq("snapshot_date", context.snapshot_date)
        .execute()
        .data
    )
    if not isinstance(rows, list) or len(rows) != 1:
        raise ValueError("exact source snapshot unavailable")
    validate_source(rows[0], utcnow())
    return fields["canon_version"], source_hash(rows[0], context.policy_version)


def live_publisher(page):
    from sidestory.adapters.facebook.graph import FacebookPagePublisher

    return FacebookPagePublisher(page, os.environ.get("FACE_PAGE_TOKEN", ""))


def publish_live(client, store, page, revision, now):
    from sidestory.market_talk.publishing import ControlledPublisher

    row = phase_call("queue", store.item, revision)
    if row["page_id"] != page:
        raise ValueError("Page mismatch")
    draft = Draft.model_validate(row["payload"])
    if draft.revision != revision or draft.body != row["body"]:
        raise ValueError("stored content hash mismatch")
    # A recorded publication can only be read/verified, even after source expiry.
    if row["status"] == "PUBLISHED":
        report = phase_call(
            "verification", verify_publication, revision, store, live_publisher(page), now=now
        )
    else:
        ch, sh = phase_call("source", current, client, draft.context)
        pub = ControlledPublisher(
            live_publisher(page),
            store,
            page,
            revision,
            "talk",
            draft.context.expires_at.isoformat(),
        )
        report = phase_call(
            "delivery", publish, revision, store, pub, now=now, canon_hash=ch, snapshot_hash=sh
        )
    report["slot_date"] = draft.due_at.astimezone(KST).date().isoformat()
    report.setdefault("revision", revision)
    return report


def readiness(store, page):
    """Configuration visibility only; never checks Meta or approves content."""
    policy = store.optional_policy(page)
    blockers = []
    if policy is None:
        blockers.append("PAGE_POLICY_REQUIRED")
    elif not policy["enabled"] or not (
        policy["exclusive_managed"] or policy.get("coexistence_allowed", False)
    ):
        blockers.append("PAGE_POLICY_DISABLED_OR_UNMANAGED")
    if not os.environ.get("MARKET_TALK_CHARACTER_IDS", "").strip():
        blockers.append("CHARACTER_ALLOWLIST_REQUIRED")
    for name in ("FACEBOOK_CONTROL_ENABLED", "MARKET_TALK_LIVE"):
        if not flag(name):
            blockers.append(name + "_DISABLED")
    return {
        "status": "SETUP_REQUIRED" if blockers else "INSPECTED",
        "mode": "dry_run",
        "allowed": False,
        "needs_human_review": True,
        "page_policy_registered": policy is not None,
        "blockers": blockers,
        "errors": [],
        "meta_permissions_verified": False,
        "next_step": "Review Page policy and character allowlist, then prepare and submit a draft before revision inspection.",
    }


def emit_report(report, output):
    out = json.dumps(report, ensure_ascii=False, indent=2)
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(out + "\n", encoding="utf-8")
    print(out)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--stage",
        choices=[
            "inspect",
            "automate",
            "prepare",
            "preview",
            "submit",
            "approve",
            "publish",
            "pause",
            "resume",
            "reconcile",
            "hold",
            "verify",
            "watch",
        ],
        default="inspect",
    )
    p.add_argument("--input", type=Path)
    p.add_argument("--output", type=Path)
    p.add_argument("--revision", default="")
    p.add_argument("--actor", default="")
    p.add_argument("--note", default="")
    p.add_argument("--confirm", default="")
    p.add_argument("--live", action="store_true")
    p.add_argument("--attempt", type=int, default=1)
    p.add_argument("--post-id", default="")
    p.add_argument("--not-posted", action="store_true")
    p.add_argument("--slot-date", default="")
    p.add_argument("--scheduled", action="store_true")
    args = p.parse_args(argv)
    store = None
    page = ""
    now = utcnow()
    run = os.environ.get("GITHUB_RUN_ID") or ("local-" + uuid4().hex)
    phase = "input"
    mutation = args.stage in {
        "automate",
        "approve",
        "publish",
        "pause",
        "resume",
        "reconcile",
        "hold",
        "preview",
        "submit",
        "verify",
    }

    def finish(report):
        if (
            store is not None
            and args.stage
            in {"automate", "approve", "publish", "pause", "resume", "reconcile", "hold", "verify"}
            and (args.stage != "publish" or args.live)
        ):
            try:
                day = (
                    report.get("slot_date")
                    or args.slot_date
                    or now.astimezone(KST).date().isoformat()
                )
                phase_call(
                    "outcome_persistence", store.record_outcome, page, day, run, args.stage, report
                )
            except Exception as persistence_error:
                report["outcome_recorded"] = False
                report["outcome_record_error"] = failure_report(
                    persistence_error, "outcome_persistence"
                )["blockers"][0]
                report["automatic_retry"] = False
                if report.get("status") == "PUBLISHED":
                    report["status"] = "PUBLISHED_REPORT_PENDING"
                elif report.get("status") != "BLOCKED":
                    report["status"] = "BLOCKED"
                    report["blockers"] = ["OUTCOME_PERSISTENCE_FAILED"]
            else:
                report["outcome_recorded"] = True
        if args.stage not in {"prepare", "preview"}:
            report.setdefault("phase", phase)
            report.setdefault("run_id", run)
        emit_report(report, args.output)
        return (
            1
            if report.get("errors")
            or report.get("status")
            in {"BLOCKED", "POSTED_UNVERIFIED", "PUBLISHED_REPORT_PENDING", "WATCH_ALERT"}
            else 0
        )

    try:
        if args.stage == "approve":
            blockers = []
            if not args.revision:
                blockers.append("REVISION_REQUIRED")
            if args.confirm != "YES" or not args.actor.strip():
                blockers.append("HUMAN_CONFIRMATION_REQUIRED")
            if len(args.note.strip()) < 10:
                blockers.append("REVIEW_NOTE_REQUIRED")
            if blockers:
                return finish({"status": "BLOCKED", "blockers": blockers})
        if args.live and args.stage not in {"publish", "automate"}:
            raise ValueError("--live is only valid for publish")
        page = os.environ.get("FACE_PAGE_ID", "")
        if not page:
            raise ValueError("FACE_PAGE_ID required")
        phase = "connection"
        client = connection()
        store = TalkStore(client)
        if mutation or args.stage == "watch":
            phase_call("db_contract", store.require_hardening)
        if args.stage == "automate":
            from sidestory.market_talk.automation import automatic_draft

            if not flag("MARKET_TALK_AUTO_ENABLED"):
                return finish({"status": "BLOCKED", "blockers": ["AUTOMATION_DISABLED"]})
            if args.live and (
                flag("DRY_RUN", "true")
                or not flag("MARKET_TALK_LIVE")
                or not flag("FACEBOOK_CONTROL_ENABLED")
            ):
                return finish({"status": "BLOCKED", "blockers": ["LIVE_GATES_DISABLED"]})
            phase = "automation"
            report = automatic_draft(
                client,
                store,
                page,
                canon_path=ROOT / "config/characters.yaml",
                allowed=set(
                    filter(None, os.environ.get("MARKET_TALK_CHARACTER_IDS", "").split(","))
                ),
                now=now,
                source_commit=os.environ.get("GITHUB_SHA", ""),
                model=os.environ.get("MARKET_TALK_MODEL", ""),
                input_rate=os.environ.get("MARKET_TALK_INPUT_USD_PER_MTOK", "0"),
                output_rate=os.environ.get("MARKET_TALK_OUTPUT_USD_PER_MTOK", "0"),
                current=current,
                scheduled=args.scheduled,
                slot_date=args.slot_date,
            )
            if report["status"] == "AUTO_APPROVED" and args.live:
                report = publish_live(client, store, page, report["revision"], now)
        elif args.stage == "watch":
            phase = "watch"
            report = watch(store, page, now, args.slot_date)
        elif args.stage == "verify":
            phase = "verification"
            if not args.revision or store.item(args.revision)["page_id"] != page:
                raise ValueError("exact revision on configured Page required")
            row = store.item(args.revision)
            draft = Draft.model_validate(row["payload"])
            report = phase_call(
                "verification",
                verify_publication,
                args.revision,
                store,
                live_publisher(page),
                now=now,
            )
            report["slot_date"] = draft.due_at.astimezone(KST).date().isoformat()
        elif args.stage == "inspect" and not args.input and not args.revision:
            report = readiness(store, page)
        elif args.stage in {"pause", "resume", "reconcile", "hold"}:
            phase = "operation_" + args.stage
            if args.confirm != "YES" or not args.actor or len(args.note.strip()) < 20:
                raise ValueError("explicit YES, actor and documented reason required")
            if args.stage == "hold":
                if store.item(args.revision)["page_id"] != page:
                    raise ValueError("Page mismatch")
                result = store.rpc(
                    "talk_hold", p_revision=args.revision, p_actor=args.actor, p_note=args.note
                )
            elif args.stage == "reconcile":
                if bool(args.post_id) == args.not_posted or not args.revision:
                    raise ValueError(
                        "supply exact business key and post ID OR verified --not-posted"
                    )
                at = None
                if args.post_id:
                    from sidestory.adapters.facebook.graph import FacebookPagePublisher

                    pub = FacebookPagePublisher(page, os.environ.get("FACE_PAGE_TOKEN", ""))
                    receipt = pub.get_post(args.post_id)
                    at = verified_receipt(
                        page, args.post_id, receipt, store.delivery(page, args.revision), now
                    )
                result = store.rpc(
                    "facebook_resolve",
                    p_page=page,
                    p_key=args.revision,
                    p_post_id=args.post_id or None,
                    p_published_at=at,
                    p_actor=args.actor,
                    p_note=args.note,
                )
            else:
                result = store.set_hold(page, args.actor, args.note, enabled=args.stage == "resume")
            report = {"status": args.stage.upper(), "result": result}
        elif args.stage == "prepare":
            phase = "source"
            if not args.input or not args.output:
                raise ValueError("prepare requires provenance input and output path")
            data = json.loads(args.input.read_text())
            fields = canon(
                ROOT / "config/characters.yaml",
                data["character_id"],
                set(filter(None, os.environ.get("MARKET_TALK_CHARACTER_IDS", "").split(","))),
            )
            rows = (
                client.schema("icg_side")
                .table(SOURCE_VIEW)
                .select("*")
                .eq("snapshot_date", data["snapshot_date"])
                .execute()
                .data
            )
            if not isinstance(rows, list) or len(rows) != 1:
                raise ValueError("exact source snapshot unavailable")
            validate_source(rows[0], now)
            context = Context.model_validate(
                {
                    **data,
                    **fields,
                    "snapshot_hash": source_hash(
                        rows[0], data.get("policy_version", "market-talk-1")
                    ),
                }
            )
            report = context.model_dump(mode="json")
        elif args.stage == "preview":
            phase = "generation"
            if not args.input or not args.output:
                raise ValueError("preview requires context file and output path")
            from sidestory.market_talk.generation import generate

            context = Context.model_validate_json(args.input.read_text())
            ch, sh = current(client, context)
            if (
                ch != context.canon_version
                or sh != context.snapshot_hash
                or context.expires_at <= now
            ):
                raise ValueError("context changed or expired")
            copy = generate(
                context,
                store,
                page,
                model=os.environ.get("MARKET_TALK_MODEL", ""),
                input_rate=os.environ.get("MARKET_TALK_INPUT_USD_PER_MTOK", "0"),
                output_rate=os.environ.get("MARKET_TALK_OUTPUT_USD_PER_MTOK", "0"),
                attempt=args.attempt,
                correction=args.note,
            )
            # Reviewer selects a due_at strictly before expiry before submitting.
            report = Draft(context=context, text=copy, due_at=now).model_dump(mode="json")
        else:
            if args.stage == "publish" and args.scheduled:
                target = scheduled_slot(now, args.slot_date)
                if target.status(now) != "READY":
                    return finish(
                        {
                            "status": target.status(now),
                            "slot_date": target.day.isoformat(),
                            "allowed": False,
                            "automatic_retry": False,
                        }
                    )
            revision = args.revision
            if args.stage == "publish" and not revision:
                revision = phase_call("queue", store.next_due, page, now)
                if not revision:
                    return finish({"status": "SKIPPED_NO_APPROVED_CONTENT", "allowed": False})
            if args.stage == "publish" and args.live:
                if (
                    flag("DRY_RUN", "true")
                    or not flag("MARKET_TALK_LIVE")
                    or not flag("FACEBOOK_CONTROL_ENABLED")
                ):
                    raise ValueError("live gates disabled")
                return finish(publish_live(client, store, page, revision, now))
            if args.input:
                draft = Draft.model_validate_json(args.input.read_text())
            elif revision:
                row = store.item(revision)
                if row["page_id"] != page:
                    raise ValueError("Page mismatch")
                draft = Draft.model_validate(row["payload"])
            else:
                raise ValueError("input draft or exact revision required")
            phase = "source"
            ch, sh = phase_call("source", current, client, draft.context)
            report = inspect(draft, store, page, now=now, canon_hash=ch, snapshot_hash=sh)
            if args.stage == "submit":
                if report["errors"]:
                    raise ValueError(",".join(report["errors"]))
                store.put(page, draft)
                report.update(status="DRAFT", revision=draft.revision)
            elif args.stage == "approve":
                if not revision or args.confirm != "YES" or not args.actor:
                    raise ValueError("exact revision, YES and human reviewer required")
                report = approve(
                    revision,
                    store,
                    actor=args.actor,
                    note=args.note,
                    now=now,
                    canon_hash=ch,
                    snapshot_hash=sh,
                )
            elif args.stage == "publish":
                if not args.live:
                    report["status"] = "DRY_RUN"
            report.setdefault("revision", draft.revision)
        return finish(report)
    except Exception as exc:
        return finish(failure_report(exc, phase))


if __name__ == "__main__":
    raise SystemExit(main())
