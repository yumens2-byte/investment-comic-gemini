"""Publishing port (Facebook Page in Phase-1; implemented in P2/P3)."""
from __future__ import annotations

from pathlib import Path
from typing import Protocol

from pydantic import BaseModel


class PublishReceipt(BaseModel):
    channel: str
    post_id: str | None
    photo_ids: list[str]
    dry_run: bool


class Publisher(Protocol):
    def publish(self, slides: list[Path], message: str, *, dry_run: bool) -> PublishReceipt: ...
