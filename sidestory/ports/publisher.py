"""Publishing port (Facebook Page, P2). Orchestration lives in app/publish.py."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel


class PublishReceipt(BaseModel):
    channel: str
    post_id: str | None
    photo_ids: list[str]
    dry_run: bool


class PublishError(RuntimeError):
    """A provider call failed.

    ambiguous=True: the request may have reached the provider and taken effect (timeout
    after sending, 5xx). Such a post is never retried blindly — it is reconciled first.
    """

    def __init__(self, message: str, *, ambiguous: bool = False):
        super().__init__(message)
        self.ambiguous = ambiguous


class Publisher(Protocol):
    channel: str

    def check(self) -> dict[str, Any]:
        """Read-only credential check: {'id', 'name'} of the Page. Raises PublishError."""
        ...

    def upload_photo(self, path: Path) -> str:
        """Upload one image as an UNPUBLISHED Page photo; returns its photo id."""
        ...

    def create_post(self, message: str, photo_ids: list[str]) -> str:
        """Publish one Page post with the photos attached in order; returns the post id."""
        ...

    def find_recent_post(self, message: str, limit: int = 10) -> str | None:
        """Post id of a recent Page post whose message equals `message`, else None."""
        ...

    def get_post(self, post_id: str) -> dict[str, Any]: ...
