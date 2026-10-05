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


class SideSetupError(RuntimeError):
    """icg_side is not ready on the target project (runbook step missing)."""


# PostgREST / Postgres codes → runbook action (sidestory/README.md "P0 runbook").
_SETUP_HINTS = {
    "PGRST106": "icg_side schema is not exposed. Supabase Dashboard → Settings → API → "
                "Exposed schemas: add icg_side (runbook step 3).",
    "PGRST205": "icg_side objects are missing. Apply sidestory/migrations/"
                "0001_icg_side_schema.sql (runbook step 2), then reload the schema cache.",
    "42P01": "icg_side objects are missing. Apply sidestory/migrations/"
             "0001_icg_side_schema.sql (runbook step 2).",
    "PGRST202": "icg_side.main_state_fingerprint is missing. Apply the migration (step 2).",
    # An empty icg_side (owner-only ACL) also yields 42501 — same fix as a missing migration.
    "42501": "service_role cannot use icg_side: apply sidestory/migrations/"
             "0001_icg_side_schema.sql (runbook step 2; it also grants service_role).",
}

_PROBES = ("side_episodes", "main_feed_episode_v1", "main_feed_market_v1", "main_feed_arc_v1")


def _error_code(exc: Exception) -> str:
    code = getattr(exc, "code", None)
    if not code and exc.args and isinstance(exc.args[0], dict):
        code = exc.args[0].get("code")
    return str(code or "")


def preflight(client: Any) -> None:
    """Fail fast with an actionable message instead of a stack trace mid-stage."""
    try:
        for name in _PROBES:
            side_table(client, name).select("*").limit(0).execute()
        client.schema(SIDE_SCHEMA).rpc(
            "main_state_fingerprint", {"p_date": "1970-01-01"}).execute()
    except Exception as exc:  # postgrest.APIError or transport errors
        hint = _SETUP_HINTS.get(_error_code(exc))
        if hint is None:
            raise
        raise SideSetupError(f"[{_error_code(exc)}] {hint}") from exc
