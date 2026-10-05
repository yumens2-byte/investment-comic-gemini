"""Read-only contract to the main track (backed by icg_side.main_feed_*_v1 views)."""
from __future__ import annotations

from typing import Protocol

from sidestory.core.models import ArcRow, MainEpisodeRow, MarketRow


class MainFeedReader(Protocol):
    def published_episodes(self, start_date: str, end_date: str) -> list[MainEpisodeRow]: ...

    def market(self, snapshot_date: str) -> MarketRow | None: ...

    def arc(self) -> ArcRow | None: ...

    def main_fingerprint(self, episode_date: str) -> str | None:
        """SHA of main protected rows (arc_state, episode_assets/published_comics/
        daily_analysis for the date). Computed in-DB by icg_side.main_state_fingerprint."""
        ...
