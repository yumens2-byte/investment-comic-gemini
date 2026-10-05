"""Claude vision adapter for SG-8 (DR-3: whitelisted engine helpers only)."""
from __future__ import annotations

import base64
import io
import json
import os
from pathlib import Path
from typing import Any

from PIL import Image
from pydantic import ValidationError

from engine.narrative.claude_client import _build_messages_create_kwargs, _extract_json
from sidestory.core.panel_check import VisionReport, vision_prompt
from sidestory.ports.vision import VisionError

DEFAULT_MODEL = "claude-sonnet-4-6"   # same model as the side narrative
MAX_SIDE = 1024                       # longest side sent to the model


def _png_b64(path: Path) -> str:
    try:
        with Image.open(path) as img:
            img = img.convert("RGB")
            img.thumbnail((MAX_SIDE, MAX_SIDE))
            buf = io.BytesIO()
            img.save(buf, "PNG")
    except OSError as exc:
        raise VisionError(f"unreadable image {path.name}: {exc}") from exc
    return base64.b64encode(buf.getvalue()).decode()


class ClaudePanelInspector:
    def __init__(self, client: Any = None, model: str | None = None):
        self._client = client
        self.model = model or os.environ.get("SIDESTORY_VISION_MODEL", DEFAULT_MODEL)
        self.usage: list[dict[str, int]] = []

    def _get_client(self) -> Any:
        if self._client is None:
            if not os.environ.get("ANTHROPIC_API_KEY"):
                raise VisionError("ANTHROPIC_API_KEY missing")
            import anthropic

            self._client = anthropic.Anthropic(max_retries=1)
        return self._client

    def inspect(self, image: Path) -> VisionReport:
        data = _png_b64(image)
        client = self._get_client()
        create = client.messages.create
        kwargs = _build_messages_create_kwargs(
            create, model=self.model, system_prompt=vision_prompt(),
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                             "data": data}},
                {"type": "text", "text": "Describe this panel as instructed. JSON only."}]}])
        # A description, not creative writing: keep it as deterministic as the SDK allows.
        if "temperature" in kwargs:
            kwargs["temperature"] = 0
        try:
            response = create(**kwargs)
        except Exception as exc:  # noqa: BLE001 — provider errors become a typed failure
            raise VisionError(f"{type(exc).__name__}: {exc}") from exc
        usage = getattr(response, "usage", None)
        if usage is not None:
            self.usage.append({"input": int(getattr(usage, "input_tokens", 0) or 0),
                               "output": int(getattr(usage, "output_tokens", 0) or 0)})
        text = "".join(getattr(b, "text", "") for b in getattr(response, "content", []) or [])
        try:
            return VisionReport.model_validate(json.loads(_extract_json(text)))
        except (json.JSONDecodeError, ValidationError, TypeError) as exc:
            raise VisionError(f"unusable inspection answer: {exc}") from exc
