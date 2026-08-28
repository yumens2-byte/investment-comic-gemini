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
# Canon-locked fictional character names must never be treated as factual
# algorithmic-trading causality claims (2026-08-29 incident: character-name
# false positives can deadlock strict continuity vs. strict production gates).
_CANON_ALGO_NAME_RE = re.compile(r"알고리즘\s*리퍼|Algorithm\s*Reaper", re.IGNORECASE)
_ALGO_TOKEN_RE = re.compile(r"알고리즘|algorithmic|algorithms|algorithm", re.IGNORECASE)


def _mask_canon_names(text: str) -> str:
    """Replace canon algo-themed character names so causality checks skip them."""
    return _CANON_ALGO_NAME_RE.sub("리퍼", text)
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


def has_algo_evidence(context_pack: dict[str, Any] | None) -> bool:
    """Public wrapper: does today's evidence support algorithmic causality claims?"""
    return _has_algo_evidence(context_pack)


def neutralize_algo_causality(text: str) -> str:
    """Rewrite algorithm-actor wording to a neutral market actor.

    Used on continuity metadata (previous next_hook, beat-plan payoff text) so a
    legacy hook can never force today's copy into an UNSUPPORTED_ALGORITHM_CAUSALITY
    violation. Canon character names (알고리즘 리퍼 / Algorithm Reaper) are preserved
    verbatim because they are fiction, not market claims.
    """
    if not text:
        return text
    stash: list[str] = []

    def _protect(match: re.Match[str]) -> str:
        stash.append(match.group(0))
        return f"\x00{len(stash) - 1}\x00"

    masked = _CANON_ALGO_NAME_RE.sub(_protect, text)
    masked = _ALGO_TOKEN_RE.sub(
        lambda m: "시장" if m.group(0) == "알고리즘" else "market", masked
    )
    for index, original in enumerate(stash):
        masked = masked.replace(f"\x00{index}\x00", original)
    return masked


def sanitize_continuity_context(
    context_pack: dict[str, Any] | None,
    story_beat_plan: dict[str, Any] | None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, list[str]]:
    """Remove gate-conflicting content from continuity inputs before generation.

    Gate precedence is factual accuracy (production) over continuity. Two classes
    of inherited contamination are handled BEFORE the prompt, the continuity
    scorer, and the retry feedback see the context, so the two strict gates can
    never issue contradictory instructions:

    1. Operational placeholder threads (_THREAD_PLACEHOLDER_RE) are ALWAYS
       dropped — legacy bundles persisted them, the scorer then demands their
       keywords while SERIAL_NARRATIVE_P0 bans echoing them (2026-08-29 #2
       oscillating deadlock: attempts alternate between continuity-fail and
       SYNTHETIC_THREAD_PLACEHOLDER/NO_BATTLE_VILLAIN_THREAD fails).
    2. Algorithm-causality wording is neutralized only when today's evidence
       does not support it (2026-08-29 #1 deadlock).

    Returns (sanitized_pack, sanitized_plan, change_labels). Inputs are not
    mutated; deep copies are returned only when a change was actually required.
    """
    import copy

    changes: list[str] = []
    algo_supported = _has_algo_evidence(context_pack)

    def _neutralize(text: str) -> str:
        return text if algo_supported else neutralize_algo_causality(text)

    def _fix(container: dict[str, Any], key: str, label: str) -> None:
        value = container.get(key)
        if isinstance(value, str):
            replaced = _neutralize(value)
            if replaced != value:
                container[key] = replaced
                changes.append(label)
        elif isinstance(value, list):
            replaced_list: list[Any] = []
            changed = False
            for item in value:
                if isinstance(item, str):
                    if _THREAD_PLACEHOLDER_RE.search(item):
                        changed = True
                        continue
                    replaced_item = _neutralize(item)
                    changed = changed or replaced_item != item
                    replaced_list.append(replaced_item)
                else:
                    replaced_list.append(item)
            if changed:
                container[key] = replaced_list
                changes.append(label)

    def _drop_placeholder_dicts(
        container: dict[str, Any], key: str, label: str, text_field: str = "promise"
    ) -> None:
        value = container.get(key)
        if not isinstance(value, list):
            return
        kept: list[Any] = []
        changed = False
        for item in value:
            if isinstance(item, dict) and _THREAD_PLACEHOLDER_RE.search(
                str(item.get(text_field) or "")
            ):
                changed = True
                continue
            if isinstance(item, dict) and isinstance(item.get(text_field), str):
                replaced = _neutralize(item[text_field])
                if replaced != item[text_field]:
                    item[text_field] = replaced
                    changed = True
            kept.append(item)
        if changed:
            container[key] = kept
            changes.append(label)

    pack = copy.deepcopy(context_pack) if isinstance(context_pack, dict) else context_pack
    plan = copy.deepcopy(story_beat_plan) if isinstance(story_beat_plan, dict) else story_beat_plan

    def _fix_previous(previous: dict[str, Any], prefix: str) -> None:
        for key in ("next_hook", "must_continue_from", "final_panel_summary"):
            _fix(previous, key, f"{prefix}.{key}")
        for key in ("unresolved_threads", "resolved_threads"):
            _fix(previous, key, f"{prefix}.{key}")
        _drop_placeholder_dicts(previous, "structured_threads", f"{prefix}.structured_threads")

    if isinstance(pack, dict):
        previous = pack.get("previous_episode")
        if isinstance(previous, dict):
            _fix_previous(previous, "previous_episode")
        window = pack.get("continuity_window")
        if isinstance(window, dict):
            _drop_placeholder_dicts(window, "thread_ledger", "continuity_window.thread_ledger")
            _fix(window, "recent_threads", "continuity_window.recent_threads")
            primary_previous = window.get("primary_previous")
            if isinstance(primary_previous, dict):
                _fix_previous(primary_previous, "continuity_window.primary_previous")

    if isinstance(plan, dict):
        for index, beat in enumerate(plan.get("panel_beats") or []):
            if isinstance(beat, dict):
                _fix(beat, "dialogue_intent", f"panel_beats[{index}].dialogue_intent")
                _fix(beat, "continuity_payoff", f"panel_beats[{index}].continuity_payoff")
        serial_contract = plan.get("serial_contract")
        if isinstance(serial_contract, dict):
            _drop_placeholder_dicts(
                serial_contract, "due_threads", "serial_contract.due_threads"
            )
            _fix(serial_contract, "previous_consequence", "serial_contract.previous_consequence")

    if not changes:
        return context_pack, story_beat_plan, []
    return pack, plan, changes


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
            if _CAUSAL_ALGO_RE.search(_mask_canon_names(text)):
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


