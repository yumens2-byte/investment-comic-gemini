"""All writes are confined to icg_side; atomic publication/cost RPCs live in Postgres."""

from __future__ import annotations

from datetime import timedelta, timezone

from sidestory.market_talk.content import Draft, digest, normalize


class TalkStore:
    def __init__(self, client):
        self.db = client.schema("icg_side")

    def rpc(self, name, **params):
        return self.db.rpc(name, params).execute().data

    def optional_policy(self, page_id):
        rows = (
            self.db.table("facebook_page_policy").select("*").eq("page_id", page_id).execute().data
        )
        if not isinstance(rows, list) or len(rows) > 1:
            raise ValueError("Page policy unavailable")
        return rows[0] if rows else None

    def policy(self, page_id):
        policy = self.optional_policy(page_id)
        if policy is None:
            raise ValueError("Page policy missing")
        return policy

    def recent(self, page_id):
        rows = (
            self.db.table("talk_items")
            .select("revision,semantic_key,body_hash,creative")
            .neq("status", "CONTENT_HOLD")
            .eq("page_id", page_id)
            .order("created_at", desc=True)
            .limit(30)
            .execute()
            .data
        )
        if not isinstance(rows, list):
            raise ValueError("history unavailable")
        return rows

    def put(self, page_id, draft: Draft):
        return (
            self.db.table("talk_items")
            .insert(
                {
                    "revision": draft.revision,
                    "page_id": page_id,
                    "semantic_key": draft.semantic_key,
                    "body_hash": digest(normalize(draft.body)),
                    "send_hash": digest(draft.body),
                    "body": draft.body,
                    "creative": draft.text.commentary + " " + draft.text.dialogue,
                    "payload": draft.model_dump(mode="json"),
                    "due_at": draft.due_at.isoformat(),
                    "expires_at": draft.context.expires_at.isoformat(),
                }
            )
            .execute()
            .data
        )

    def item(self, revision):
        rows = self.db.table("talk_items").select("*").eq("revision", revision).execute().data
        if not isinstance(rows, list) or len(rows) != 1:
            raise ValueError("exact item revision required")
        return rows[0]

    def approve(self, revision, actor, note):
        return self.rpc("talk_approve", p_revision=revision, p_actor=actor, p_note=note)

    def begin(self, page_id, key, track, body, expires_at):
        return self.rpc(
            "facebook_begin",
            p_page=page_id,
            p_key=key,
            p_track=track,
            p_body_hash=digest(body),
            p_expires=expires_at,
        )

    def finish(self, page_id, key, token, state, post_id=None, reason=""):
        return self.rpc(
            "facebook_finish",
            p_page=page_id,
            p_key=key,
            p_token=token,
            p_state=state,
            p_post_id=post_id,
            p_reason=reason,
        )

    def cost_reserve(self, page_id, key, amount):
        return self.rpc("talk_cost_reserve", p_page=page_id, p_key=key, p_amount=str(amount))

    def set_hold(self, page_id, actor, reason, enabled=False):
        return self.rpc(
            "facebook_set_hold", p_page=page_id, p_actor=actor, p_reason=reason, p_enabled=enabled
        )

    def observe(self, page_id, posts):
        return self.rpc("facebook_observe", p_page=page_id, p_posts=posts)

    def next_due(self, page_id, now):
        today = now.astimezone(timezone(timedelta(hours=9))).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        rows = (
            self.db.table("talk_items")
            .select("revision")
            .eq("page_id", page_id)
            .eq("status", "APPROVED")
            .gte("due_at", today.isoformat())
            .lte("due_at", now.isoformat())
            .gt("expires_at", now.isoformat())
            .order("due_at")
            .limit(1)
            .execute()
            .data
        )
        if not isinstance(rows, list):
            raise ValueError("queue unavailable")
        return rows[0]["revision"] if rows else None

    def delivery(self, page_id, key):
        rows = (
            self.db.table("facebook_deliveries")
            .select("*")
            .eq("page_id", page_id)
            .eq("business_key", key)
            .execute()
            .data
        )
        if not isinstance(rows, list) or len(rows) != 1:
            raise ValueError("exact delivery required")
        return rows[0]
