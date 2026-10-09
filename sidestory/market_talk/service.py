"""Exact-revision review stages; automatic mode uses a separate bounded review call."""

from __future__ import annotations

from datetime import datetime, timedelta

from sidestory.market_talk.content import Draft, digest, validate


def inspect(draft, store, page_id, *, now, canon_hash, snapshot_hash):
    recent = [r for r in store.recent(page_id) if r.get("revision") != draft.revision]
    errors = validate(
        draft, now=now, current_canon=canon_hash, current_snapshot=snapshot_hash, recent=recent
    )
    policy = store.policy(page_id)
    return {
        "mode": "dry_run",
        "allowed": False,
        "errors": errors,
        "page_enabled": policy["enabled"],
        "revision": draft.revision,
        "needs_human_review": True,
    }


def approve(revision, store, *, actor, note, now, canon_hash, snapshot_hash):
    row = store.item(revision)
    draft = Draft.model_validate(row["payload"])
    if draft.revision != revision or draft.body != row["body"]:
        raise ValueError("stored content hash mismatch")
    report = inspect(
        draft, store, row["page_id"], now=now, canon_hash=canon_hash, snapshot_hash=snapshot_hash
    )
    if report["errors"]:
        raise ValueError(",".join(report["errors"]))
    return store.approve(revision, actor, note)


def publish(revision, store, publisher, *, now, canon_hash, snapshot_hash):
    row = store.item(revision)
    draft = Draft.model_validate(row["payload"])
    if draft.revision != revision or draft.body != row["body"]:
        raise ValueError("stored content hash mismatch")
    report = inspect(
        draft, store, row["page_id"], now=now, canon_hash=canon_hash, snapshot_hash=snapshot_hash
    )
    if report["errors"]:
        raise ValueError(",".join(report["errors"]))
    if row["status"] not in {"APPROVED", "PUBLISHED"}:
        raise ValueError("exact revision must be approved")
    if now < draft.due_at:
        return {"status": "NOT_DUE"}
    publisher.check()
    post_id = publisher.create_post(draft.body, [])
    return verify_publication(revision, store, publisher, now=now, post_id=post_id)


def verify_publication(revision, store, publisher, *, now, post_id=None):
    row = store.item(revision)
    draft = Draft.model_validate(row["payload"])
    if draft.revision != revision or draft.body != row["body"]:
        raise ValueError("stored content hash mismatch")
    delivery = store.delivery(row["page_id"], revision)
    if delivery["state"] != "PUBLISHED" or row["status"] != "PUBLISHED":
        return {
            "status": "BLOCKED",
            "revision": revision,
            "blockers": ["PUBLISHED_RECEIPT_REQUIRED"],
        }
    if post_id is not None and post_id != delivery.get("post_id"):
        return {
            "status": "POSTED_UNVERIFIED",
            "revision": revision,
            "blockers": ["RECEIPT_ID_MISMATCH"],
            "automatic_retry": False,
        }
    post_id = delivery["post_id"]
    try:
        receipt = publisher.get_post(post_id)
    except Exception:
        return {
            "status": "POSTED_UNVERIFIED",
            "post_id": post_id,
            "revision": revision,
            "blockers": ["RECEIPT_READ_FAILED"],
            "automatic_retry": False,
        }
    try:
        at = verified_receipt(row["page_id"], post_id, receipt, delivery, now)
    except (ValueError, KeyError, TypeError, AttributeError):
        return {
            "status": "POSTED_UNVERIFIED",
            "post_id": post_id,
            "revision": revision,
            "blockers": ["RECEIPT_MISMATCH"],
            "automatic_retry": False,
        }
    return {
        "status": "PUBLISHED",
        "post_id": post_id,
        "revision": revision,
        "verified": True,
        "published_at": at,
    }


def verified_receipt(page_id, post_id, receipt, delivery, now):
    if (
        not post_id.startswith(page_id + "_")
        or receipt.get("id") != post_id
        or receipt.get("is_published") is not True
        or not isinstance(receipt.get("message"), str)
        or digest(receipt["message"]) != delivery["body_hash"]
    ):
        raise ValueError("receipt does not match the exact Page and submitted content")
    created = datetime.fromisoformat(receipt["created_time"].replace("Z", "+00:00"))
    started = datetime.fromisoformat(delivery["started_at"].replace("Z", "+00:00"))
    if (
        created.tzinfo is None
        or started.tzinfo is None
        or created < started - timedelta(minutes=5)
        or created > now + timedelta(minutes=5)
    ):
        raise ValueError("receipt outside publication window")
    return created.isoformat()
