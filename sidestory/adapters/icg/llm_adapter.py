"""Claude narrative adapter (DR-3: whitelisted engine helpers only)."""
from __future__ import annotations

import json
import os
from typing import Any

from engine.narrative.claude_client import _build_messages_create_kwargs, _extract_json
from sidestory.ports.llm import LLMError

DEFAULT_MODEL = "claude-sonnet-4-6"  # same as main narrative primary model


class ClaudeNarrativeLLM:
    def __init__(self, client: Any = None, model: str | None = None):
        self._client = client
        self.model = model or os.environ.get("SIDESTORY_LLM_MODEL", DEFAULT_MODEL)
        self.usage: list[dict[str, int]] = []

    def _get_client(self) -> Any:
        if self._client is None:
            if not os.environ.get("ANTHROPIC_API_KEY"):
                raise LLMError("ANTHROPIC_API_KEY missing")
            import anthropic

            self._client = anthropic.Anthropic(max_retries=1)
        return self._client

    def generate_script(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        client = self._get_client()
        create = client.messages.create
        kwargs = _build_messages_create_kwargs(
            create, model=self.model, system_prompt=system_prompt,
            messages=[{"role": "user", "content": user_prompt}])
        try:
            response = create(**kwargs)
        except Exception as exc:  # noqa: BLE001 — provider errors become a typed failure
            raise LLMError(f"{type(exc).__name__}: {exc}") from exc
        usage = getattr(response, "usage", None)
        if usage is not None:
            self.usage.append({"input": int(getattr(usage, "input_tokens", 0) or 0),
                               "output": int(getattr(usage, "output_tokens", 0) or 0)})
        text = "".join(getattr(b, "text", "") for b in getattr(response, "content", []) or [])
        try:
            data = json.loads(_extract_json(text))
        except json.JSONDecodeError as exc:
            raise LLMError(f"unparseable JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise LLMError("model output is not a JSON object")
        return data
