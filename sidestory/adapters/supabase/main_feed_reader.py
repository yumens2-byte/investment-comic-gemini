"""MainFeedReader over icg_side.main_feed_*_v1 views (DR-4: no direct icg.* access)."""
from __future__ import annotations

from typing import Any

from sidestory.adapters.supabase.client import side_table
from sidestory.app.settings import SIDE_SCHEMA
from sidestory.core.models import ArcRow, MainEpisodeRow, MarketRow

EPISODE_VIEW = "main_feed_episode_v1"
MARKET_VIEW = "main_feed_market_v1"
ARC_VIEW = "main_feed_arc_v1"
FINGERPRINT_RPC = "main_state_fingerprint"


def _rows(resp: Any) -> list[dict]:
    data = getattr(resp, "data", None)
    if not isinstance(data, list):
        raise RuntimeError("invalid main feed response")
    return [row for row in data if isinstance(row, dict)]


class SupabaseMainFeedReader:
    def __init__(self, client: Any):
        self._client = client

    def published_episodes(self, start_date: str, end_date: str) -> list[MainEpisodeRow]:
        resp = (
            side_table(self._client, EPISODE_VIEW)
            .select("*")
            .gte("episode_date", start_date)
            .lte("episode_date", end_date)
            .order("episode_date", desc=True)
            .execute()
        )
        return [MainEpisodeRow.model_validate(row) for row in _rows(resp)]

    def market(self, snapshot_date: str) -> MarketRow | None:
        resp = (
            side_table(self._client, MARKET_VIEW)
            .select("*")
            .lte("snapshot_date", snapshot_date)
            .order("snapshot_date", desc=True)
            .limit(1)
            .execute()
        )
        rows = _rows(resp)
        return MarketRow.model_validate(rows[0]) if rows else None

    def dollar_history(self, start_date: str, end_date: str) -> list[tuple[str, float | None]]:
        resp = (
            side_table(self._client, MARKET_VIEW)
            .select("snapshot_date,dollar_index")
            .gte("snapshot_date", start_date)
            .lte("snapshot_date", end_date)
            .order("snapshot_date")
            .execute()
        )
        return [(str(r["snapshot_date"]), r.get("dollar_index")) for r in _rows(resp)]

    def arc(self) -> ArcRow | None:
        rows = _rows(side_table(self._client, ARC_VIEW).select("*").limit(1).execute())
        return ArcRow.model_validate(rows[0]) if rows else None

    def main_fingerprint(self, episode_date: str) -> str | None:
        resp = (
            self._client.schema(SIDE_SCHEMA)
            .rpc(FINGERPRINT_RPC, {"p_date": episode_date})
            .execute()
        )
        data = getattr(resp, "data", None)
        return data if isinstance(data, str) else None
