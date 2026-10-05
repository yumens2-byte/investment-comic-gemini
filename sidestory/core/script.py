"""SideScript: the side-story script schema, normalisation and validation (P1 §2).

Flow: LLM output (panels 1–6 + copy) → ``normalize`` (ids, deterministic panels 7–8,
disclaimer) → ``validate`` (schema + beats + SG-3/4/5). Any problem list is fed back
to the model for regeneration; still failing → hold.
"""
from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError, field_validator

from sidestory.core import gates
from sidestory.core.beats import LLM_PANELS, TOTAL_PANELS, beats_for
from sidestory.core.canon_rules import DISCLAIMER, find_stage_violations
from sidestory.core.models import EchoPack

CAPTION_MAX = 1500

# Words in setting/action that make the image model draw glyphs (pilot 1: "title inscription"
# rendered the literal word TITLE). Text belongs to key_text/narration only.
TEXT_INDUCING = re.compile(
    r"\b(title|titles|text|texts|inscription|inscriptions|letter|letters|lettering|word|words|"
    r"caption|captions|typography|headline|headlines|banner|banners|label|labels|logo|logos|"
    r"signage|signboard|font|fonts|glyph|glyphs|numeral|numerals|digits|writing|written)\b",
    re.IGNORECASE)
# Extra people in setting/action (pilot 1: "a distant silhouette stands" became a second figure).
# Nodes are expressed only through the `silhouettes` field; Zero Block only via its pose.
FIGURE_WORDS = re.compile(
    r"\b(figure|figures|person|persons|people|man|men|woman|women|human|humans|humanoid|"
    r"silhouette|silhouettes|observer|observers|someone|somebody|stranger|strangers|crowd|"
    r"character|characters|soldier|soldiers|hero|heroes|villain|villains)\b",
    re.IGNORECASE)
# Negated mentions ("no figures present", "without any text") are instructions, not content.
NEGATED = re.compile(
    r"\b(no|without|never|not)\s+(any\s+|other\s+|visible\s+|human\s+|written\s+)?\w+",
    re.IGNORECASE)

DATA_CARD_IDX = 7
DISCLAIMER_IDX = 8

PanelType = Literal["COVER", "TENSION", "CLIMAX", "AFTERMATH", "TEXT_CARD", "DISCLAIMER"]


