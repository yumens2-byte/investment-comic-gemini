"""python -m sidestory.market_talk --help. Defaults to read-only inspection."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from sidestory.market_talk.content import Context, Draft, canon, digest, utcnow
from sidestory.market_talk.service import approve, inspect, publish, verified_receipt
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
        .table("main_feed_market_v1")
        .select("*")
        .eq("snapshot_date", context.snapshot_date)
        .execute()
        .data
    )
    if not isinstance(rows, list) or len(rows) != 1:
        raise ValueError("exact source snapshot unavailable")
    return fields["canon_version"], digest(rows[0])


def readiness(store, page):
    """Configuration visibility only; never checks Meta or approves content."""
    policy = store.optional_policy(page)
    blockers = []
    if policy is None:
        blockers.append("PAGE_POLICY_REQUIRED")
    elif not policy["enabled"] or not policy["exclusive_managed"]:
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
            "prepare",
            "preview",
            "submit",
            "approve",
            "publish",
            "pause",
            "resume",
            "reconcile",
            "hold",
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
    args = p.parse_args(argv)
    try:
        if args.live and args.stage != "publish":
            raise ValueError("--live is only valid for publish")
        page = os.environ.get("FACE_PAGE_ID", "")
        if not page:
            raise ValueError("FACE_PAGE_ID required")
        client = connection()
        store = TalkStore(client)
        now = utcnow()
        if args.stage == "inspect" and not args.input and not args.revision:
            report = readiness(store, page)
        elif args.stage in {"pause", "resume", "reconcile", "hold"}:
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
                .table("main_feed_market_v1")
                .select("*")
                .eq("snapshot_date", data["snapshot_date"])
                .execute()
                .data
            )
            if not isinstance(rows, list) or len(rows) != 1:
                raise ValueError("exact source snapshot unavailable")
            context = Context.model_validate({**data, **fields, "snapshot_hash": digest(rows[0])})
            report = context.model_dump(mode="json")
        elif args.stage == "preview":
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
            revision = args.revision
            if args.stage == "publish" and not revision:
                revision = store.next_due(page, now)
                if not revision:
                    print(json.dumps({"status": "SKIPPED_NO_APPROVED_CONTENT"}))
                    return 0
            if args.input:
                draft = Draft.model_validate_json(args.input.read_text())
            elif revision:
                row = store.item(revision)
                if row["page_id"] != page:
                    raise ValueError("Page mismatch")
                draft = Draft.model_validate(row["payload"])
            else:
                raise ValueError("input draft or exact revision required")
            ch, sh = current(client, draft.context)
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
                else:
                    if (
                        flag("DRY_RUN", "true")
                        or not flag("MARKET_TALK_LIVE")
                        or not flag("FACEBOOK_CONTROL_ENABLED")
                    ):
                        raise ValueError("live gates disabled")
                    from sidestory.adapters.facebook.graph import FacebookPagePublisher
                    from sidestory.market_talk.publishing import ControlledPublisher

                    pub = ControlledPublisher(
                        FacebookPagePublisher(page, os.environ.get("FACE_PAGE_TOKEN", "")),
                        store,
                        page,
                        revision,
                        "talk",
                        draft.context.expires_at.isoformat(),
                    )
                    report = publish(revision, store, pub, now=now, canon_hash=ch, snapshot_hash=sh)
            report.setdefault("revision", draft.revision)
        emit_report(report, args.output)
        return 0 if not report.get("errors") else 1
    except Exception as exc:
        # No SDK exception text, request URLs, raw source material or tokens in reports.
        emit_report({"status": "BLOCKED", "error_type": type(exc).__name__}, args.output)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
