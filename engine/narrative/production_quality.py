"""Deterministic pre-persist quality gate for generated episode scripts."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ProductionViolation:
    code: str
    detail: str


class ProductionQualityError(ValueError):
    """Raised when an episode violates a non-negotiable publishing contract."""


_PERCENT_RE = re.compile(r"(?<![\w.])([+-]?\d+(?:\.\d+)?)\s*%")
_CAUSAL_ALGO_RE = re.compile(
    r"(?:알고리즘|algorithm)(?:이|가|은|는|의)?[^.!?\n]{0,30}"
    r"(?:방향을\s*바|압력|주도|움직|반등시|하락시|회복시|order flow)",
    re.IGNORECASE,
)
_STATIC_ACTIONS = ("stand", "look", "study", "read", "watch", "sit")
_THREAD_PLACEHOLDER_RE = re.compile(
    r"(?:Previous battle outcome remains unresolved emotionally|"
    r"Track continuing pressure from villain\s+CHAR_|\bPEACEFUL_GROWTH\b)",
    re.IGNORECASE,
)
_DANGLING_DECIMAL_RE = re.compile(r"(?:^|\s)[+-]?\d+\.$")


def _all_story_text(script: dict[str, Any]) -> list[tuple[str, str]]:
    values: list[tuple[str, str]] = []
    for panel in script.get("panels") or []:
        if not isinstance(panel, dict):
            continue
        idx = panel.get("idx", "?")
        for field in ("key_text", "narration", "market_ref"):
            value = panel.get(field)
            if isinstance(value, str):
                values.append((f"P{idx}.{field}", value))
    for field in ("caption_x_cover", "caption_x_final", "caption_telegram"):
        value = script.get(field)
        if isinstance(value, str):
            values.append((field, value))
    for idx, value in enumerate(script.get("caption_x_parts") or []):
        if isinstance(value, str):
            values.append((f"caption_x_parts[{idx}]", value))
    return values


def _has_algo_evidence(context_pack: dict[str, Any] | None) -> bool:
    evidence = " ".join(
        str(value)
        for item in (context_pack or {}).get("top_evidence") or []
        if isinstance(item, dict)
        for value in item.values()
    ).lower()
    return any(term in evidence for term in ("algorithmic trading", "algo trading", "알고리즘 거래", "알고 트레이딩"))


def validate_production_episode(
    script: dict[str, Any],
    *,
    delta: dict[str, dict[str, Any]] | None = None,
    context_pack: dict[str, Any] | None = None,
    story_beat_plan: dict[str, Any] | None = None,
    scenario_type: str = "ONE_VS_ONE",
    serial_required: bool = False,
    max_equity_daily_return_pct: float = 25.0,
    strict: bool = False,
) -> list[ProductionViolation]:
    """Validate facts, cast, serial state, scenario semantics, and action variety."""
    violations: list[ProductionViolation] = []
    story_text = _all_story_text(script)

    # A percentage this large in publishable copy is nearly always a unit
    # lineage failure for this daily-market product.  Treat it as a review
    # threshold, not a claim about what markets can theoretically do.
    for location, text in story_text:
        for match in _PERCENT_RE.finditer(text):
            value = float(match.group(1))
            nearby = text[max(0, match.start() - 40) : match.start()].upper()
            is_equity_return = "SPY" in nearby or "NASDAQ" in nearby
            # Preserve legitimate high relative moves such as VIX +32%.  The
            # tighter threshold applies only when the nearby label identifies
            # SPY/NASDAQ; triple-digit percentages remain a universal lineage
            # review because this product does not publish leveraged returns.
            if abs(value) > 100 or (is_equity_return and abs(value) > max_equity_daily_return_pct):
                violations.append(
                    ProductionViolation(
                        "NUMERIC_PERCENT_OUTLIER",
                        f"{location}: {match.group(0)} exceeds publish threshold",
                    )
                )

    for metric in ("SPY", "NASDAQ"):
        row = (delta or {}).get(metric) or {}
        if row.get("semantic_type") == "daily_return_pct" and row.get("pct") != row.get("curr"):
            violations.append(
                ProductionViolation(
                    "DOUBLE_PERCENT_CHANGE",
                    f"{metric}: daily_return_pct must expose pct == curr",
                )
            )

    if not _has_algo_evidence(context_pack):
        for location, text in story_text:
            if _CAUSAL_ALGO_RE.search(text):
                violations.append(
                    ProductionViolation(
                        "UNSUPPORTED_ALGORITHM_CAUSALITY",
                        f"{location}: algorithmic causality is not supported by evidence",
                    )
                )

    panels = [panel for panel in script.get("panels") or [] if isinstance(panel, dict)]
    rendered_chars = {
        str(char.get("char_id"))
        for panel in panels
        for char in panel.get("characters") or []
        if isinstance(char, dict) and char.get("char_id")
    }
    required_chars = {
        str(char_id)
        for beat in (story_beat_plan or {}).get("panel_beats") or []
        if isinstance(beat, dict)
        for char_id in beat.get("required_character") or []
        if char_id
    }
    missing_chars = sorted(required_chars - rendered_chars)
    if missing_chars:
        violations.append(
            ProductionViolation("REQUIRED_CAST_MISSING", ",".join(missing_chars))
        )

    if scenario_type == "NO_BATTLE":
        battle_panels = [str(panel.get("idx")) for panel in panels if panel.get("panel_type") == "BATTLE"]
        if battle_panels:
            violations.append(
                ProductionViolation(
                    "SCENARIO_PANEL_MISMATCH",
                    "NO_BATTLE uses BATTLE panels: " + ",".join(battle_panels),
                )
            )

    if serial_required:
        if not str(script.get("next_hook") or "").strip():
            violations.append(ProductionViolation("SERIAL_NEXT_HOOK_MISSING", "next_hook is empty"))
        if not (script.get("unresolved_threads") or script.get("resolved_threads")):
            violations.append(
                ProductionViolation("SERIAL_THREAD_LEDGER_EMPTY", "no unresolved/resolved thread")
            )
        for field in ("unresolved_threads", "resolved_threads"):
            for idx, thread in enumerate(script.get(field) or []):
                text = str(thread).strip()
                if _THREAD_PLACEHOLDER_RE.search(text):
                    violations.append(
                        ProductionViolation(
                            "SYNTHETIC_THREAD_PLACEHOLDER",
                            f"{field}[{idx}] is operational boilerplate, not a story state",
                        )
                    )
                if scenario_type == "NO_BATTLE" and re.search(
                    r"villain\s+CHAR_VILLAIN_", text, re.IGNORECASE
                ):
                    violations.append(
                        ProductionViolation(
                            "NO_BATTLE_VILLAIN_THREAD",
                            f"{field}[{idx}] introduces villain pressure in NO_BATTLE",
                        )
                    )

    for location, text in story_text:
        if _DANGLING_DECIMAL_RE.search(text.strip()):
            violations.append(
                ProductionViolation(
                    "TRUNCATED_NUMERIC_SENTENCE",
                    f"{location} ends at an incomplete decimal token",
                )
            )

    action_roots: list[set[str]] = []
    for panel in panels:
        if panel.get("panel_type") in {"TEXT_CARD", "DISCLAIMER"}:
            continue
        action = str(panel.get("action") or "").lower()
        action_roots.append({root for root in _STATIC_ACTIONS if re.search(rf"\b{root}\w*\b", action)})
    if len(action_roots) >= 4 and sum(bool(roots) for roots in action_roots) / len(action_roots) >= 0.8:
        violations.append(
            ProductionViolation(
                "STATIC_ACTION_STREAK",
                "at least 80% of narrative panels rely on static observe/stand actions",
            )
        )

    # Stable order and no duplicate messages make logs/test fixtures useful.
    violations = list(dict.fromkeys(violations))
    if violations and strict:
        raise ProductionQualityError(
            "; ".join(f"{item.code}: {item.detail}" for item in violations)
        )
    return violations
