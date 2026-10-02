"""Aspect-preserving composition with measured, protected text regions."""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps
from pydantic import Field, model_validator

from engine.quality.contracts import QualityHold, StrictModel
from engine.quality.policy import qc_finding

SIZE = (1080, 1350)


class Rect(StrictModel):
    x: int = Field(ge=0)
    y: int = Field(ge=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)

    @model_validator(mode="after")
    def within_canvas(self):
        if self.x + self.width > SIZE[0] or self.y + self.height > SIZE[1]:
            raise ValueError("rectangle outside canvas")
        return self

    def intersects(self, other: Rect) -> bool:
        return (
            self.x < other.x + other.width
            and other.x < self.x + self.width
            and self.y < other.y + other.height
            and other.y < self.y + self.height
        )


def wrap_pixels(text: str, font: ImageFont.FreeTypeFont, width: int) -> list[str]:
    lines = []
    for paragraph in text.split("\n"):
        line = ""
        for char in paragraph:
            if font.getlength(char) > width:
                qc_finding("mobile_render", "glyph exceeds available width", error_type=QualityHold)
            if line and font.getlength(line + char) > width:
                lines.append(line)
                line = char
            else:
                line += char
        lines.append(line)
    return lines


def compose_quality_panel(
    *,
    image_path: Path | None,
    text: str,
    text_area: Rect,
    protected: list[Rect],
    font_path: Path,
    output: Path,
    font_size: int = 42,
    margin: int = 20,
) -> dict:
    if font_size < math.ceil(14 * SIZE[0] / 360):
        qc_finding("mobile_render", "body font below 14px equivalent at 360px display",
                   error_type=QualityHold)
    if margin < 0 or text_area.width <= 2 * margin or text_area.height <= 2 * margin:
        raise QualityHold("invalid text margins")
    if any(text_area.intersects(r) for r in protected):
        qc_finding("mobile_render", "text would cover a protected face, prop or contact",
                   error_type=QualityHold)
    font = ImageFont.truetype(str(font_path), font_size)
    lines = wrap_pixels(text, font, text_area.width - 2 * margin)
    ascent, descent = font.getmetrics()
    line_height = ascent + descent + 6
    if len(lines) * line_height > text_area.height - 2 * margin:
        qc_finding("mobile_render", "text overflow; edit copy or layout, do not shrink font",
                   error_type=QualityHold)
    canvas = Image.new("RGB", SIZE, (5, 10, 20))
    if image_path is not None:
        with Image.open(image_path) as original:
            # contain instead of stretching/cropping: all original pixels retained.
            contained = ImageOps.contain(original.convert("RGB"), SIZE, Image.Resampling.LANCZOS)
        canvas.paste(
            contained, ((SIZE[0] - contained.width) // 2, (SIZE[1] - contained.height) // 2)
        )
    draw = ImageDraw.Draw(canvas)
    draw.rectangle(
        (
            text_area.x,
            text_area.y,
            text_area.x + text_area.width - 1,
            text_area.y + text_area.height - 1,
        ),
        fill=(5, 10, 20),
    )
    for idx, line in enumerate(lines):
        draw.text(
            (text_area.x + margin, text_area.y + margin + idx * line_height),
            line,
            font=font,
            fill=(240, 245, 255),
            anchor="lt",
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output)
    previews = []
    for width in (360, 390):
        preview = output.with_name(f"{output.stem}-preview-{width}.png")
        canvas.resize((width, round(SIZE[1] * width / SIZE[0])), Image.Resampling.LANCZOS).save(
            preview
        )
        previews.append(str(preview))
    return {
        "output": str(output),
        "previews": previews,
        "line_count": len(lines),
        "font_size": font_size,
        "display_font_px": font_size * 360 / SIZE[0],
        "text_area": text_area.model_dump(),
        "geometry_check": "warning" if (font_size < math.ceil(14 * SIZE[0] / 360)
            or any(text_area.intersects(r) for r in protected)
            or any(font.getlength(c) > text_area.width - 2 * margin for c in text)
            or len(lines) * line_height > text_area.height - 2 * margin) else "pass",
        "human_readability": "unverified",
    }
