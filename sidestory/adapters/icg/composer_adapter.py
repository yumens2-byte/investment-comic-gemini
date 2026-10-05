"""Slide composition via the main PIL composer (DR-3), strict mode only."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from engine.assembly.pil_composer import compose_episode

# The main composer silently falls back to a Latin bitmap font when NotoSansCJK is missing,
# which renders Korean copy as empty boxes. The side track refuses instead.
KOREAN_FONT_CANDIDATES = (
    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"),
    Path("/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc"),
    Path("/System/Library/Fonts/AppleSDGothicNeo.ttc"),
)


class PilSlideComposer:
    def __init__(self, font_candidates: tuple[Path, ...] = KOREAN_FONT_CANDIDATES):
        self._fonts = font_candidates

    def compose(self, panels: list[dict[str, Any]], images: list[Path | None],
                output_dir: Path) -> list[Path]:
        if not any(p.is_file() for p in self._fonts):
            raise ValueError("Korean font (NotoSansCJK) missing — install fonts-noto-cjk")
        return compose_episode(panels, images, output_dir, strict=True)
