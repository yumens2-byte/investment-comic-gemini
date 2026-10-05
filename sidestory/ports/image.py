"""Image generation / slide composition ports (P1)."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol


class ImageHold(RuntimeError):
    """Paid generation needs reconciliation (ledger hold, refusal, cap). Never auto-retried."""


class ImageGenerator(Protocol):
    def generate(self, panel_idx: int, prompt: str, refs: list[Path],
                 output_dir: Path) -> tuple[Path, float]:
        """Return (png path, cost USD). Raise ImageHold on any non-success."""
        ...


class SlideComposer(Protocol):
    def compose(
        self, panels: list[dict[str, Any]], images: list[Path | None], output_dir: Path
    ) -> list[Path]: ...
