"""
engine/image/gemini_client.py
Gemini 2.5 Flash Image API 클라이언트.

⚠️ CRITICAL:
  genai.Client(api_key=os.environ["GEMINI_API_SUB_PAY_KEY"]) — GEMINI_API_SUB_PAY_KEY 고정.
  GEMINI_API_KEY 이름 절대 사용 금지 (doc 19 patch).

RULE 07: 모든 패널에 캐릭터 REF 이미지 멀티 입력 주입.
재시도: 완료된 이미지 누락 응답만 최대 3회. 영속 가드 HOLD는 fallback 금지.
비용 계산: prompt_tokens * 0.30 + output_tokens * 30.0, 분모 1e6.
로그: output/episodes/{date}/panels/gemini_run.log (JSONL)
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import tempfile
import time
from pathlib import Path

from engine.image.generation_guard import GenerationHold, ProductionGenerationGuard

logger = logging.getLogger(__name__)

_MODEL = "gemini-2.5-flash-image"
_COST_INPUT_PER_1M = 0.30  # USD per 1M input tokens
_COST_OUTPUT_PER_1M = 30.0  # USD per 1M output tokens
_ESTIMATED_IMAGE_OUTPUT_TOKENS = 1290


def _get_client():
    """
    Gemini genai.Client 반환.
    ⚠️ GEMINI_API_SUB_PAY_KEY 환경변수 고정 — GEMINI_API_KEY 사용 금지.
    """
    from google import genai  # 지연 import (테스트 mock 용이)

    pay_key = os.environ.get("GEMINI_API_SUB_PAY_KEY", "")
    if not pay_key:
        raise RuntimeError(
            "GEMINI_API_SUB_PAY_KEY 환경변수 누락. GitHub Secrets에 GEMINI_API_SUB_PAY_KEY 등록 필요. "
            "(주의: GEMINI_API_KEY 이름 사용 불가 — doc 19 patch)"
        )
    from google.genai import types

    return genai.Client(
        api_key=pay_key,
        http_options=types.HttpOptions(
            timeout=120_000, retry_options=types.HttpRetryOptions(attempts=1)
        ),
    )


def _calc_cost(prompt_tokens: int, output_tokens: int) -> float:
    """Gemini 비용 계산 (USD)."""
    return (
        prompt_tokens * _COST_INPUT_PER_1M / 1_000_000
        + output_tokens * _COST_OUTPUT_PER_1M / 1_000_000
    )


def _metadata_value(metadata: object, key: str) -> int:
    """Read an integer usage field from SDK objects or dict-like metadata."""
    if metadata is None:
        return 0
    if isinstance(metadata, dict):
        value = metadata.get(key, 0)
    else:
        value = getattr(metadata, key, 0)
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _extract_usage_tokens(response: object) -> tuple[int, int]:
    """Extract Gemini usage metadata for cost/quality logs across SDK versions."""
    metadata = getattr(response, "usage_metadata", None)
    if metadata is None and isinstance(response, dict):
        metadata = response.get("usage_metadata") or response.get("usageMetadata")

    prompt_tokens = _metadata_value(metadata, "prompt_token_count")
    if prompt_tokens == 0:
        prompt_tokens = _metadata_value(metadata, "promptTokenCount")

    output_tokens = _metadata_value(metadata, "candidates_token_count")
    if output_tokens == 0:
        output_tokens = _metadata_value(metadata, "candidatesTokenCount")

    total_tokens = _metadata_value(metadata, "total_token_count")
    if total_tokens == 0:
        total_tokens = _metadata_value(metadata, "totalTokenCount")
    if output_tokens == 0 and total_tokens > prompt_tokens:
        output_tokens = total_tokens - prompt_tokens

    return prompt_tokens, output_tokens


def _estimate_prompt_tokens(prompt_text: str, ref_paths: list[Path]) -> int:
    """Fallback token estimate when Gemini image responses omit usage metadata."""
    text_tokens = max(1, len(prompt_text) // 4)
    # Reference images are billed as input too, but SDK metadata can be absent for image output.
    return text_tokens + len(ref_paths) * 258


def _obj_value(obj: object, key: str, default: object = None) -> object:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _response_parts(response: object) -> list[object]:
    """Return Gemini response parts without leaking SDK AttributeError shapes."""
    candidates = _obj_value(response, "candidates", [])
    if not candidates:
        return []
    first = candidates[0]
    content = _obj_value(first, "content")
    if content is None:
        return []
    parts = _obj_value(content, "parts", [])
    return list(parts or [])


def _response_finish_reason(response: object) -> str:
    candidates = _obj_value(response, "candidates", [])
    if not candidates:
        feedback = _obj_value(response, "prompt_feedback")
        reason = _obj_value(feedback, "block_reason")
        return str(reason) if reason else "no_candidates"
    return str(_obj_value(candidates[0], "finish_reason", "unknown"))


def _write_jsonl_log(log_path: Path, record: dict) -> None:
    """gemini_run.log에 JSONL 레코드 추가."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def _generate_one(
    client,
    prompt_text: str,
    ref_paths: list[Path],
    aspect_ratio: str | None = None,
) -> tuple[bytes, int, int]:
    """
    Gemini API 단일 패널 이미지 생성.

    Args:
        client: genai.Client 인스턴스.
        prompt_text: 패널 프롬프트.
        ref_paths: 캐릭터 REF 이미지 경로 목록.
        aspect_ratio: "9:16" 등. None(기본)이면 모델 기본값(정사각) — 이미지 트랙
            만화 패널의 기존 동작을 그대로 유지한다. 영상 트랙 북엔드만 지정한다.

    Returns:
        이미지 바이너리 (PNG), prompt token count, output token count.

    Raises:
        RuntimeError: 응답에 이미지 없을 때.
    """
    from google.genai import types

    # contents = [프롬프트 텍스트] + [REF 이미지들]
    contents: list = [prompt_text]
    for ref_path in ref_paths:
        if ref_path.exists():
            contents.append(
                types.Part.from_bytes(
                    data=ref_path.read_bytes(),
                    mime_type="image/png",
                )
            )
        else:
            raise GenerationHold(f"Missing mandatory REF: {ref_path}")

    config = None
    if aspect_ratio:
        # 정사각 이미지를 9:16 영상에 넣으면 상하 44% 가 검은 여백이 된다
        # (2026-09-07 W36 실측). 생성 단계에서 비율을 맞춘다.
        config = types.GenerateContentConfig(
            image_config=types.ImageConfig(aspect_ratio=aspect_ratio)
        )

    response = client.models.generate_content(
        model=_MODEL,
        contents=contents,
        config=config,
    )

    prompt_tokens, output_tokens = _extract_usage_tokens(response)

    # 응답에서 이미지 추출
    for part in _response_parts(response):
        inline_data = _obj_value(part, "inline_data")
        if inline_data:
            data = _obj_value(inline_data, "data")
            if data:
                return data, prompt_tokens, output_tokens

    raise NoImageResponse(_response_finish_reason(response), prompt_tokens, output_tokens)


