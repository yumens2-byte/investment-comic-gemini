"""
engine/analysis/story_context_builder.py

Narrative Context Pack builder pilot.

Goal:
- Convert existing market delta + optional context sources into a compact, factual
  packet for Claude.
- Keep this module deterministic and side-effect free so it can be enabled safely
  behind NARRATIVE_CONTEXT_ENABLED during beta rollout.
"""

from __future__ import annotations

from typing import Any

_MAX_EVIDENCE = 3

_METRIC_STORY_MAP: dict[str, tuple[str, str, str]] = {
    "VIX": ("volatility", "Volatility Hydra pressure", "red volatility siren"),
    "WTI": ("oil", "Oil Shock Titan pressure", "oil port under black waves"),
    "DGS10": ("rates", "Debt Titan pressure", "bond auction hall"),
    "SPY": ("equity", "Algorithm Reaper pressure", "falling market billboard"),
    "NASDAQ": ("tech", "Algorithm Reaper pressure", "AI data-center tower"),
    "BTC": ("crypto", "Liquidity Leviathan ripple", "digital coin vault"),
    "USDKRW": ("fx", "currency gate tension", "currency exchange gate"),
    "HY_SPREAD": ("credit", "Liquidity Leviathan pressure", "cracked credit bridge"),
    "FEAR_GREED": ("sentiment", "crowd emotion shift", "crowd sentiment dial"),
    "CRYPTO_BASIS": ("crypto", "crypto leverage stress", "futures terminal glow"),
}


def _as_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _fmt_metric_value(metric: str, row: dict[str, Any]) -> str:
    curr = _as_float(row.get("curr"))
    pct = _as_float(row.get("pct"))
    parts: list[str] = []
    if curr is not None:
        parts.append(f"{metric} {curr:g}")
    if pct is not None:
        sign = "+" if pct > 0 else ""
        parts.append(f"({sign}{pct:g}%)")
    return " ".join(parts) if parts else metric


def _score_metric(row: dict[str, Any]) -> float:
    pct = _as_float(row.get("pct"))
    curr = _as_float(row.get("curr"))
    if pct is not None:
        return abs(pct)
    if curr is not None:
        return abs(curr) / 1000
    return 0.0


def _top_delta_evidence(delta: dict[str, dict[str, Any]], limit: int = _MAX_EVIDENCE) -> list[dict[str, str]]:
    ranked = sorted(
        ((metric, row) for metric, row in delta.items() if isinstance(row, dict)),
        key=lambda item: _score_metric(item[1]),
        reverse=True,
    )

    evidence: list[dict[str, str]] = []
    for metric, row in ranked[:limit]:
        topic, story_role, symbol = _METRIC_STORY_MAP.get(
            metric, (metric.lower(), f"{metric} market signal", "market dashboard")
        )
        evidence.append(
            {
                "id": f"metric:{metric}",
                "kind": "metric",
                "metric": metric,
                "topic": topic,
                "value": _fmt_metric_value(metric, row),
                "story_role": story_role,
                "scene_symbol": symbol,
            }
        )
    return evidence


def _select_news_evidence(news_items: list[dict[str, Any]] | None) -> list[dict[str, str]]:
    if not news_items:
        return []

    sorted_items = sorted(
        news_items,
        key=lambda item: _as_float(item.get("relevance_score")) or 0.0,
        reverse=True,
    )
    evidence: list[dict[str, str]] = []
    for idx, item in enumerate(sorted_items[:_MAX_EVIDENCE], 1):
        summary = str(item.get("safe_summary_ko") or item.get("headline") or "").strip()
        if not summary:
            continue
        evidence.append(
            {
                "id": str(item.get("id") or f"news:{idx}"),
                "kind": "news",
                "headline_summary": summary,
                "source": str(item.get("source") or "news"),
                "source_url": str(item.get("source_url") or ""),
                "story_role": str(item.get("story_use") or "market cause"),
            }
        )
    return evidence


