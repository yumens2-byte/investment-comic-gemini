"""
engine/image/openai_client.py
OpenAI GPT Image 최종 폴백 클라이언트 (Run Market 전용).

Gemini 한도/잔액 소진(QUOTA_EXHAUSTED) 이후에만 gemini_client.generate_panel이 호출한다.
- 키: OPENAI_API_KEY 단독 (OPENAI_ORG_ID/OPENAI_PROJECT_ID는 SDK 선택값).
- SDK 재시도 0회. 결과가 모호하면 호출부가 HOLD 처리한다.
- 화풍: Gemini와 동일한 프롬프트/REF + Gemini 성공 패널을 스타일 앵커로 마지막 입력.
설계: docs/IMAGE_OPENAI_FALLBACK_DETAILED_DESIGN_2026-10-27.md
"""

from __future__ import annotations

import base64
import io
import math
import os
from pathlib import Path

from engine.image.generation_guard import GenerationHold

_MODEL_DEFAULT = "gpt-image-2"
_QUALITY_DEFAULT = "medium"
# gpt-image-1은 2026-10-23 종료(openai SDK 3.40.0). 임의 해상도(4:5)를 지원하는 계열만 허용.
_ALLOWED_MODELS = frozenset({
    "gpt-image-2", "gpt-image-2-2026-04-21",
    "gpt-image-2.5-sunburst", "gpt-image-2.5-sunburst-2026-09-08",
    "gpt-image-2.5-flare", "gpt-image-2.5-flare-2026-09-08",
})
_ALLOWED_QUALITIES = frozenset({"low", "medium", "high"})
_SIZES = {None: "1024x1024", "4:5": "1024x1280"}
_MAX_INPUT_IMAGES = 16
_MAX_PROMPT_CHARS = 32000

# USD per 1M tokens. 이미지 입력 $8 / 출력 $30은 외부 집계 기준(공식 미확인).
# 텍스트 입력 단가는 미확인이므로 이미지 입력 단가로 보수적(상한) 계산한다.
# 공식 단가 확인 후 ICG_OPENAI_COST_*_PER_1M 환경변수로 덮어쓴다.
_COST_DEFAULTS = {"TEXT_IN": 8.0, "IMAGE_IN": 8.0, "OUTPUT": 30.0}

STYLE_ANCHOR_ASSET = Path("assets/style/gemini_style_anchor.png")

_STYLE_ANCHOR_RULE = (
    "a STYLE REFERENCE ONLY: match its line weight, inking, "
    "cel shading, color palette, lighting and rendering finish exactly. "
    "Do not copy its characters, composition, pose or background."
)
STYLE_PREAMBLE_ANCHOR = (
    "INPUT IMAGES: images 1..{refs} are character references (appearance only). "
    "The final image is " + _STYLE_ANCHOR_RULE
)
STYLE_PREAMBLE_ANCHOR_ONLY = "INPUT IMAGE: the only input image is " + _STYLE_ANCHOR_RULE
STYLE_PREAMBLE_NO_ANCHOR = (
    "INPUT IMAGES: all input images are character references (appearance only). "
    "Follow the STYLE LOCK below exactly for line weight, inking, shading and palette."
)


class OpenAIQuotaExhausted(RuntimeError):
    """OpenAI 429 (rate limit or insufficient_quota): request rejected, no image."""


class OpenAITerminal(RuntimeError):
    """Rejected before generation (auth, permission, invalid request)."""


class OpenAIRefusal(RuntimeError):
    """Moderation refusal; billing is unconfirmed, so callers settle it as unknown."""


class OpenAINoImage(RuntimeError):
    """Completed response without image data; usage cost may be known."""

    def __init__(self, cost: float | None):
        super().__init__("OpenAI completed without image")
        self.cost = cost


def _flag(name: str, default: str) -> bool:
    value = os.environ.get(name, default).lower()
    if value not in {"true", "false"}:
        raise GenerationHold(f"Invalid {name} feature flag")
    return value == "true"


def fallback_enabled() -> bool:
    return _flag("ICG_IMAGE_OPENAI_FALLBACK_ENABLED", "false")


def fallback_ready() -> bool:
    """Enabled and keyed. A missing key keeps the existing Gemini HOLD behavior."""
    return fallback_enabled() and bool(os.environ.get("OPENAI_API_KEY", "").strip())


def model_name() -> str:
    model = os.environ.get("ICG_OPENAI_IMAGE_MODEL", "") or _MODEL_DEFAULT
    if model not in _ALLOWED_MODELS:
        raise GenerationHold(f"Unsupported OpenAI image model: {model}")
    return model


def quality_name() -> str:
    quality = os.environ.get("ICG_OPENAI_IMAGE_QUALITY", "") or _QUALITY_DEFAULT
    if quality not in _ALLOWED_QUALITIES:
        raise GenerationHold(f"Unsupported OpenAI image quality: {quality}")
    return quality


def size_for(aspect_ratio: str | None) -> str:
    if aspect_ratio not in _SIZES:
        raise GenerationHold(f"OpenAI fallback does not support aspect ratio {aspect_ratio}")
    return _SIZES[aspect_ratio]