class NoImageResponse(RuntimeError):
    """A completed provider response without an image, preserving billed usage."""

    def __init__(self, reason: str, prompt_tokens: int, output_tokens: int):
        super().__init__(f"Gemini completed without image (finish_reason={reason})")
        self.reason = reason
        self.prompt_tokens = prompt_tokens
        self.output_tokens = output_tokens


def _terminal_error(exc: Exception) -> bool:
    status = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    if str(status) in {"400", "401", "403", "404", "429"}:
        return True
    message = str(exc).lower()
    return any(word in message for word in (
        "quota", "resource_exhausted", "budget", "billing", "permission_denied",
        "unauthenticated", "invalid_argument", "safety", "prohibited", "policy",
        "blocklist", "recitation", "spii", "blocked",
    ))


def _validate_png(data: bytes) -> None:
    from PIL import Image

    with Image.open(io.BytesIO(data)) as image:
        if image.format != "PNG":
            raise ValueError("Provider image is not PNG")
        image.verify()
    with Image.open(io.BytesIO(data)) as image:
        image.load()
        if image.width <= 0 or image.height <= 0:
            raise ValueError("Provider image has invalid dimensions")


def _persist_exclusive(path: Path, data: bytes) -> None:
    """Commit a complete, fsynced file with atomic no-overwrite semantics."""
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def generate_panel(
    panel_idx: int,
    prompt_text: str,
    ref_paths: list[Path],
    output_dir: Path,
    log_path: Path,
    aspect_ratio: str | None = None,
    *,
    guard=None,
) -> tuple[Path | None, float]:
    """Generate with durable pre-call reservations; ambiguous outcomes always HOLD.

    SDK retries are disabled. Only completed, nonterminal no-image/invalid-image
    responses can retry (at most three calls, also constrained by the ledger).
    Explicit guard injection is for offline tests; production uses its DB guard.
    """
    output_dir = Path(output_dir)
    ref_paths = [Path(ref) for ref in ref_paths]
    if panel_idx <= 0 or not prompt_text.strip():
        raise GenerationHold("Valid panel and prompt required")
    for ref in ref_paths:
        if not ref.is_file():
            raise GenerationHold(f"Missing mandatory REF: {ref}")
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"P{panel_idx}.png"
    if guard is None:
        guard = ProductionGenerationGuard(
            scope=output_dir.as_posix(), panel=panel_idx,
            prompt=prompt_text + f"\n[model={_MODEL};aspect={aspect_ratio}]",
            refs=ref_paths,
        )
    if guard.reuse(output_path):
        try:
            _validate_png(output_path.read_bytes())
        except Exception as exc:
            raise GenerationHold("Successful artifact failed PNG validation") from exc
        return output_path, 0.0
    client = _get_client()
    total_cost = 0.0
    for attempt in range(1, 4):
        token = guard.reserve()
        started = time.monotonic()
        record = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "panel": panel_idx, "model": _MODEL, "attempt": attempt,
            "ref_images": [str(p) for p in ref_paths],
            "cost_usd": None, "cost_estimated": False,
        }
        # Every reservation fingerprints these exact provider inputs. A new prompt
        # needs a new reviewed revision, even after a completed retryable failure.
        prompt = prompt_text
        try:
            image_bytes, input_tokens, output_tokens = _generate_one(
                client, prompt, ref_paths, aspect_ratio=aspect_ratio
            )
        except NoImageResponse as exc:
            known_cost = _calc_cost(exc.prompt_tokens, exc.output_tokens) if (
                exc.prompt_tokens or exc.output_tokens
            ) else None
            terminal = _terminal_error(exc)
            record.update(status="terminal" if terminal else "failed", cost_usd=known_cost,
                          error=str(exc), latency_sec=round(time.monotonic() - started, 2))
            _write_jsonl_log(log_path, record)
            guard.finish(token, state="terminal" if terminal else "failed", actual_cost=known_cost)
            if terminal:
                raise GenerationHold(str(exc)) from exc
            total_cost += known_cost if known_cost is not None else _calc_cost(
                _estimate_prompt_tokens(prompt, ref_paths), _ESTIMATED_IMAGE_OUTPUT_TOKENS
            )
            continue
        except Exception as exc:
            # Even server errors can have ambiguous billing; never automatically retry.
            terminal = _terminal_error(exc)
            record.update(status="terminal" if terminal else "unknown", error=str(exc),
                          latency_sec=round(time.monotonic() - started, 2))
            _write_jsonl_log(log_path, record)
            guard.finish(token, state="terminal" if terminal else "unknown", actual_cost=None)
            raise GenerationHold("Provider outcome requires reconciliation: " + str(exc)) from exc

        measured = bool(input_tokens or output_tokens)
        actual_cost = _calc_cost(input_tokens, output_tokens) if measured else None
        charged = actual_cost if measured else _calc_cost(
            _estimate_prompt_tokens(prompt, ref_paths), _ESTIMATED_IMAGE_OUTPUT_TOKENS
        )
        total_cost += charged
        record.update(prompt_tokens=input_tokens, output_tokens=output_tokens,
                      cost_usd=actual_cost, cost_estimated=not measured,
                      estimated_cost_usd=None if measured else charged,
                      latency_sec=round(time.monotonic() - started, 2))
        try:
            _validate_png(image_bytes)
        except Exception as exc:
            record.update(status="failed", error=str(exc))
            _write_jsonl_log(log_path, record)
            guard.finish(token, state="failed", actual_cost=actual_cost)
            continue
        try:
            _persist_exclusive(output_path, image_bytes)
            guard.finish(token, state="success", actual_cost=actual_cost,
                         output_hash=hashlib.sha256(image_bytes).hexdigest())
        except Exception as exc:
            # A paid result exists or its ledger commit failed; preserve it and stop.
            record.update(status="hold", output=str(output_path), error=str(exc))
            _write_jsonl_log(log_path, record)
            raise GenerationHold("Image persistence/ledger requires reconciliation: " + str(exc)) from exc
        record.update(status="success", output=str(output_path))
        _write_jsonl_log(log_path, record)
        return output_path, total_cost
    return None, total_cost


def generate_episode(
    panels: list[dict],
    output_dir: Path,
) -> tuple[list[Path | None], float]:
    """
    에피소드 전체 패널 이미지 생성.

    Args:
        panels: [{"panel_idx": int, "prompt_text": str, "ref_image_paths": [Path]}]
        output_dir: output/episodes/DATE/panels/

    Returns:
        (패널 경로 목록, 총 비용 USD)
        실패 패널은 None으로 포함.
    """
    log_path = output_dir / "gemini_run.log"
    results: list[Path | None] = []
    total_cost = 0.0

    for panel in panels:
        idx = panel.get("panel_idx", 0)
        prompt = panel.get("prompt_text", "")
        refs = panel.get("ref_image_paths", [])

        path, panel_cost = generate_panel(
            panel_idx=idx,
            prompt_text=prompt,
            ref_paths=refs,
            output_dir=output_dir,
            log_path=log_path,
        )
        results.append(path)
        total_cost += panel_cost

    success_count = sum(1 for p in results if p is not None)
    logger.info(
        "[gemini] 에피소드 생성 완료: %d/%d 패널 성공 (cost=$%.4f)",
        success_count,
        len(results),
        total_cost,
    )
    return results, total_cost
