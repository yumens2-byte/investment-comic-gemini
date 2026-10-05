"""Side-only disclaimer slide (P2). Replaces the main composer's S8.

Why: the main S8 draws a warning emoji that NotoSansCJK cannot render (pilot 1/2: a "☒" box
in the footer) and carries the main brand line. This slide uses only Hangul, ASCII and
common punctuation, all covered by NotoSansCJK (checked by ``unsupported_chars``).
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from sidestory.core.canon_rules import DISCLAIMER

SIZE = (1080, 1350)
BG = (8, 5, 15)             # same as the main slide background
PANEL = (17, 19, 34)
ACCENT = (0, 200, 200)      # cyan, side palette (no gold/red)
TEXT = (232, 236, 245)
MUTED = (150, 158, 180)
TITLE = "투자 유의 안내"
LINES = (DISCLAIMER + ".", "모든 투자 판단과 책임은 투자자 본인에게 있습니다.")
FOOTER = "EDT Universe 외전 · New Network 관측 기록"
ALL_TEXT = (TITLE, *LINES, FOOTER)
FONT_INDEX = 0              # .ttc → index 0 (project rule)


def unsupported_chars(text: str) -> list[str]:
    """Characters outside Hangul syllables, printable ASCII and a few punctuation marks."""
    allowed_punct = set("·—「」")
    bad = []
    for ch in text:
        if ch == " " or 0x21 <= ord(ch) <= 0x7E or 0xAC00 <= ord(ch) <= 0xD7A3 \
                or ch in allowed_punct:
            continue
        bad.append(ch)
    return bad


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, width: int) -> list[str]:
    lines, cur = [], ""
    for word in text.split(" "):
        trial = f"{cur} {word}".strip()
        if draw.textlength(trial, font=font) <= width or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    return [*lines, cur] if cur else lines


def render(out_path: Path, font_path: Path) -> Path:
    bad = [c for t in ALL_TEXT for c in unsupported_chars(t)]
    if bad:
        raise ValueError(f"disclaimer slide has glyphs outside the font-safe set: {bad}")
    img = Image.new("RGB", SIZE, BG)
    d = ImageDraw.Draw(img)
    title = ImageFont.truetype(str(font_path), 64, index=FONT_INDEX)
    body = ImageFont.truetype(str(font_path), 44, index=FONT_INDEX)
    small = ImageFont.truetype(str(font_path), 30, index=FONT_INDEX)
    left, right = 110, SIZE[0] - 110
    d.rounded_rectangle((70, 380, SIZE[0] - 70, 960), radius=28, fill=PANEL)
    d.rectangle((70, 380, 82, 960), fill=ACCENT)
    y = 450
    d.text((left, y), TITLE, font=title, fill=ACCENT)
    y += 120
    for para in LINES:
        for line in _wrap(d, para, body, right - left):
            d.text((left, y), line, font=body, fill=TEXT)
            y += 66
        y += 30
    w = d.textlength(FOOTER, font=small)
    d.text(((SIZE[0] - w) / 2, SIZE[1] - 110), FOOTER, font=small, fill=MUTED)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, "PNG")
    return out_path
