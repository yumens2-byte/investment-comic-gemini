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

import copy
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

_OPERATIONAL_THREAD_RE = re.compile(
    r"(?:Previous battle outcome remains unresolved emotionally|"
    r"Track continuing pressure from villain\s+CHAR_|\bPEACEFUL_GROWTH\b)",
    re.IGNORECASE,
)
_UNSUPPORTED_ALGO_HISTORY_RE = re.compile(
    r"(?:NASDAQ[·ㆍ・/\s]*SPY|SPY[·ㆍ・/\s]*NASDAQ)?\s*"
    r"(?:하락[:：]?\s*)?알고리즘\s*압력\s*구간",
    re.IGNORECASE,
)


def sanitize_continuity_bundle(bundle: dict[str, Any] | None) -> dict[str, Any] | None:
    """Remove legacy operational prose and unsupported causality from memory.

    Old persisted bundles are immutable production history.  Sanitize them at
    the read boundary so strict retry does not demand text that the production
    quality gate simultaneously forbids.
    """
    if not isinstance(bundle, dict):
        return bundle
    cleaned = copy.deepcopy(bundle)
    for field in ("unresolved_threads", "resolved_threads"):
        if field not in cleaned:
            continue
        cleaned[field] = [
            str(item).strip()
            for item in cleaned.get(field) or []
            if str(item).strip() and not _OPERATIONAL_THREAD_RE.search(str(item))
        ][:3]
    for field in ("next_hook", "must_continue_from", "final_panel_summary"):
        value = cleaned.get(field)
        if isinstance(value, str):
            cleaned[field] = _UNSUPPORTED_ALGO_HISTORY_RE.sub(
                "이전 회차에서 묘사한 시장 압력 구간", value
            )
    return cleaned


def sanitize_continuity_window(window: dict[str, Any] | None) -> dict[str, Any] | None:
    """Sanitize cached window aggregates restored from a pre-hardening run."""
    if not isinstance(window, dict):
        return window
    cleaned = copy.deepcopy(window)
    cleaned["primary_previous"] = sanitize_continuity_bundle(
        cleaned.get("primary_previous")
    )
    cleaned["recent_threads"] = [
        str(item).strip()
        for item in cleaned.get("recent_threads") or []
        if str(item).strip() and not _OPERATIONAL_THREAD_RE.search(str(item))
    ][:5]
    cleaned["thread_ledger"] = [
        item
        for item in cleaned.get("thread_ledger") or []
        if isinstance(item, dict)
        and not _OPERATIONAL_THREAD_RE.search(
            str(item.get("summary") or item.get("text") or "")
        )
    ]
    return cleaned


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
    for thread in script_dict.get("unresolved_threads") or []:
        text = str(thread).strip()
        if text:
            threads.append(text)
    # Never manufacture reader-facing threads from operational outcome/villain
    # fields. These English placeholders leaked into generated scripts and even
    # introduced villain pressure in NO_BATTLE episodes.
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

    unresolved_threads = _derive_threads(script_dict, ctx)
    if not unresolved_threads and next_hook:
        unresolved_threads = [next_hook]
    from engine.narrative.serial_contracts import normalize_thread

    structured_threads = [
        normalize_thread(item, source_episode_id=episode_id) for item in unresolved_threads
    ]
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
        "unresolved_threads": unresolved_threads,
        "structured_threads": structured_threads,
        "resolved_threads": [
            str(item).strip()
            for item in script_dict.get("resolved_threads") or []
            if str(item).strip()
        ][:3],
        "relationship_delta": script_dict.get("relationship_delta") or {},
        "arc_id": (ctx.get("arc_context") or {}).get("arc_id"),
        "arc_day": (ctx.get("arc_context") or {}).get("arc_day"),
        "active_villain": (ctx.get("arc_context") or {}).get("active_villain")
        or ctx.get("villain_id"),
        "arc_tension": (ctx.get("arc_context") or {}).get("arc_tension"),
        "must_continue_from": next_hook or final_summary,
    }