class SidePanel(BaseModel):
    idx: int = Field(ge=1, le=TOTAL_PANELS)
    panel_type: PanelType
    camera: str = Field(default="", max_length=60)
    setting: str = Field(default="", max_length=400)   # English, image prompt
    action: str = Field(default="", max_length=400)    # English, image prompt
    key_text: str = Field(default="", max_length=40)
    narration: str = Field(default="", max_length=120)
    market_ref: str | None = Field(default=None, max_length=80)
    zero_block_pose: Literal["front", "side", "back", "attack", "defense", "none"] = "none"
    silhouettes: list[Literal["node_a", "node_b", "node_c"]] = Field(default_factory=list)

    @field_validator("silhouettes")
    @classmethod
    def _unique(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("duplicate silhouettes")
        return value


class SideScript(BaseModel):
    side_episode_id: str
    anchor_main_episode: str
    format: Literal["nn_log"] = "nn_log"
    title: str = Field(min_length=1, max_length=40)
    logline: str = Field(min_length=1, max_length=100)
    caption_fb: str = Field(min_length=1, max_length=CAPTION_MAX)
    panels: list[SidePanel] = Field(min_length=TOTAL_PANELS, max_length=TOTAL_PANELS)
    side_threads: list[str] = Field(default_factory=list, max_length=3)
    next_hook_side: str = Field(default="", max_length=120)


_MARKET_LABELS = (
    ("us10y", "미 10년물 {:.2f}%"),
    ("vix", "VIX {:.2f}"),
    ("oil_wti", "WTI {:.2f}달러"),
    ("spy_change", "S&P500 {:+.2f}%"),
    ("nasdaq_change", "나스닥 {:+.2f}%"),
    ("hy_spread", "하이일드 {:.2f}%p"),
    ("fear_greed", "공포탐욕 {:.0f}"),
)
# When the card exceeds 120 chars, drop items in this order (least central first).
_DROP_ORDER = ("hy_spread", "fear_greed", "nasdaq_change", "oil_wti", "spy_change",
               "dollar", "vix", "us10y")
CARD_MAX = 120


def data_card(echo: EchoPack) -> dict[str, Any]:
    """Panel 7: numbers copied from the EchoPack only (EC-2 by construction)."""
    items: dict[str, str] = {}
    for key, fmt in _MARKET_LABELS:
        value = echo.market.get(key)
        if isinstance(value, int | float):
            items[key] = fmt.format(value)
    if echo.dollar and isinstance(echo.dollar.get("value"), int | float):
        as_of = str(echo.dollar.get("as_of") or "")[5:]
        items["dollar"] = (f"{echo.dollar['label_ko']} {echo.dollar['value']:.2f}"
                           + (f"({as_of})" if as_of else ""))
    for key in _DROP_ORDER:
        if len(" · ".join(items.values())) <= CARD_MAX:
            break
        items.pop(key, None)
    return {
        "idx": DATA_CARD_IDX, "panel_type": "TEXT_CARD",
        "key_text": f"본편 {echo.main_date[5:]} 시장 기록",
        "narration": " · ".join(items.values()),
        "market_ref": echo.main_episode_id,
        "zero_block_pose": "none", "silhouettes": [],
    }


def disclaimer_panel() -> dict[str, Any]:
    return {"idx": DISCLAIMER_IDX, "panel_type": "DISCLAIMER", "key_text": "",
            "narration": DISCLAIMER, "zero_block_pose": "none", "silhouettes": []}


def _with_disclaimer(caption: str) -> str:
    caption = (caption or "").rstrip()
    if caption.endswith(DISCLAIMER):
        return caption
    return f"{caption}\n\n{DISCLAIMER}" if caption else DISCLAIMER


def normalize(raw: dict[str, Any], *, side_episode_id: str, echo: EchoPack) -> dict[str, Any]:
    """Fill ids and deterministic panels; keep only LLM story panels 1–6."""
    story = [p for p in (raw.get("panels") or [])
             if isinstance(p, dict) and isinstance(p.get("idx"), int)
             and 1 <= p["idx"] <= LLM_PANELS]
    story.sort(key=lambda p: p["idx"])
    threads = raw.get("side_threads") or []
    return {
        "side_episode_id": side_episode_id,
        "anchor_main_episode": echo.main_episode_id,
        "format": "nn_log",
        "title": str(raw.get("title") or "").strip(),
        "logline": str(raw.get("logline") or "").strip(),
        "caption_fb": _with_disclaimer(str(raw.get("caption_fb") or "")),
        "panels": [*story, data_card(echo), disclaimer_panel()],
        "side_threads": [str(t) for t in threads][:3] if isinstance(threads, list) else [],
        "next_hook_side": str(raw.get("next_hook_side") or "").strip(),
    }


def _main_char_ids(echo: EchoPack) -> list[str]:
    ids = [*echo.hero_ids, *([echo.villain_id] if echo.villain_id else [])]
    return [i for i in ids if i]


def validate(script: dict[str, Any], echo: EchoPack, stage: str) -> tuple[SideScript | None,
                                                                          list[str]]:
    """Return (parsed script, problems). Empty problems = pass."""
    idxs = [p.get("idx") for p in script.get("panels") or [] if isinstance(p, dict)]
    if idxs != list(range(1, TOTAL_PANELS + 1)):
        return None, [f"panels must be idx 1..{TOTAL_PANELS} (write story panels 1..{LLM_PANELS},"
                      f" got {[i for i in idxs if isinstance(i, int) and i <= LLM_PANELS]})"]
    try:
        parsed = SideScript.model_validate(script)
    except ValidationError as exc:
        return None, [f"schema: {'.'.join(str(p) for p in e['loc'])}: {e['msg']}"
                      for e in exc.errors()]

    problems: list[str] = []
    panels = parsed.panels
    beats = beats_for(echo.outcome_class)
    main_ids = _main_char_ids(echo)
    for beat in beats:
        p = panels[beat.idx - 1]
        if p.panel_type != beat.panel_type:
            problems.append(f"P{p.idx} panel_type must be {beat.panel_type}")
        if p.zero_block_pose not in beat.allowed_poses:
            problems.append(f"P{p.idx} pose {p.zero_block_pose} not in {beat.allowed_poses}")
        if len(p.silhouettes) > beat.max_silhouettes:
            problems.append(f"P{p.idx} silhouettes {len(p.silhouettes)} > {beat.max_silhouettes}")
        if not p.setting.strip() or not p.action.strip():
            problems.append(f"P{p.idx} setting/action required (English)")
        visual = f"{p.setting}\n{p.action}"
        # D-P1-1: main-story characters are cited in text only, never drawn.
        hits = [i for i in main_ids if i in visual] + (["CHAR_"] if "CHAR_" in visual else [])
        if hits:
            problems.append(f"P{p.idx} main characters must not be drawn: {sorted(set(hits))}")
        problems += [f"P{p.idx} {v}" for v in find_stage_violations(visual, stage)]
        positive = NEGATED.sub(" ", visual)
        text_hits = sorted({m.group(0).lower() for m in TEXT_INDUCING.finditer(positive)})
        if text_hits:
            problems.append(f"P{p.idx} setting/action must not ask for written text {text_hits} "
                            "(quote titles only in key_text/narration)")
        figure_hits = sorted({m.group(0).lower() for m in FIGURE_WORDS.finditer(positive)})
        if figure_hits:
            problems.append(f"P{p.idx} setting/action must not describe people {figure_hits} "
                            "(Zero Block via zero_block_pose, nodes via silhouettes only)")
        if beat.must_cite_main:
            cited = f"{p.key_text}\n{p.narration}"
            if echo.main_episode_id not in cited and (not echo.title or echo.title not in cited):
                problems.append(f"P{p.idx} must cite main episode title '{echo.title}'")

    payload = parsed.model_dump()
    for gate in (gates.sg3_stage(payload, stage), gates.sg4_echo_contract(payload, echo),
                 gates.sg5_copy(parsed.caption_fb, gates.copy_texts(payload))):
        if not gate.passed:
            problems.append(f"{gate.gate}: {gate.reason}")
    return parsed, problems

