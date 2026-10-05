"""Side-track persistence (icg_side schema)."""
from __future__ import annotations

from typing import Any, Protocol


class SideStore(Protocol):
    def anchored_main_ids(self) -> set[str]: ...

    def upsert_episode(self, side_episode_id: str, fields: dict[str, Any]) -> None: ...

    def get_episode(self, side_episode_id: str) -> dict[str, Any] | None: ...

    def log(self, stage: str, status: str, detail: dict[str, Any]) -> None: ...
