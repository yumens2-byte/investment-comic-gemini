"""
engine/narrative/continuity.py

Previous-episode continuity helpers.

The pipeline already keeps numeric story state, but Claude needs a compact
narrative memory of the prior episode (last scene, hook, unresolved thread) to
avoid disconnected one-off episodes. This module is deterministic and uses only
existing JSON columns so it can ship before a dedicated continuity_json DB
migration.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def _episode_id(episode_date: str, episode_no: int | str | None) -> str:
    try:
        no = int(episode_no or 1)
    except (TypeError, ValueError):
        no = 1
    return f"ICG-{episode_date}-{no:03d}"


def _panel_text(panel: dict[str, Any]) -> str:
    return str(panel.get("narration") or panel.get("key_text") or "").strip()


def _final_story_panel(script_dict: dict[str, Any]) -> dict[str, Any]:
    panels = script_dict.get("panels") if isinstance(script_dict, dict) else []
    if not isinstance(panels, list) or not panels:
        return {}
    for panel in reversed(panels):
        if isinstance(panel, dict) and panel.get("panel_type") != "DISCLAIMER":
            return panel
    return panels[-1] if isinstance(panels[-1], dict) else {}


def _derive_threads(script_dict: dict[str, Any], ctx: dict[str, Any]) -> list[str]:
    threads: list[str] = []
    next_hook = str(script_dict.get("next_hook") or "").strip()
    if next_hook:
        threads.append(next_hook)
    outcome = (ctx.get("battle_result") or {}).get("outcome")
    villain = ctx.get("villain_id")
    if outcome:
        threads.append(f"Previous battle outcome remains unresolved emotionally: {outcome}.")
    if villain:
        threads.append(f"Track continuing pressure from villain {villain}.")
    # Preserve order while removing duplicates/empties.
    result: list[str] = []
    for item in threads:
        if item and item not in result:
            result.append(item)
    return result[:3]


def build_continuity_bundle(
    episode_id: str,
    episode_date: str,
    ctx: dict[str, Any],
    script_dict: dict[str, Any],
) -> dict[str, Any]:
    """Build a compact narrative memory bundle from the completed episode."""
    final_panel = _final_story_panel(script_dict)
    final_summary = _panel_text(final_panel)
    next_hook = str(script_dict.get("next_hook") or "").strip()
    if not next_hook:
        # EpisodeScript schema does not currently expose next_hook, so use the
        # final story panel as a safe continuity seed.
        next_hook = final_summary

    return {
        "version": "continuity-1",
        "source_episode_id": episode_id,
        "source_date": episode_date,
        "title": str(script_dict.get("title") or ""),
        "logline": str(script_dict.get("logline") or ""),
        "final_panel_summary": final_summary,
        "next_hook": next_hook,
        "outcome": (ctx.get("battle_result") or {}).get("outcome"),
        "event_type": ctx.get("event_type"),
        "scenario_type": ctx.get("scenario_type"),
        "hero_ids": ctx.get("heroes") or [ctx.get("hero_id")],
        "villain_id": ctx.get("villain_id"),
        "unresolved_threads": _derive_threads(script_dict, ctx),
        "must_continue_from": next_hook or final_summary,
    }


def bundle_from_episode_row(row: dict[str, Any]) -> dict[str, Any] | None:
    """Build a continuity bundle from an episode_assets row using existing columns."""
    script = row.get("script_json") or {}
    if not isinstance(script, dict) or not script:
        return None
    embedded = script.get("_continuity")
    if isinstance(embedded, dict) and embedded.get("source_episode_id"):
        return embedded
    episode_date = str(row.get("episode_date") or row.get("source_date") or "")
    if not episode_date:
        return None
    episode_no = row.get("episode_no") or 1
    ctx = {
        "battle_result": row.get("battle_json") or {},
        "event_type": row.get("event_type"),
        "scenario_type": row.get("scenario_type"),
        "heroes": row.get("heroes_json") or [],
        "villain_id": (row.get("battle_json") or {}).get("villain_id"),
    }
    return build_continuity_bundle(_episode_id(episode_date, episode_no), episode_date, ctx, script)


def load_previous_continuity(episode_date: str) -> dict[str, Any] | None:
    """Load the latest prior published/assembled episode as a continuity bundle."""
    try:
        from engine.common.supabase_client import icg_table

        for status in ("published", "assembled"):
            resp = (
                icg_table("episode_assets")
                .select(
                    "episode_date, episode_no, event_type, status, script_json, "
                    "battle_json, scenario_type, heroes_json"
                )
                .eq("status", status)
                .lt("episode_date", episode_date)
                .order("episode_date", desc=True)
                .order("episode_no", desc=True)
                .limit(5)
                .execute()
            )
            rows = getattr(resp, "data", None)
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, dict):
                    continue
                bundle = bundle_from_episode_row(row)
                if bundle:
                    logger.info(
                        "[continuity] previous episode loaded source=%s status=%s",
                        bundle.get("source_episode_id"),
                        status,
                    )
                    return bundle
    except Exception as exc:
        logger.warning("[continuity] previous continuity load failed: %s", exc)
    return None
