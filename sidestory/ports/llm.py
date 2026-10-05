"""Narrative generation port (implemented in P1)."""
from __future__ import annotations

from typing import Any, Protocol


class NarrativeLLM(Protocol):
    def generate_script(self, system_prompt: str, user_prompt: str) -> dict[str, Any]: ...
