"""SG-8: picture check of a generated panel against its script (v8.9). Pure, no I/O.

The vision model only *describes* the picture (figures, text, watermark) in a fixed JSON
shape; the pass/fail decision is made here, deterministically, from the script.

Severity (master, 2026-10-05: "대세에 영향이 없으면 발행"):
  critical → retake once, then hold      | minor → pass, recorded as a warning
  - extra MAJOR figure (clearly visible character)      critical
  - extra MINOR figure (tiny / faint / far background)  minor
  - legible text, letters or numbers                    critical
  - tiny unreadable glyph-like marks                    minor
  - watermark or logo                                   critical
  - Zero Block missing on a posed panel                 critical
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field

from sidestory.core.script import SidePanel

SG8 = "SG-8"


class Figure(BaseModel):
    kind: Literal["zero_block", "other"]
    prominence: Literal["major", "minor"]


class VisionReport(BaseModel):
    figures: list[Figure] = Field(default_factory=list, max_length=50)
    text: Literal["none", "minor", "legible"]
    watermark: bool
    notes: str = Field(default="", max_length=300)


@dataclass(frozen=True)
class Expectation:
    zero_block: bool          # a Zero Block pose is requested
    background_allowed: int   # number of node silhouettes requested

    @classmethod
    def of(cls, panel: SidePanel) -> Expectation:
        return cls(zero_block=panel.zero_block_pose != "none",
                   background_allowed=len(panel.silhouettes))


@dataclass(frozen=True)
class Verdict:
    critical: tuple[str, ...]
    minor: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return not self.critical

    def as_dict(self) -> dict[str, list[str]]:
        return {"critical": list(self.critical), "minor": list(self.minor)}


# Fixed category keys → fixed correction sentences. The retake prompt depends only on the
# set of categories (never on counts), so a resumed retake keeps the same ledger fingerprint.
EXTRA_FIGURE = "extra_figure"
TEXT = "text"
WATERMARK = "watermark"
ZERO_BLOCK_MISSING = "zero_block_missing"
CORRECTIONS = {
    EXTRA_FIGURE: "Remove every person, hooded shape or humanoid figure that is not listed "
                  "in CHARACTER or BACKGROUND FIGURES; replace them with empty scenery.",
    TEXT: "Remove all letters, words and numbers; surfaces must be blank.",
    WATERMARK: "Remove any watermark, signature or logo.",
    ZERO_BLOCK_MISSING: "Zero Block must be clearly visible as described in CHARACTER.",
}
_ORDER = (EXTRA_FIGURE, TEXT, WATERMARK, ZERO_BLOCK_MISSING)


def judge(report: VisionReport, exp: Expectation) -> Verdict:
    critical: list[str] = []
    minor: list[str] = []
    zb = [f for f in report.figures if f.kind == "zero_block"]
    others = [f for f in report.figures if f.kind == "other"]
    # A second "Zero Block" is still an extra character.
    extra = others + zb[1 if exp.zero_block else 0:]
    extra_major = sum(f.prominence == "major" for f in extra)
    extra_minor = len(extra) - extra_major
    # Requested node silhouettes absorb extras, faint ones first.
    allowance = exp.background_allowed
    absorbed = min(allowance, extra_minor)
    extra_minor -= absorbed
    extra_major -= min(allowance - absorbed, extra_major)
    if extra_major:
        critical.append(f"{EXTRA_FIGURE}: {extra_major} clearly visible figure(s) not in script")
    if extra_minor:
        minor.append(f"{EXTRA_FIGURE}: {extra_minor} faint background figure(s) not in script")
    if report.text == "legible":
        critical.append(f"{TEXT}: legible text in the picture")
    elif report.text == "minor":
        minor.append(f"{TEXT}: tiny unreadable marks")
    if report.watermark:
        critical.append(f"{WATERMARK}: watermark or logo")
    if exp.zero_block and not zb:
        critical.append(f"{ZERO_BLOCK_MISSING}: Zero Block not visible")
    return Verdict(tuple(critical), tuple(minor))


def correction(verdict: Verdict) -> str:
    keys = {item.split(":", 1)[0] for item in verdict.critical}
    lines = [CORRECTIONS[k] for k in _ORDER if k in keys]
    return "CORRECTION (previous image rejected): " + " ".join(lines)


def vision_prompt() -> str:
    """Instruction for the describing model. It reports; it does not judge, and it is not
    told what the script asked for (so the description cannot be biased toward a pass)."""
    return (
        "You inspect one comic panel image. Describe it; do not judge it.\n"
        "Zero Block = a hooded figure whose face is hidden in shadow, dark hoodie, "
        "green eye slits, often holding a small cube.\n"
        "List EVERY humanoid figure: people, hooded shapes, statues shaped like people, "
        "silhouettes, shadows shaped like people, at any size.\n"
        "- kind: \"zero_block\" if it matches Zero Block, otherwise \"other\".\n"
        "- prominence: \"major\" if a viewer would notice it as a character at normal size "
        "(clear outline, visible eyes or details, or taller than about 1/10 of the image); "
        "\"minor\" if tiny, faint or lost in the far background.\n"
        "text: \"legible\" if any readable letters, words or numbers; \"minor\" if only tiny "
        "unreadable glyph-like marks; \"none\" otherwise. UI-like line patterns are not text.\n"
        "watermark: true if any watermark, signature, sparkle logo or brand mark.\n"
        "Answer with ONE JSON object only:\n"
        '{"figures": [{"kind": "zero_block|other", "prominence": "major|minor"}], '
        '"text": "none|minor|legible", "watermark": false, "notes": "<=200 chars"}'
    )