def _select_event_hooks(economic_events: list[dict[str, Any]] | None) -> list[str]:
    if not economic_events:
        return []
    sorted_events = sorted(
        economic_events,
        key=lambda item: _as_float(item.get("importance")) or 0.0,
        reverse=True,
    )
    hooks: list[str] = []
    for event in sorted_events[:3]:
        name = str(event.get("name") or event.get("event") or "").strip()
        if not name:
            continue
        when = str(event.get("release_time") or event.get("date") or "").strip()
        hooks.append(f"{name} ({when})" if when else name)
    return hooks


def _select_sector_symbols(sector_heatmap: dict[str, Any] | None) -> list[str]:
    if not sector_heatmap:
        return []
    sectors = sector_heatmap.get("sectors") if isinstance(sector_heatmap, dict) else None
    if not isinstance(sectors, list):
        return []
    ranked = sorted(
        [s for s in sectors if isinstance(s, dict)],
        key=lambda item: abs(_as_float(item.get("change_pct")) or 0.0),
        reverse=True,
    )
    symbols: list[str] = []
    for item in ranked[:2]:
        name = str(item.get("name") or item.get("symbol") or "sector").strip()
        pct = _as_float(item.get("change_pct"))
        if pct is None:
            symbols.append(f"{name} sector board")
        else:
            color = "green" if pct >= 0 else "red"
            symbols.append(f"{name} {color} sector board ({pct:+g}%)")
    return symbols


def _market_cause(top_evidence: list[dict[str, str]]) -> str:
    if not top_evidence:
        return "No dominant market signal; keep the story calm and observation-focused."
    first = top_evidence[0]
    role = first.get("story_role", "market signal")
    value = first.get("value") or first.get("headline_summary") or first.get("metric") or "signal"
    return f"Primary story driver: {role} from {value}."


def build_narrative_context_pack(
    *,
    delta: dict[str, dict[str, Any]],
    battle_result: dict[str, Any],
    event_type: str,
    scenario_type: str,
    ending_tone: str,
    arc_context: dict[str, Any] | None = None,
    previous_episode: dict[str, Any] | None = None,
    news_items: list[dict[str, Any]] | None = None,
    economic_events: list[dict[str, Any]] | None = None,
    sector_heatmap: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a compact context packet for richer, better-grounded narrative generation."""
    metric_evidence = _top_delta_evidence(delta)
    news_evidence = _select_news_evidence(news_items)
    if news_evidence:
        # Keep at least one news card in the pilot pack so story cause is not
        # reduced to numbers only. Metrics still get priority for factual grounding.
        top_evidence = (metric_evidence[: _MAX_EVIDENCE - 1] + news_evidence[:1])
    else:
        top_evidence = metric_evidence[:_MAX_EVIDENCE]
    foreshadow = _select_event_hooks(economic_events)

    scene_symbols = []
    for item in metric_evidence:
        symbol = item.get("scene_symbol")
        if symbol and symbol not in scene_symbols:
            scene_symbols.append(symbol)
    for symbol in _select_sector_symbols(sector_heatmap):
        if symbol not in scene_symbols:
            scene_symbols.append(symbol)

    pack = {
        "version": "pilot-1",
        "event_type": event_type,
        "scenario_type": scenario_type,
        "ending_tone": ending_tone,
        "market_cause": _market_cause(top_evidence),
        "top_evidence": top_evidence,
        "foreshadow": foreshadow[:3],
        "scene_symbols": scene_symbols[:5],
        "battle_outcome": str(battle_result.get("outcome", "DRAW")),
        "balance": battle_result.get("balance", 0),
        "arc_tension": (arc_context or {}).get("tension"),
        "prohibited_claims": [
            "Do not invent news, numbers, sources, or future market direction.",
            "Do not provide investment advice or buy/sell instructions.",
            "Use only supplied metrics/news summaries in market_ref.",
        ],
    }
    if previous_episode:
        pack["previous_episode"] = previous_episode
        pack["continuity_directives"] = [
            "Panel 1-2 must acknowledge or pay off previous_episode.next_hook when present.",
            "Do not reset character relationship state without explanation.",
            "Continue unresolved_threads unless today's market evidence makes a clear pivot necessary.",
        ]
    return pack
