"""Side-track persistence (icg_side schema)."""
from __future__ import annotations

from typing import Any, Protocol


class SideStore(Protocol):
    def anchored_main_ids(self) -> set[str]: ...

    def upsert_episode(self, side_episode_id: str, fields: dict[str, Any]) -> None: ...

    def update_episode(self, side_episode_id: str, fields: dict[str, Any],
                       expect_status: str) -> bool:
        """Compare-and-set on status. False = row missing or status changed concurrently."""
        ...

    def get_episode(self, side_episode_id: str) -> dict[str, Any] | None: ...

    def log(self, stage: str, status: str, detail: dict[str, Any]) -> None: ...

    def live_publication(self, side_episode_id: str, channel: str) -> dict[str, Any] | None:
        """The non-dry-run publication row, if any (unique per episode+channel)."""
        ...

    def insert_publication(self, row: dict[str, Any]) -> None: ...
