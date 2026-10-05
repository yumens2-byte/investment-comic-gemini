"""Narrative generation ports (P1)."""
from __future__ import annotations

from typing import Any, Protocol


class LLMError(RuntimeError):
    """Model call failed or returned unparseable output."""


class NarrativeLLM(Protocol):
    def generate_script(self, system_prompt: str, user_prompt: str) -> dict[str, Any]: ...


class PromptSource(Protocol):
    def system_prompt(self) -> str: ...
