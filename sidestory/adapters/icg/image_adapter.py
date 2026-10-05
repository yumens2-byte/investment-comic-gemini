"""Gemini panel adapter over the main generate_panel + durable ledger (DR-3).

SUPABASE_SCHEMA=icg_side routes the ledger to icg_side.image_generation_calls with
side caps; scope must be output/sidestory/<date>/panels (enforced by the DB).
"""
from __future__ import annotations

from pathlib import Path

from engine.image.gemini_client import generate_panel
from engine.image.generation_guard import GenerationHold
from sidestory.ports.image import ImageHold


class GeminiPanelGenerator:
    def __init__(self, guard_factory=None):
        # Offline tests only: a callable(output_dir, panel_idx, prompt, refs) -> guard.
        self._guard_factory = guard_factory

    def generate(self, panel_idx: int, prompt: str, refs: list[Path],
                 output_dir: Path) -> tuple[Path, float]:
        guard = (self._guard_factory(output_dir, panel_idx, prompt, refs)
                 if self._guard_factory else None)
        try:
            path, cost = generate_panel(panel_idx, prompt, refs, output_dir,
                                        output_dir.parent / "gemini_run.log", None, guard=guard)
        except GenerationHold as exc:
            raise ImageHold(str(exc)) from exc
        if path is None:
            raise ImageHold(f"panel {panel_idx}: no valid image after bounded retries")
        return Path(path), float(cost)
