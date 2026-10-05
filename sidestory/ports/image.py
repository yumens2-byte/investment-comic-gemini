"""Image generation / slide composition ports (implemented in P1)."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol


class ImageGenerator(Protocol):
    def generate(self, panel_idx: int, prompt: str, refs: list[Path], output_dir: Path) -> Path: ...


class SlideComposer(Protocol):
    def compose(
        self, panels: list[dict[str, Any]], images: list[Path], output_dir: Path
    ) -> list[Path]: ...
