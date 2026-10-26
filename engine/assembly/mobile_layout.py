"""Measured mobile composition. Never crop, regenerate, truncate or approve art."""
from __future__ import annotations

import hashlib
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

from engine.assembly.pil_composer import (
    _FONT_PATHS,
    BG_DARK,
    OVERLAY_COLOR,
    TEXT_AMBER,
    TEXT_LIGHT_GRAY,
    TEXT_WHITE,
    require_korean_font,
)
from engine.image.generation_guard import GenerationHold
from engine.image.scene_performance import payload_hash

PROFILE = {"id": "mobile-reserved-band-1", "canvas": [1080, 1350],
           "caption_band": [0, 1050, 1080, 1350], "padding_review_ratio": 0.05,
           "font_sizes": {"key": [44, 40], "narration": [36, 32], "market": [28, 26]},
           "max_lines": {"key": 2, "narration": 3, "market": 1}}


def font_profile() -> dict:
    import os
    for name in [os.environ.get("ICG_CJK_FONT_PATH", ""), *_FONT_PATHS]:
        path = Path(name)
        if name and path.is_file():
            return {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "layout_sha256": payload_hash(PROFILE), "path": str(path)}
    raise GenerationHold("MOBILE_APPROVED_FONT_REQUIRED")


def wrap_pixels(draw, text: str, font, width: int) -> list[str]:
    """Wrap by measured glyph advance; preserve every character and explicit line."""
    lines = []
    for paragraph in text.split('\n'):
        current = ''
        for char in paragraph:
            candidate = current + char
            if draw.textlength(candidate, font=font) > width:
                if not current:
                    raise GenerationHold("MOBILE_GLYPH_TOO_WIDE")
                lines.append(current)
                current = char
            else:
                current = candidate
        lines.append(current)
    return lines


def compose_mobile(panel: dict, source: Path, output: Path) -> dict:
    """Writes only after the complete caption fits; returns measurements, never PASS."""
    texts = {"key": panel.get("key_text") or '', "narration": panel.get("narration") or '',
             "market": panel.get("market_ref") or ''}
    require_korean_font(list(texts.values()))
    font_meta = font_profile()
    with Image.open(source) as image:
        original_size = list(image.size)
        contained = ImageOps.contain(image.convert('RGB'), (1080, 1350), Image.Resampling.LANCZOS)
    slide = Image.new('RGB', (1080, 1350), BG_DARK)
    x, y = (1080-contained.width)//2, (1350-contained.height)//2
    slide.paste(contained, (x, y))
    draw = ImageDraw.Draw(slide)
    chosen = None
    # Fit from larger to documented minimum; never silently go below the minimum.
    for decrease in range(5):
        cursor, placements = 1066, []
        for key in ('key', 'narration', 'market'):
            if not texts[key]:
                continue
            upper, lower = PROFILE['font_sizes'][key]
            size = max(lower, upper - decrease)
            font = ImageFont.truetype(font_meta['path'], size)
            lines = wrap_pixels(draw, texts[key], font, 1024)
            if len(lines) > PROFILE['max_lines'][key]:
                break
            for line in lines:
                bbox = draw.textbbox((0, 0), line, font=font)
                height = max(size, bbox[3] - bbox[1])
                placements.append((key, line, font, [28, cursor, 28+bbox[2]-bbox[0], cursor+height]))
                cursor += height + 5
            cursor += 5
        else:
            if cursor <= 1334:
                chosen = placements
                break
    if chosen is None:
        raise GenerationHold('MOBILE_TEXT_EDIT_REQUIRED')
    draw.rectangle((0, 1050, 1080, 1350), fill=OVERLAY_COLOR)
    colors = {'key': TEXT_WHITE, 'narration': TEXT_LIGHT_GRAY, 'market': TEXT_AMBER}
    for key, line, font, bbox in chosen:
        # Anchor at the glyph ink top; actual glyph bounds are stored for audit.
        draw.text((bbox[0], bbox[1]), line, font=font, fill=colors[key], anchor='lt')
    output.parent.mkdir(parents=True, exist_ok=True)
    slide.save(output, 'PNG')
    for width in (360, 430):
        preview = slide.resize((width, round(1350*width/1080)), Image.Resampling.LANCZOS)
        preview.save(output.with_name(f'{output.stem}-{width}px.png'), 'PNG')
    padding_x = (1080-contained.width)/1080
    return {'panel_idx': panel['idx'], 'profile': PROFILE['id'],
            'source_size': original_size, 'rendered_bbox': [x, y, x+contained.width, y+contained.height],
            'horizontal_padding_ratio': padding_x, 'vertical_padding_ratio': (1350-contained.height)/1350,
            'geometry_status': 'REVIEW' if padding_x > PROFILE['padding_review_ratio'] else 'PASS',
            'actual_image_status': 'UNKNOWN', 'mobile_assembly_status': 'UNKNOWN',
            'font_sha256': font_meta['sha256'], 'layout_sha256': font_meta['layout_sha256'],
            'text_boxes': [{'role': k, 'bbox': b, 'font_size': f.size} for k, _, f, b in chosen],
            'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
            'slide_sha256': hashlib.sha256(output.read_bytes()).hexdigest()}
