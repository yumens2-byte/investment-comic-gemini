"""Deterministic P0 contracts for serialized casting, threads, and villains."""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from typing import Any

HERO_IDS = [f"CHAR_HERO_{idx:03d}" for idx in range(1, 6)]


def summarize_cast_history(bundles: list[dict[str, Any]], limit: int = 10) -> dict[str, Any]:
    """Return ordered lead history and exposure statistics from newest-first bundles."""
    leads: list[str] = []
    for bundle in bundles[:limit]:
        heroes = [str(item) for item in bundle.get("hero_ids") or [] if item]
        if heroes:
            leads.append(heroes[0])
    counts = Counter(leads)
    consecutive = 0
    if leads:
        consecutive = next((idx for idx, item in enumerate(leads) if item != leads[0]), len(leads))
    return {
        "recent_lead_ids": leads,
        "lead_counts": dict(counts),
        "consecutive_lead_id": leads[0] if leads else None,
        "consecutive_lead": consecutive,
    }


def rotate_hero(
    market_scores: dict[str, int],
    cast_history: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any]]:
    """Select the best grounded hero while penalizing recent over-exposure."""
    history = cast_history or {}
    recent = [str(item) for item in history.get("recent_lead_ids") or []]
    counts = Counter(recent[:10])
    consecutive_id = history.get("consecutive_lead_id")
    consecutive = int(history.get("consecutive_lead") or 0)
    candidates: dict[str, dict[str, int]] = {}
    for hero_id in HERO_IDS:
        market_fit = int(market_scores.get(hero_id, 0))
        recent_penalty = min(35, counts[hero_id] * 12)
        consecutive_penalty = min(30, consecutive * 18) if hero_id == consecutive_id else 0
        try:
            last_seen = recent.index(hero_id)
            absence_bonus = min(15, last_seen * 3)
        except ValueError:
            absence_bonus = 15
        candidates[hero_id] = {
            "market_fit": market_fit,
            "absence_bonus": absence_bonus,
            "recent_lead_penalty": recent_penalty,
            "consecutive_penalty": consecutive_penalty,
            "total": market_fit + absence_bonus - recent_penalty - consecutive_penalty,
        }
    market_winner = max(HERO_IDS, key=lambda item: (market_scores.get(item, 0), -HERO_IDS.index(item)))
    rotated_winner = max(HERO_IDS, key=lambda item: (candidates[item]["total"], -HERO_IDS.index(item)))
    # A truly dominant market fit is not displaced merely for variety.
    other_market_fit = max(
        (market_scores.get(item, 0) for item in HERO_IDS if item != market_winner),
        default=0,
    )
    dominant_market_fit = market_scores.get(market_winner, 0) - other_market_fit >= 50
    if dominant_market_fit:
        selected = market_winner
        reason = "MARKET_FIT_OVERRIDE"
    else:
        selected = rotated_winner
        reason = "ROTATED_SCORE"
    return selected, {"selected": selected, "reason": reason, "candidates": candidates}


def validate_canon_mirrors(canon: dict[str, Any]) -> list[str]:
    """Return human-readable errors when hero/villain mirror links are not reciprocal."""
    heroes = canon.get("heroes") or {}
    villains = canon.get("villains") or {}
    errors: list[str] = []
    for hero_id, hero in heroes.items():
        mirror = ((hero or {}).get("belief") or {}).get("mirror_villain")
        if mirror and mirror not in villains:
            errors.append(f"{hero_id}.mirror_villain references unknown {mirror}")
        elif mirror:
            reverse = ((villains[mirror] or {}).get("belief") or {}).get("mirror_hero")
            if reverse != hero_id:
                errors.append(f"{hero_id}->{mirror} is not reciprocal (reverse={reverse})")
    for villain_id, villain in villains.items():
        mirror = ((villain or {}).get("belief") or {}).get("mirror_hero")
        if mirror and mirror not in heroes:
            errors.append(f"{villain_id}.mirror_hero references unknown {mirror}")
    return errors


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def thread_id(thread_type: str, promise: str, owners: list[str] | None = None) -> str:
    seed = "|".join([thread_type.upper(), _clean(promise).casefold(), *sorted(owners or [])])
    return "THREAD_" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12].upper()


def normalize_thread(
    value: str | dict[str, Any], *, due_in: int = 2, source_episode_id: str = ""
) -> dict[str, Any]:
    """Upgrade a legacy string or sanitize an existing structured thread."""
    if isinstance(value, dict):
        promise = _clean(value.get("promise"))
        thread_type = str(value.get("type") or "MYSTERY").upper()
        owners = [str(item) for item in value.get("owner_character_ids") or []]
        return {
            "thread_id": str(value.get("thread_id") or thread_id(thread_type, promise, owners)),
            "type": thread_type,
            "promise": promise,
            "owner_character_ids": owners,
            "status": str(value.get("status") or "OPEN").upper(),
            "payoff_due_in": int(value.get("payoff_due_in", due_in)),
            "setup_episode_id": str(value.get("setup_episode_id") or source_episode_id),
        }
    promise = _clean(value)
    return {
        "thread_id": thread_id("MYSTERY", promise),
        "type": "MYSTERY",
        "promise": promise,
        "owner_character_ids": [],
        "status": "OPEN",
        "payoff_due_in": due_in,
        "setup_episode_id": source_episode_id,
    }


def merge_thread_ledger(bundles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge newest-first continuity bundles without duplicating stable thread IDs."""
    ledger: dict[str, dict[str, Any]] = {}
    for age, bundle in enumerate(bundles):
        values = bundle.get("structured_threads") or bundle.get("unresolved_threads") or []
        for value in values:
            item = normalize_thread(value, due_in=max(0, 2 - age), source_episode_id=str(bundle.get("source_episode_id") or ""))
            existing = ledger.get(item["thread_id"])
            if existing is None or item["status"] in {"PAID", "EXTENDED"}:
                ledger[item["thread_id"]] = item
    return list(ledger.values())[:8]


def build_villain_reader_card(
    canon: dict[str, Any], villain_id: str | None, *, recently_seen: bool = False
) -> dict[str, Any] | None:
    """Compile reader-facing villain facts from canon without inventing claims."""
    if not villain_id:
        return None
    villain = (canon.get("villains") or {}).get(villain_id)
    if not isinstance(villain, dict):
        return None
    belief = villain.get("belief") or {}
    triggers = villain.get("trigger_metrics") or []
    natural = bool(belief.get("natural_disaster"))
    phenomenon = _clean(belief.get("phenomenon") or villain.get("event"))
    if natural:
        mechanism = phenomenon
        goal = _clean(belief.get("attenuation"))
    else:
        mechanism = _clean(belief.get("lie") or belief.get("contradiction") or villain.get("event"))
        goal = _clean(belief.get("want"))
    return {
        "char_id": villain_id,
        "display_name_ko": _clean(villain.get("name_ko")),
        "market_phenomenon": _clean(villain.get("event")),
        "trigger_metrics": triggers,
        "mechanism": mechanism,
        "immediate_goal_or_attenuation": goal,
        "signature_threat": _clean(villain.get("description")),
        "limitation_or_weakness": _clean(belief.get("truth") or belief.get("revelation")),
        "natural_disaster": natural,
        "intro_mode": "REFRESH" if recently_seen else "FULL",
        "required_reveal_steps": ["IDENTITY", "MECHANISM"] if recently_seen else ["SIGNATURE", "IDENTITY", "MECHANISM", "STAKES"],
    }
