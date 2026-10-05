"""Supabase client factory for the side track."""
from __future__ import annotations

from typing import Any

from sidestory.app.settings import SIDE_SCHEMA, Settings


def side_client(settings: Settings) -> Any:
    from supabase import create_client

    settings.require_db()
    return create_client(settings.supabase_url, settings.supabase_key)


def side_table(client: Any, name: str) -> Any:
    # Every side read/write goes through the icg_side schema — never icg.
    return client.schema(SIDE_SCHEMA).table(name)