def bundle_from_episode_row(row: dict[str, Any]) -> dict[str, Any] | None:
    """Build a continuity bundle from an episode_assets row using existing columns."""
    script = row.get("script_json") or {}
    if not isinstance(script, dict) or not script:
        return None
    embedded = script.get("_continuity")
    if isinstance(embedded, dict) and embedded.get("source_episode_id"):
        return sanitize_continuity_bundle(embedded)
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
    return sanitize_continuity_bundle(
        build_continuity_bundle(_episode_id(episode_date, episode_no), episode_date, ctx, script)
    )


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


def detect_arc_pivot(
    previous_episode: dict[str, Any] | None, arc_context: dict[str, Any] | None
) -> dict[str, Any]:
    """Detect whether current arc context needs an explicit narrative pivot explanation."""
    previous = previous_episode or {}
    current = arc_context or {}
    previous_villain = previous.get("active_villain") or previous.get("villain_id")
    current_villain = current.get("active_villain") or current.get("villain_id")
    previous_tension = _as_float(previous.get("arc_tension"))
    current_tension = _as_float(current.get("arc_tension") or current.get("tension"))
    reasons: list[str] = []
    if previous_villain and current_villain and previous_villain != current_villain:
        reasons.append("active_villain_changed")
    if (
        previous_tension is not None
        and current_tension is not None
        and abs(current_tension - previous_tension) >= 20
    ):
        reasons.append("arc_tension_jump")
    return {
        "pivot_required": bool(reasons),
        "pivot_reasons": reasons,
        "previous_active_villain": previous_villain,
        "current_active_villain": current_villain,
        "previous_arc_tension": previous_tension,
        "current_arc_tension": current_tension,
        "instruction": (
            "P1-P2 must explain why the scene/villain/tension changed before escalating a new conflict."
            if reasons
            else "No explicit arc pivot explanation required."
        ),
    }


def _as_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _merge_recent_window(bundles: list[dict[str, Any]]) -> dict[str, Any]:
    primary = bundles[0] if bundles else None
    recent_threads: list[str] = []
    recurring_villains: list[str] = []
    relationship_memory: dict[str, Any] = {}
    for bundle in bundles:
        for thread in bundle.get("unresolved_threads") or []:
            text = str(thread).strip()
            if text and text not in recent_threads:
                recent_threads.append(text)
        villain = bundle.get("active_villain") or bundle.get("villain_id")
        if villain and villain not in recurring_villains:
            recurring_villains.append(str(villain))
        rel = bundle.get("relationship_delta") or {}
        if isinstance(rel, dict):
            relationship_memory.update(rel)
    from engine.narrative.serial_contracts import merge_thread_ledger, summarize_cast_history

    return {
        "version": "continuity-window-1",
        "primary_previous": primary,
        "recent_threads": recent_threads[:5],
        "recurring_villains": recurring_villains[:5],
        "relationship_memory": relationship_memory,
        "cast_history": summarize_cast_history(bundles),
        "thread_ledger": merge_thread_ledger(bundles),
    }


def load_continuity_window(episode_date: str, limit: int = 3) -> dict[str, Any]:
    """Load a compact continuity window from recent prior published/assembled episodes."""
    bundles: list[dict[str, Any]] = []
    try:
        from engine.common.supabase_client import icg_table

        resp = (
            icg_table("episode_assets")
            .select(
                "episode_date, episode_no, event_type, status, script_json, "
                "battle_json, scenario_type, heroes_json"
            )
            .in_("status", ["published", "assembled"])
            .lt("episode_date", episode_date)
            .order("episode_date", desc=True)
            .order("episode_no", desc=True)
            .limit(limit * 2)
            .execute()
        )
        rows = getattr(resp, "data", None)
        if isinstance(rows, list):
            for row in rows:
                if not isinstance(row, dict):
                    continue
                bundle = bundle_from_episode_row(row)
                if bundle:
                    bundles.append(bundle)
                if len(bundles) >= limit:
                    break
    except Exception as exc:
        logger.warning("[continuity] continuity window load failed: %s", exc)
    return _merge_recent_window(bundles)
