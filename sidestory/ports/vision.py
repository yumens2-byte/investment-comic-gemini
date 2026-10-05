"""Panel picture inspection port (SG-8, v8.9)."""
from __future__ import annotations

from pathlib import Path
from typing import Protocol

from sidestory.core.panel_check import VisionReport


class VisionError(RuntimeError):
    """Inspection call failed or returned an unusable answer. Never treated as a pass."""


class PanelInspector(Protocol):
    def inspect(self, image: Path) -> VisionReport: ...