def _rate(key: str) -> float:
    raw = os.environ.get(f"ICG_OPENAI_COST_{key}_PER_1M", "")
    if not raw:
        return _COST_DEFAULTS[key]
    try:
        value = float(raw)
    except ValueError as exc:
        raise GenerationHold(f"Invalid ICG_OPENAI_COST_{key}_PER_1M") from exc
    if not math.isfinite(value) or value < 0:
        raise GenerationHold(f"Invalid ICG_OPENAI_COST_{key}_PER_1M")
    return value


def _value(obj: object, key: str) -> object:
    if obj is None:
        return None
    return obj.get(key) if isinstance(obj, dict) else getattr(obj, key, None)


def calc_cost(usage: object) -> float | None:
    """Usage-based USD cost; None when usage is missing (caller settles unknown)."""
    if usage is None:
        return None
    try:
        input_tokens = int(_value(usage, "input_tokens") or 0)
        output_tokens = int(_value(usage, "output_tokens") or 0)
        details = _value(usage, "input_tokens_details")
        image_in = int(_value(details, "image_tokens") or 0)
        text_in = int(_value(details, "text_tokens") or 0)
    except (TypeError, ValueError):
        return None
    if details is None:
        # Unknown split: bill every input token at the higher image rate.
        image_in, text_in = input_tokens, 0
    if not (input_tokens or output_tokens):
        return None
    return (text_in * _rate("TEXT_IN") + image_in * _rate("IMAGE_IN")
            + output_tokens * _rate("OUTPUT")) / 1_000_000


def build_prompt(prompt_text: str, ref_count: int, has_anchor: bool) -> str:
    if not has_anchor:
        preamble = STYLE_PREAMBLE_NO_ANCHOR
    elif ref_count:
        preamble = STYLE_PREAMBLE_ANCHOR.format(refs=ref_count)
    else:
        preamble = STYLE_PREAMBLE_ANCHOR_ONLY
    return preamble + "\n\n" + prompt_text


def check_inputs(prompt: str, ref_paths: list[Path], style_anchor: Path | None) -> None:
    """Provider limits are checked before any reservation can be spent."""
    count = len(ref_paths) + (1 if style_anchor else 0)
    if count > _MAX_INPUT_IMAGES:
        raise GenerationHold(f"OpenAI fallback input images {count} > {_MAX_INPUT_IMAGES}")
    if len(prompt) > _MAX_PROMPT_CHARS:
        raise GenerationHold(f"OpenAI fallback prompt exceeds {_MAX_PROMPT_CHARS} chars")
    for path in [*ref_paths, *([style_anchor] if style_anchor else [])]:
        if not Path(path).is_file():
            raise GenerationHold(f"Missing OpenAI fallback input image: {path}")


def _get_client():
    from openai import OpenAI  # 지연 import (테스트 mock 용이)

    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        raise GenerationHold("OPENAI_API_KEY 환경변수 누락; OpenAI fallback unavailable")
    return OpenAI(api_key=key, max_retries=0, timeout=180.0)


def _mime(path: Path) -> str:
    suffix = path.suffix.lower()
    return ("image/jpeg" if suffix in {".jpg", ".jpeg"}
            else "image/webp" if suffix == ".webp" else "image/png")


def generate_one(client, prompt: str, ref_paths: list[Path], style_anchor: Path | None,
                 aspect_ratio: str | None) -> tuple[bytes, float | None]:
    """Single images.edit call. Returns provider PNG bytes and usage cost."""
    import openai

    images = [(p.name, p.read_bytes(), _mime(p))
              for p in [*ref_paths, *([style_anchor] if style_anchor else [])]]
    kwargs = {"model": model_name(), "prompt": prompt, "quality": quality_name(),
              "size": size_for(aspect_ratio), "output_format": "png", "n": 1}
    try:
        if images:
            response = client.images.edit(image=images, **kwargs)
        else:
            response = client.images.generate(**kwargs)
    except openai.RateLimitError as exc:
        raise OpenAIQuotaExhausted(f"OpenAI 429 code={getattr(exc, 'code', None)}") from exc
    except openai.BadRequestError as exc:
        if getattr(exc, "code", None) == "moderation_blocked":
            raise OpenAIRefusal("OpenAI moderation_blocked") from exc
        raise OpenAITerminal(f"OpenAI 400 code={getattr(exc, 'code', None)}") from exc
    except (openai.AuthenticationError, openai.PermissionDeniedError,
            openai.NotFoundError) as exc:
        raise OpenAITerminal(f"OpenAI {type(exc).__name__}") from exc
    cost = calc_cost(_value(response, "usage"))
    data = _value(response, "data") or []
    encoded = _value(data[0], "b64_json") if data else None
    if not encoded:
        raise OpenAINoImage(cost)
    try:
        return base64.b64decode(encoded, validate=True), cost
    except (ValueError, TypeError) as exc:
        raise OpenAINoImage(cost) from exc


def normalize_to_anchor(data: bytes, style_anchor: Path | None) -> bytes:
    """Match the Gemini anchor's pixel size when aspect ratios agree within 1%."""
    if style_anchor is None:
        return data
    from PIL import Image

    with Image.open(style_anchor) as anchor:
        target = anchor.size
    with Image.open(io.BytesIO(data)) as image:
        image.load()
        if image.size == target:
            return data
        if abs(image.width / image.height - target[0] / target[1]) > 0.01 * (target[0] / target[1]):
            return data
        out = io.BytesIO()
        image.resize(target, Image.Resampling.LANCZOS).save(out, "PNG")
        return out.getvalue()
