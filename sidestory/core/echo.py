"""Build the main→side EchoPack (L-A) from main feed rows.

The extraction mirrors main continuity rules without importing them
(engine/narrative/continuity.py: embedded ``_continuity`` first, otherwise the
final story panel text is the next-hook seed).
"""
from __future__ import annotations

from typing import Any

from sidestory.core.models import ArcRow, EchoPack, MainEpisodeRow, MarketRow, OutcomeClass
from sidestory.core.outcome import classify

MAX_THREADS = 3
_MARKET_KEYS = (
    "us10y",
    "vix",
    "oil_wti",
    "spy_change",
    "nasdaq_change",
    "dollar_index",
    "hy_spread",
    "fear_greed",
)


_NON_STORY_PANELS = frozenset({"DISCLAIMER", "TEXT_CARD"})


def _panel_text(panel: dict[str, Any]) -> str:
    # Same precedence as main continuity._panel_text: narration, then key_text.
    return str(panel.get("narration") or panel.get("key_text") or "").strip()


def _final_story_panel(script: dict[str, Any]) -> dict[str, Any]:
    # Same exclusion as main continuity._final_story_panel (DISCLAIMER / TEXT_CARD).
    panels = [p for p in script.get("panels") or [] if isinstance(p, dict)]
    story = [p for p in panels if str(p.get("panel_type") or "").upper() not in _NON_STORY_PANELS]
    return story[-1] if story else {}


def _clean_threads(items: Any) -> list[str]:
    threads: list[str] = []
    for item in items or []:
        if isinstance(item, dict):
            item = item.get("promise") or item.get("text") or ""
        text = str(item).strip()
        if text and text not in threads:
            threads.append(text)
    return threads[:MAX_THREADS]


def build_echo_pack(
    side_date: str,
    episode: MainEpisodeRow,
    market: MarketRow | None,
    arc: ArcRow | None,
) -> EchoPack:
    script = episode.script_json or {}
    battle = episode.battle_json or {}
    continuity = script.get("_continuity") if isinstance(script.get("_continuity"), dict) else {}

    next_hook = str(continuity.get("next_hook") or script.get("next_hook") or "").strip()
    if not next_hook:
        next_hook = _panel_text(_final_story_panel(script))

    threads = _clean_threads(
        continuity.get("unresolved_threads") or script.get("unresolved_threads")
    )
    outcome = battle.get("outcome")
    hero_ids = [str(h) for h in (episode.heroes_json or []) if h]

    market_values: dict[str, float | None] = {}
    if market is not None:
        dumped = market.model_dump()
        # Main stores some fields with float32 noise (e.g. 15.3100004196167).
        # 2 decimals = same precision the SG-4 EC-2 number check compares at.
        market_values = {
            key: (round(float(dumped[key]), 2) if dumped.get(key) is not None else None)
            for key in _MARKET_KEYS
        }

    outcome_class = classify(outcome, episode.scenario_type)
    # NO_BATTLE rows keep a legacy villain_id in battle_json for persistence
    # compatibility only (scripts/run_market.py: primary_villain is None) — not story fact.
    villain_id = None if outcome_class is OutcomeClass.NO_BATTLE else battle.get("villain_id")

    return EchoPack(
        side_date=side_date,
        main_episode_id=episode.main_episode_id,
        main_date=episode.episode_date,
        title=str(script.get("title") or "").strip(),
        logline=str(script.get("logline") or "").strip(),
        event_type=episode.event_type,
        scenario_type=episode.scenario_type,
        outcome=outcome,
        outcome_class=outcome_class,
        villain_id=villain_id,
        hero_ids=hero_ids,
        next_hook=next_hook,
        main_threads=threads,
        market=market_values,
        arc=(arc.model_dump() if arc is not None else {}),
    )
