"""SideStore over icg_side tables."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sidestory.adapters.supabase.client import side_table


class SupabaseSideStore:
    def __init__(self, client: Any):
        self._client = client

    def anchored_main_ids(self) -> set[str]:
        resp = side_table(self._client, "side_episodes").select("anchor_main_episode").execute()
        data = getattr(resp, "data", None) or []
        return {str(r["anchor_main_episode"]) for r in data if r.get("anchor_main_episode")}

    def upsert_episode(self, side_episode_id: str, fields: dict[str, Any]) -> None:
        side_table(self._client, "side_episodes").upsert(
            {"side_episode_id": side_episode_id, **fields}, on_conflict="side_episode_id"
        ).execute()

    def update_episode(self, side_episode_id: str, fields: dict[str, Any],
                       expect_status: str) -> bool:
        resp = (
            side_table(self._client, "side_episodes")
            .update({**fields, "updated_at": datetime.now(timezone.utc).isoformat()})
            .eq("side_episode_id", side_episode_id)
            .eq("status", expect_status)
            .execute()
        )
        return bool(getattr(resp, "data", None))

    def get_episode(self, side_episode_id: str) -> dict[str, Any] | None:
        resp = (
            side_table(self._client, "side_episodes")
            .select("*")
            .eq("side_episode_id", side_episode_id)
            .limit(1)
            .execute()
        )
        data = getattr(resp, "data", None) or []
        return data[0] if data else None

    def live_publication(self, side_episode_id: str, channel: str) -> dict[str, Any] | None:
        resp = (
            side_table(self._client, "side_publications")
            .select("*")
            .eq("side_episode_id", side_episode_id)
            .eq("channel", channel)
            .eq("dry_run", False)
            .limit(1)
            .execute()
        )
        data = getattr(resp, "data", None) or []
        return data[0] if data else None

    def insert_publication(self, row: dict[str, Any]) -> None:
        side_table(self._client, "side_publications").insert(row).execute()

    def log(self, stage: str, status: str, detail: dict[str, Any]) -> None:
        side_table(self._client, "side_run_logs").insert(
            {"stage": stage, "status": status, "detail": detail}
        ).execute()
