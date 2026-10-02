"""Readiness of rarely used generation paths before an editorial policy re-enables them.

A path is ready when it was published recently, or when a manual canary run passed
recently. Lookups fail closed: an unverifiable path is treated as dormant, which only
switches the episode to a non-combat action and never adds paid calls.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone

logger = logging.getLogger(__name__)

COMBAT_PATH_KEY = "ONE_VS_ONE:COMBAT"
DORMANT_AFTER_DAYS = 30  # Provisional (design D2); no published use for this long = dormant.
CANARY_VALID_DAYS = 7  # Provisional (design D2); a passing canary re-verifies the path.


def combat_path_ready(episode_date: str, *, today: datetime | None = None) -> tuple[bool, str]:
    """Return (ready, evidence) for the combat image path relative to an episode date."""
    target = date.fromisoformat(episode_date)
    since = (target - timedelta(days=DORMANT_AFTER_DAYS)).isoformat()
    try:
        from engine.common.supabase_client import icg_table

        rows = (
            icg_table("episode_assets")
            .select("episode_date")
            .eq("status", "published")
            .eq("scenario_type", "ONE_VS_ONE")
            .gte("episode_date", since)
            .lt("episode_date", episode_date)
            .limit(1)
            .execute()
            .data
        )
    except Exception as exc:
        logger.warning("[PathReadiness] publication lookup failed: %s", exc)
        return False, "lookup_failed"
    if isinstance(rows, list) and rows:
        return True, f"published:{rows[0].get('episode_date')}"

    now = today or datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=CANARY_VALID_DAYS)).isoformat()
    try:
        canaries = (
            icg_table("path_canary_runs")
            .select("created_at")
            .eq("path_key", COMBAT_PATH_KEY)
            .eq("status", "pass")
            .gte("created_at", cutoff)
            .limit(1)
            .execute()
            .data
        )
    except Exception as exc:
        logger.warning("[PathReadiness] canary lookup failed: %s", exc)
        return False, "canary_lookup_failed"
    if isinstance(canaries, list) and canaries:
        return True, f"canary:{canaries[0].get('created_at')}"
    return False, "dormant"