def build_serial_contract_instruction() -> str:
    """Standing serial-output contract injected into EVERY generation attempt.

    The runtime (Notion-hosted) system prompt predates SERIAL_NARRATIVE_P0, so its
    output contract omits next_hook/threads and the schema keeps them optional.
    Retry feedback alone cannot fix this: it is rebuilt from the LAST attempt's
    violations only, so once production passes the serial instructions vanish and
    the model regresses (2026-08-29 #3: serial violations on attempts 1 and 3
    with a schema-shape failure in between). This block therefore rides along on
    every attempt whenever serial output is required.
    """
    return (
        "## SERIAL NARRATIVE CONTRACT (required on every response)\n"
        "- Top-level next_hook: a non-empty Korean sentence under 100 characters. "
        "A concrete in-world story hook; never an investment prediction.\n"
        "- Top-level unresolved_threads and resolved_threads: JSON arrays of PLAIN "
        "STRINGS (max 3 each). NEVER objects, ids, or status fields — a bare Korean "
        "sentence per entry.\n"
        "- At least one concrete entry across unresolved_threads/resolved_threads: "
        "an in-world character decision, emotion, or unanswered clue.\n"
        "- Never use operational wording (Track continuing, CHAR_*, PEACEFUL_GROWTH) "
        "inside next_hook or thread entries."
    )


def build_production_retry_feedback(
    violations: list[ProductionViolation],
    *,
    serial_required: bool = False,
) -> str | None:
    """Turn gate failures into concrete, non-conflicting regeneration rules."""
    if not violations:
        return None

    codes = {item.code for item in violations}
    lines = [
        "## PRODUCTION QUALITY RETRY — every listed violation is a mandatory fix",
        *[f"- {item.code}: {item.detail}" for item in violations],
    ]
    if "UNSUPPORTED_ALGORITHM_CAUSALITY" in codes:
        lines.append(
            "- ALGORITHM FIX: remove every claim that an algorithm changed, drove, "
            "pressured, reversed, recovered, raised, or lowered the market. Describe "
            "only the supplied price/rate observation; do not merely paraphrase the claim."
        )
        lines.append(
            "- ALGORITHM WORDING BAN: unless an evidence card explicitly mentions algorithmic "
            "trading, do not place 'algorithm', '알고리즘', or '알고' in key_text, narration, "
            "market_ref, or captions at all. This includes fictional metaphors in those fields."
        )
    if "STATIC_ACTION_STREAK" in codes:
        lines.append(
            "- ACTION FIX: in at least half of non-card panels, replace stand/look/study/"
            "read/watch/sit actions with distinct physical state-changing verbs such as "
            "crosses, marks, closes, hands over, blocks, opens, or turns away."
        )
    if "SYNTHETIC_THREAD_PLACEHOLDER" in codes:
        lines.append(
            "- THREAD FIX: remove operational/template wording (Track continuing, CHAR_*, "
            "PEACEFUL_GROWTH). Write a concrete in-world character decision or unanswered clue."
        )
    if serial_required:
        lines.append(
            "- SERIAL FIX: return a non-empty next_hook (Korean, under 100 chars) and at "
            "least one concrete unresolved_threads or resolved_threads entry. Both thread "
            "fields must be arrays of PLAIN STRINGS — never objects with thread_id/status."
        )
    lines.extend(
        [
            "- Follow required_character and scenario panel-type constraints exactly.",
            "- Use only evidence-supported numbers, units, and causal statements.",
            "- Return the complete EpisodeScript JSON only.",
        ]
    )
    return "\n".join(lines)
