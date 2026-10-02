"""Deterministic image-brief check for panel actions before any paid image call.

Rules encode the 2026-10-03 incident: an action aimed at a named character
("slamming a chain ... toward Iron Securities Nuna") was refused by the provider
with PROHIBITED_CONTENT, while the same scene described as a clash against a
shield was accepted. Passing these rules does not guarantee provider approval;
it keeps combat briefs inside the COMBAT ACTION CONTRACT.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

COMPOSITOR_PANEL_TYPES = frozenset({"TEXT_CARD", "DISCLAIMER"})

_ATTACK_VERBS = (
    r"slam\w*|strik\w*|struck|smash\w*|punch\w*|kick\w*|stab\w*|slash\w*|hit|hits|hitting|"
    r"shoot\w*|shot|fir(?:e|es|ed|ing)|blast\w*|impal\w*|crush\w*|pummel\w*|hurl\w*|"
    r"lash\w*|whip\w*|swing\w*|swung"
)
_DIRECTED = r"(?:at|toward|towards|into|onto|against|on)"
_PRONOUN_TARGET = r"(?:her|him|them|the hero|the heroine|the villain)\b"
_FIREARM_DISCHARGE = re.compile(
    r"\b(?:fir(?:e|es|ed|ing)|shoot\w*|shot|burst|discharg\w*|muzzle flash\w*)\b"
    r"(?:\W+\w+){0,6}?\W+(?:rifle|gun|pistol|bullet\w*|rounds?|firearm)\b"
    r"|\b(?:rifle|gun|pistol|firearm)\b(?:\W+\w+){0,4}?\W+"
    r"(?:fir(?:e|es|ed|ing)|shoot\w*|blaz\w*|recoil\w*)\b",
    re.IGNORECASE,
)
_NEGATION = re.compile(r"\b(?:without|never|not|no|holstered|lowered|unfired)\b", re.IGNORECASE)
_GRAPHIC_INJURY = re.compile(
    r"\b(?:blood\w*|bleed\w*|gore|gory|impal\w*|corpse\w*|dead body|severed|dismember\w*)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ActionViolation:
    rule: str
    panel_idx: int
    detail: str


_CANON_PATH = Path(__file__).resolve().parents[2] / "config" / "characters.yaml"


@lru_cache(maxsize=1)
def _canon_names() -> tuple[str, ...]:
    # Anchored to the repository, not the working directory; a missing canon is an error
    # because silently dropping name targets would weaken the check.
    text = _CANON_PATH.read_text(encoding="utf-8")
    names = re.findall(r"^\s*name_en:\s*(.+?)\s*$", text, flags=re.MULTILINE)
    return tuple(sorted({n.strip().strip("'\"") for n in names if n.strip()}, key=len,
                        reverse=True))


def _directed_attack(names: tuple[str, ...]) -> re.Pattern[str]:
    # A possessive target ("the villain's shield") names an object, not a body.
    # "her" before a noun is a determiner ("into her shield"); only the object form counts.
    pronoun_object = (_PRONOUN_TARGET + r"(?!'s)(?=\s*(?:$|[,.;:!?)]|(?:and|as|while|but|"
                      r"who|with|from|back|again|hard|directly)\b))")
    targets = [pronoun_object] + [re.escape(name) + r"\b(?!'s)" for name in names]
    return re.compile(
        rf"\b(?:{_ATTACK_VERBS})\b(?:\W+\w+){{0,8}}?\W+{_DIRECTED}\W+"
        rf"(?:\w+\W+){{0,2}}?(?:{'|'.join(targets)})",
        re.IGNORECASE,
    )


def check_action(action: str, panel_idx: int = 0,
                 names: tuple[str, ...] | None = None) -> list[ActionViolation]:
    """Return rule violations for one panel action (English image brief)."""
    text = " ".join(str(action or "").split())
    if not text:
        return []
    found: list[ActionViolation] = []
    match = _directed_attack(_canon_names() if names is None else names).search(text)
    if match:
        found.append(ActionViolation("ACTION_ATTACK_ON_CHARACTER", panel_idx, match.group(0)))
    match = _FIREARM_DISCHARGE.search(text)
    if match and _NEGATION.search(text[max(0, match.start() - 40):match.end()]):
        match = None
    if match:
        found.append(ActionViolation("ACTION_FIREARM_DISCHARGE", panel_idx, match.group(0)))
    match = _GRAPHIC_INJURY.search(text)
    if match:
        found.append(ActionViolation("ACTION_GRAPHIC_INJURY", panel_idx, match.group(0)))
    return found


def check_script_actions(script: dict) -> list[ActionViolation]:
    """Check every generated (non-compositor) panel action in a script."""
    violations: list[ActionViolation] = []
    for i, panel in enumerate(script.get("panels") or []):
        if not isinstance(panel, dict) or panel.get("panel_type") in COMPOSITOR_PANEL_TYPES:
            continue
        violations.extend(check_action(panel.get("action", ""), panel.get("idx", i + 1)))
    return violations
