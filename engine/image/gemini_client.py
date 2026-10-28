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

from engine.image.generation_guard import (
    GenerationHold,
    ProductionGenerationGuard,
    generation_revision,
)
from engine.image.retry_policy import (
    CONTENT_REASONS,
    REVIEW_REASONS,
    ReviewedRetryPlan,
    max_retries,
    normalized_reason,
    retry_delay,
    retry_enabled,
)

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


def _api_value(obj: object, snake: str, camel: str, default: object = None) -> object:
    return _obj_value(obj, snake, _obj_value(obj, camel, default))


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
        feedback = _api_value(response, "prompt_feedback", "promptFeedback")
        reason = _api_value(feedback, "block_reason", "blockReason")
        return str(reason) if reason else "no_candidates"
    return str(_api_value(candidates[0], "finish_reason", "finishReason", "unknown"))


def _response_diagnostics(response: object) -> dict:
    """Allowlisted provider evidence; excludes content/image bytes and headers."""
    def clean(value):
        if hasattr(value, "model_dump"):
            return value.model_dump(mode="json")
        if isinstance(value, list):
            return [clean(item) for item in value]
        if isinstance(value, dict):
            return {key: clean(item) for key, item in value.items()}
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        return str(value)
    candidates = _obj_value(response, "candidates", []) or []
    first = candidates[0] if candidates else None
    feedback = _api_value(response, "prompt_feedback", "promptFeedback")
    return {"finish_message": str(_api_value(first, "finish_message", "finishMessage", "") or "")[:2000],
            "safety_ratings": clean(_api_value(first, "safety_ratings", "safetyRatings", [])),
            "prompt_safety_ratings": clean(_api_value(feedback, "safety_ratings", "safetyRatings", [])),
            "prompt_block_reason": str(_api_value(feedback, "block_reason", "blockReason", "") or "")}


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
        aspect_ratio: "9:16" 등. None(기본)이면 비율을 명시하지 않음 — 출력 비율은 응답에서 검증
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
                    mime_type=("image/jpeg" if ref_path.suffix.lower() in {".jpg", ".jpeg"}
                               else "image/png"),
                )
            )
        else:
            raise GenerationHold(f"Missing mandatory REF: {ref_path}")

    config = types.GenerateContentConfig(
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True)
    )
    if aspect_ratio:
        # 정사각 이미지를 9:16 영상에 넣으면 상하 44% 가 검은 여백이 된다
        # (2026-09-07 W36 실측). 생성 단계에서 비율을 맞춘다.
        config = types.GenerateContentConfig(
            image_config=types.ImageConfig(aspect_ratio=aspect_ratio),
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True)
        )

    response = client.models.generate_content(
        model=_MODEL,
        contents=contents,
        config=config,
    )

    prompt_tokens, output_tokens = _extract_usage_tokens(response)

    reason = _response_finish_reason(response)
    if normalized_reason(reason) in CONTENT_REASONS | REVIEW_REASONS:
        raise NoImageResponse(reason, prompt_tokens, output_tokens, _response_diagnostics(response))

    # 응답에서 이미지 추출
    for part in _response_parts(response):
        inline_data = _obj_value(part, "inline_data")
        if inline_data:
            data = _obj_value(inline_data, "data")
            if data:
                return data, prompt_tokens, output_tokens

    raise NoImageResponse(_response_finish_reason(response), prompt_tokens, output_tokens, _response_diagnostics(response))


class NoImageResponse(RuntimeError):
    """A completed provider response without an image, preserving billed usage."""

    def __init__(self, reason: str, prompt_tokens: int, output_tokens: int, details: dict | None = None):
        super().__init__(f"Gemini completed without image (finish_reason={reason})")
        self.details = details or {}
        self.reason = reason
        self.prompt_tokens = prompt_tokens
        self.output_tokens = output_tokens


PROVIDER_REFUSAL_PATH = Path("output/provider-refusals.jsonl")


def _record_provider_refusal(panel_idx: int, reason: str, cost: float | None) -> None:
    """Best-effort evidence for failure alerts; never changes ledger or billing outcome."""
    record = {"code": "PROVIDER_REFUSAL", "panel": panel_idx, "finish_reason": str(reason),
              "cost_usd": cost, "run_id": os.environ.get("GITHUB_RUN_ID", "local")}
    try:
        PROVIDER_REFUSAL_PATH.parent.mkdir(parents=True, exist_ok=True)
        with PROVIDER_REFUSAL_PATH.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        logger.warning("[gemini] provider refusal evidence write failed")


def _terminal_error(exc: Exception) -> bool:
    if isinstance(exc, NoImageResponse) and normalized_reason(exc.reason) in CONTENT_REASONS | REVIEW_REASONS:
        return True
    status = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    if str(status) in {"400", "401", "403", "404", "429"}:
        return True
    message = str(exc).lower()
    return any(word in message for word in (
        "quota", "resource_exhausted", "budget", "billing", "permission_denied",
        "unauthenticated", "invalid_argument", "safety", "prohibited", "policy",
        "blocklist", "recitation", "spii", "blocked",
    ))


QUOTA_REASON = "QUOTA_EXHAUSTED"
# Unmeasured OpenAI usage is reported at the ledger's per-call reservation amount.
_OPENAI_UNMEASURED_COST = 0.10
PROVIDER_MAP_NAME = "image-providers.json"


def _gemini_quota_exhausted(exc: Exception) -> bool:
    """Structured Gemini quota/billing rejection (google-genai APIError code/status).

    Message-only errors keep the existing terminal HOLD; fallback needs a provider code.
    """
    try:
        code = int(getattr(exc, "code", None))
    except (TypeError, ValueError):
        code = None
    status = str(getattr(exc, "status", "") or "").upper()
    if code == 429 or status == "RESOURCE_EXHAUSTED":
        return True
    if code in {400, 403} and status in {"FAILED_PRECONDITION", "PERMISSION_DENIED"}:
        message = str(getattr(exc, "message", "") or "").lower()
        return any(word in message for word in ("billing", "prepay", "credit", "spend", "quota"))
    return False


class ProviderState:
    """Episode-wide provider selection. Once Gemini quota is exhausted the episode
    stays on OpenAI (no repeated Gemini calls) and every OpenAI panel uses one anchor.
    Persisted beside the PNGs so a rerun continues with the same provider and anchor.
    A record from another generation revision is ignored: recovery revisions start on
    Gemini again and may archive the old anchor PNG.
    """

    def __init__(self, output_dir: Path):
        self.output_dir = Path(output_dir)
        self.path = self.output_dir / PROVIDER_MAP_NAME
        self.panels: dict[str, dict] = {}
        self.fallback: dict | None = None
        self.style_anchor: Path | None = None
        self._openai = None
        self.revision = generation_revision()
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                if data.get("revision", 1) == self.revision:
                    self.panels = dict(data.get("panels") or {})
                    self.fallback = data.get("fallback")
            except (OSError, ValueError, AttributeError) as exc:
                raise GenerationHold("Image provider map unreadable; reconciliation required") from exc
        if self.fallback:
            self.style_anchor = self._restore_anchor(self.fallback)

    @property
    def active(self) -> str:
        return "openai" if self.fallback else "gemini"

    def _restore_anchor(self, fallback: dict) -> Path | None:
        name, digest = fallback.get("style_anchor"), fallback.get("style_anchor_sha256")
        if not name:
            return None
        anchor = Path(name)
        try:
            actual = hashlib.sha256(anchor.read_bytes()).hexdigest()
        except OSError as exc:
            raise GenerationHold(f"OpenAI fallback style anchor missing: {anchor}") from exc
        if actual != digest:
            raise GenerationHold("OpenAI fallback style anchor changed")
        return anchor

    def _choose_anchor(self, panel_idx: int) -> Path | None:
        from engine.image.openai_client import STYLE_ANCHOR_ASSET
        for idx in range(panel_idx - 1, 0, -1):
            candidate = self.output_dir / f"P{idx}.png"
            # Panels without a record predate the fallback and were made by Gemini.
            provider = (self.panels.get(str(idx)) or {}).get("provider", "gemini")
            if candidate.is_file() and provider == "gemini":
                return candidate
        return STYLE_ANCHOR_ASSET if STYLE_ANCHOR_ASSET.is_file() else None

    def _save(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps({"version": 1, "revision": self.revision,
                                         "fallback": self.fallback,
                                         "panels": self.panels}, ensure_ascii=False, indent=2),
                             encoding="utf-8")
        temporary.replace(self.path)

    def switch(self, panel_idx: int, reason: str) -> None:
        anchor = self._choose_anchor(panel_idx)
        self.style_anchor = anchor
        self.fallback = {
            "from_panel": panel_idx, "reason": reason,
            "run_id": os.environ.get("GITHUB_RUN_ID", "local"),
            "style_anchor": anchor.as_posix() if anchor else None,
            "style_anchor_sha256": hashlib.sha256(anchor.read_bytes()).hexdigest() if anchor else None,
        }
        self._save()
        logger.warning("[image] IMAGE_PROVIDER_FALLBACK from=P%s reason=%s style_anchor=%s",
                       panel_idx, reason, anchor)

    def record(self, panel_idx: int, output_path: Path, provider: str, model: str) -> None:
        self.panels[str(panel_idx)] = {
            "provider": provider, "model": model,
            "sha256": hashlib.sha256(Path(output_path).read_bytes()).hexdigest(),
        }
        self._save()

    def openai_client(self):
        if self._openai is None:
            from engine.image.openai_client import _get_client as get_openai_client
            self._openai = get_openai_client()
        return self._openai


def _openai_attempt(*, panel_idx: int, prompt_text: str, ref_paths: list[Path], output_path: Path,
                    log_path: Path, aspect_ratio: str | None, guard, settle,
                    state: ProviderState, attempt: int) -> tuple[Path | None, float]:
    """One reserved OpenAI call under the panel's existing ledger identity.

    Returns (path, cost) on success, (None, cost) for a settled invalid image.
    Every ambiguous or rejected outcome settles first, then HOLDs.
    """
    from engine.image import openai_client as oa

    anchor = state.style_anchor
    prompt = oa.build_prompt(prompt_text, len(ref_paths), anchor is not None)
    oa.check_inputs(prompt, ref_paths, anchor)
    model, quality, size = oa.model_name(), oa.quality_name(), oa.size_for(aspect_ratio)
    client = state.openai_client()
    token = guard.reserve()
    started = time.monotonic()
    record = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "run_id": os.environ.get("GITHUB_RUN_ID", "local"),
        "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT", "1"),
        "panel": panel_idx, "provider": "openai", "model": model, "quality": quality,
        "size": size, "attempt": attempt, "ref_images": [str(p) for p in ref_paths],
        "style_anchor": str(anchor) if anchor else None,
        "cost_usd": None, "cost_estimated": False,
    }

    def finish(**kwargs) -> GenerationHold | None:
        try:
            settle(token, **kwargs)
        except GenerationHold as hold:
            return hold
        return None

    def log(**fields) -> None:
        record.update(latency_sec=round(time.monotonic() - started, 2), **fields)
        try:
            _write_jsonl_log(log_path, record)
        except OSError:
            logger.warning("[openai] local evidence unavailable; panel=%s", panel_idx)

    try:
        guard.store_attempt_diagnostic(token, "inputs", {
            "run_id": os.environ.get("GITHUB_RUN_ID", "local"),
            "provider": "openai", "model": model, "quality": quality, "size": size,
            "aspect_ratio": aspect_ratio, "prompt_text": prompt,
            "ref_sha256": [hashlib.sha256(ref.read_bytes()).hexdigest() for ref in ref_paths],
            "style_anchor_sha256": hashlib.sha256(anchor.read_bytes()).hexdigest() if anchor else None,
        })
    except Exception as exc:
        settle(token, state="failed", actual_cost=0.0)
        raise GenerationHold("Private image inputs unavailable; provider not called") from exc
    try:
        image_bytes, cost = oa.generate_one(client, prompt, ref_paths, anchor, aspect_ratio)
    except oa.OpenAIQuotaExhausted as exc:
        hold = finish(state="failed", actual_cost=0.0, reason="OPENAI_QUOTA_EXHAUSTED")
        log(status="failed", cost_usd=0.0, error=str(exc), result_code="IMAGE_PROVIDERS_EXHAUSTED")
        raise GenerationHold(f"IMAGE_PROVIDERS_EXHAUSTED; panel={panel_idx}; "
                             f"gemini and openai quota exhausted{'; ' + str(hold) if hold else ''}") from exc
    except oa.OpenAITerminal as exc:
        hold = finish(state="terminal", actual_cost=0.0, reason="OPENAI_TERMINAL")
        log(status="terminal", cost_usd=0.0, error=str(exc), result_code="PROVIDER_TERMINAL")
        raise GenerationHold(f"OpenAI fallback rejected; panel={panel_idx}; {exc}"
                             f"{'; ' + str(hold) if hold else ''}") from exc
    except oa.OpenAINoImage as exc:
        hold = finish(state="failed", actual_cost=exc.cost)
        log(status="failed", cost_usd=exc.cost, error=str(exc), result_code="INVALID_IMAGE")
        if hold is not None or exc.cost is None:
            raise GenerationHold(f"OpenAI image usage missing; reconciliation required; panel={panel_idx}") from exc
        return None, exc.cost
    except Exception as exc:
        # Refusals, server errors and timeouts have unconfirmed billing: never retry.
        refusal = isinstance(exc, oa.OpenAIRefusal)
        if refusal:
            _record_provider_refusal(panel_idx, "OPENAI_MODERATION_BLOCKED", None)
        hold = finish(state="unknown", actual_cost=None,
                      reason="OPENAI_MODERATION_BLOCKED" if refusal else None)
        log(status="unknown", error=type(exc).__name__,
            result_code="CONTENT_REVIEW_REQUIRED" if refusal else "PROVIDER_OUTCOME_UNKNOWN")
        logger.error("[openai] PROVIDER_OUTCOME_UNCERTAIN panel=%s provider_error_type=%s",
                     panel_idx, type(exc).__name__)
        raise GenerationHold(
            f"Provider outcome requires reconciliation; panel={panel_idx}; provider=openai; "
            f"provider_error_type={type(exc).__name__}; "
            f"settlement_error_type={type(hold).__name__ if hold else 'none'}"
        ) from exc

    try:
        image_bytes = oa.normalize_to_anchor(image_bytes, anchor)
        _validate_png(image_bytes)
    except Exception as exc:
        hold = finish(state="failed", actual_cost=cost)
        log(status="failed", cost_usd=cost, error=str(exc), result_code="INVALID_IMAGE")
        if hold is not None or cost is None:
            raise GenerationHold("Image usage missing; reconciliation required") from exc
        return None, cost
    try:
        _persist_exclusive(output_path, image_bytes)
        settle(token, state="success", actual_cost=cost,
               output_hash=hashlib.sha256(image_bytes).hexdigest())
    except Exception as exc:
        log(status="hold", cost_usd=cost, output=str(output_path), error=str(exc))
        raise GenerationHold("Image persistence/ledger requires reconciliation: " + str(exc)) from exc
    state.record(panel_idx, output_path, "openai", model)
    log(status="success", cost_usd=cost, cost_estimated=cost is None,
        estimated_cost_usd=_OPENAI_UNMEASURED_COST if cost is None else None, output=str(output_path))
    return output_path, cost if cost is not None else _OPENAI_UNMEASURED_COST


def _settle_gemini_quota(exc: Exception, *, token: str, settle, guard, record: dict,
                         started: float, log_path: Path, panel_idx: int) -> None:
    """A quota/billing rejection produced no image: settle at zero cost, keep evidence."""
    try:
        settle(token, state="failed", actual_cost=0.0, reason=QUOTA_REASON)
    except GenerationHold as hold:
        raise GenerationHold(f"Gemini quota settlement not confirmed; panel={panel_idx}; {hold}") from exc
    evidence = {"run_id": os.environ.get("GITHUB_RUN_ID", "local"),
                "finish_reason": QUOTA_REASON, "cost_usd": 0.0,
                "provider_code": str(getattr(exc, "code", "")),
                "provider_status": str(getattr(exc, "status", "") or ""),
                "provider_message": str(getattr(exc, "message", "") or "")[:300]}
    record.update(status="quota_exhausted", cost_usd=0.0, provider="gemini",
                  result_code=QUOTA_REASON, error=type(exc).__name__,
                  provider_code=evidence["provider_code"],
                  provider_status=evidence["provider_status"],
                  latency_sec=round(time.monotonic() - started, 2))
    try:
        _write_jsonl_log(log_path, record)
    except OSError:
        logger.warning("[gemini] local evidence unavailable after quota settlement")
    try:
        guard.store_attempt_diagnostic(token, "refusal", evidence)
    except Exception:
        # Evidence only; the zero-cost settlement is already durable.
        logger.warning("[gemini] quota diagnostic not stored; panel=%s", panel_idx)
    logger.warning("[gemini] QUOTA_EXHAUSTED panel=%s code=%s status=%s -> OpenAI fallback",
                   panel_idx, evidence["provider_code"], evidence["provider_status"])


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


def _write_private_inputs(panel_idx: int, plan, refs: list[Path]) -> dict:
    import uuid
    configured = os.environ.get("ICG_IMAGE_DIAGNOSTICS_DIR")
    if not configured:
        raise GenerationHold("Private image diagnostics directory required")
    root = Path(configured).resolve()
    if root == Path("output").resolve() or Path("output").resolve() in root.parents:
        raise GenerationHold("Private diagnostics must be outside public artifacts")
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    root.chmod(0o700)
    path = root / f"panel-{panel_idx}-{uuid.uuid4().hex}.json"
    record = {"panel": panel_idx, "plan_id": plan.plan_id,
              "prompts": list(plan.prompts),
              "ref_sha256": [hashlib.sha256(ref.read_bytes()).hexdigest() for ref in refs]}
    with path.open("x", encoding="utf-8") as handle:
        path.chmod(0o600)
        json.dump(record, handle, ensure_ascii=False)
    return record


def generate_panel(
    panel_idx: int,
    prompt_text: str,
    ref_paths: list[Path],
    output_dir: Path,
    log_path: Path,
    aspect_ratio: str | None = None,
    *,
    guard=None,
    retry_plan: dict | None = None,
    reuse_only: bool = False,
    sleeper=time.sleep,
    provider_state: ProviderState | None = None,
) -> tuple[Path | None, float]:
    """Generate with durable pre-call reservations; ambiguous outcomes always HOLD.

    SDK retries are disabled. Only completed, nonterminal no-image/invalid-image
    responses can retry (at most three calls, also constrained by the ledger).
    Explicit guard injection is for offline tests; production uses its DB guard.
    With provider_state (Run Market only), a structured Gemini quota rejection settles
    at zero cost and the same panel continues on the OpenAI fallback.
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
    enabled = retry_enabled()
    retries = max_retries() if enabled else 2
    plan = ReviewedRetryPlan.from_bundle(retry_plan, prompt_text, ref_paths) if enabled and retry_plan else None
    if plan:
        private_inputs = _write_private_inputs(panel_idx, plan, ref_paths)
    if guard is None:
        guard = ProductionGenerationGuard(
            scope=output_dir.as_posix(), panel=panel_idx,
            prompt=prompt_text + f"\n[model={_MODEL};aspect={aspect_ratio}]",
            refs=ref_paths, retry_plan_id=plan.plan_id if plan else None,
        )
    variant = guard.select_retry_variant(plan.prompts, f"\n[model={_MODEL};aspect={aspect_ratio}]") if plan else 0
    if plan:
        guard.store_diagnostic("inputs", private_inputs)
    if plan and provider_state is not None and provider_state.active == "openai":
        raise GenerationHold("Reviewed retry plan cannot use the OpenAI fallback")
    if guard.reuse(output_path):
        try:
            _validate_png(output_path.read_bytes())
        except Exception as exc:
            raise GenerationHold("Successful artifact failed PNG validation") from exc
        return output_path, 0.0
    if reuse_only:
        raise GenerationHold("Preserved image receipt missing; regeneration forbidden")
    total_cost = 0.0
    def settle(token, *, state, actual_cost, output_hash=None, reason=None):
        from engine.image.provider_outcome import outcome_v3_enabled
        if outcome_v3_enabled() and not plan:
            return guard.finish_outcome(token, state=state, actual_cost=actual_cost,
                                        output_hash=output_hash, reason=reason)
        if plan:
            guard.finish_reviewed(token, state=state, actual_cost=actual_cost,
                                  output_hash=output_hash, reason=reason)
        else:
            guard.finish(token, state=state, actual_cost=actual_cost, output_hash=output_hash)

    used = getattr(guard, "retry_attempts_used", 0) if plan else 0
    if type(used) is not int or not 0 <= used <= 3:
        raise GenerationHold("Invalid durable retry count")
    allowed_calls = min(retries + 1, 3 - used)
    if allowed_calls <= 0:
        raise PanelGenerationFailed("image retry exhausted")
    client = None
    for attempt in range(1, allowed_calls + 1):
        if provider_state is not None and provider_state.active == "openai":
            path, cost = _openai_attempt(
                panel_idx=panel_idx, prompt_text=prompt_text, ref_paths=ref_paths,
                output_path=output_path, log_path=log_path, aspect_ratio=aspect_ratio,
                guard=guard, settle=settle, state=provider_state, attempt=attempt,
            )
            total_cost += cost
            if path is not None:
                return path, total_cost
            continue
        if client is None:
            client = _get_client()
        token = guard.reserve()
        started = time.monotonic()
        record = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "run_id": os.environ.get("GITHUB_RUN_ID", "local"),
            "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT", "1"),
            "panel": panel_idx, "model": _MODEL, "attempt": attempt,
            "ref_images": [str(p) for p in ref_paths],
            "cost_usd": None, "cost_estimated": False,
        }
        # Every reservation fingerprints these exact provider inputs. A new prompt
        # needs a new reviewed revision, even after a completed retryable failure.
        prompt = plan.prompts[variant] if plan else prompt_text
        if not plan:
            try:
                guard.store_attempt_diagnostic(token, "inputs", {
                    "run_id": os.environ.get("GITHUB_RUN_ID", "local"),
                    "model": _MODEL, "aspect_ratio": aspect_ratio,
                    "prompt_text": prompt,
                    "ref_sha256": [hashlib.sha256(ref.read_bytes()).hexdigest()
                                   for ref in ref_paths],
                })
            except Exception as exc:
                # No request was submitted: release the reservation at known zero cost.
                settle(token, state="failed", actual_cost=0.0)
                raise GenerationHold("Private image inputs unavailable; provider not called") from exc
        try:
            image_bytes, input_tokens, output_tokens = _generate_one(
                client, prompt, ref_paths, aspect_ratio=aspect_ratio
            )
        except NoImageResponse as exc:
            known_cost = _calc_cost(exc.prompt_tokens, exc.output_tokens) if (
                exc.prompt_tokens or exc.output_tokens
            ) else None
            terminal = _terminal_error(exc)
            reason = normalized_reason(exc.reason)
            if plan:
                private_record = {"panel": panel_idx, "plan_id": plan.plan_id,
                                      "run_id": os.environ.get("GITHUB_RUN_ID", "local"),
                                      "attempt": used + attempt, "finish_reason": reason,
                                      "prompt_hash": hashlib.sha256(prompt.encode()).hexdigest(),
                                      "prompt_tokens": exc.prompt_tokens, "output_tokens": exc.output_tokens,
                                      "details": exc.details}
            record.update(status="terminal" if terminal else "failed", cost_usd=known_cost,
                          error=str(exc), latency_sec=round(time.monotonic() - started, 2))
            refusal = f"provider_reason={exc.reason}; panel={panel_idx}"
            # Surface the provider's reason before settlement can replace it with a hold text.
            logger.warning("[gemini] PROVIDER_REFUSAL %s terminal=%s cost=%s",
                           refusal, terminal, known_cost)
            if terminal:
                _record_provider_refusal(panel_idx, exc.reason, known_cost)
            settlement_error = None
            settlement_receipt = None
            try:
                settlement_receipt = settle(token, state="terminal" if terminal else "failed",
                       actual_cost=known_cost, reason=reason)
            except GenerationHold as hold:
                settlement_error = hold
            # A completed paid response is settled before any local evidence I/O.
            record.update(result_code="CONTENT_REVIEW_REQUIRED" if terminal else "INVALID_IMAGE",
                          settlement_status="RECONCILIATION_REQUIRED" if settlement_error else "SETTLED")
            try:
                _write_jsonl_log(log_path, record)
            except OSError:
                logger.warning("[gemini] local evidence unavailable after settlement; panel=%s", panel_idx)
            if not plan:
                try:
                    guard.store_attempt_diagnostic(token, "refusal", {
                        "run_id": os.environ.get("GITHUB_RUN_ID", "local"),
                        "finish_reason": reason, "cost_usd": known_cost,
                        "prompt_tokens": exc.prompt_tokens,
                        "output_tokens": exc.output_tokens, "details": exc.details,
                    })
                except GenerationHold as hold:
                    settlement_error = settlement_error or hold
            if plan:
                # Settle the paid result first; evidence failure must never trigger a new call.
                try:
                    guard.store_diagnostic("refusal", private_record)
                except GenerationHold as hold:
                    settlement_error = settlement_error or hold
                try:
                    import uuid
                    private = Path(os.environ["ICG_IMAGE_DIAGNOSTICS_DIR"]).resolve()
                    evidence = private / f"response-{panel_idx}-{uuid.uuid4().hex}.json"
                    with evidence.open("x", encoding="utf-8") as handle:
                        evidence.chmod(0o600)
                        json.dump(private_record, handle, ensure_ascii=False)
                except OSError:
                    settlement_error = settlement_error or GenerationHold("Private response evidence unavailable after settlement")
            if settlement_error is not None:
                raise GenerationHold(f"{settlement_error}; {refusal}") from exc
            if terminal:
                if plan and reason in CONTENT_REASONS and known_cost is not None:
                    total_cost += known_cost
                    if attempt < allowed_calls and variant + 1 < len(plan.prompts):
                        variant += 1
                        logger.info(
                            "[gemini] REVIEWED_SCENE_REPAIR panel=%s reason=%s variant=%s remaining_calls=%s",
                            panel_idx, reason, variant, allowed_calls - attempt,
                        )
                        guard.activate_prompt(plan.prompts[variant] + f"\n[model={_MODEL};aspect={aspect_ratio}]")
                        sleeper(retry_delay(attempt))
                        continue
                    raise PanelGenerationFailed(f"content retry exhausted; {refusal}", total_cost) from exc
                from engine.image.provider_outcome import (
                    SettlementReceipt,
                    content_isolation_v4_enabled,
                )
                if (content_isolation_v4_enabled() and not plan
                        and getattr(guard, "revision", None) == 1
                        and isinstance(settlement_receipt, SettlementReceipt)
                        and settlement_receipt.result_code == "CONTENT_REVIEW_REQUIRED"
                        and settlement_receipt.state == "terminal"
                        and settlement_receipt.hold_code == "CONTENT_REVIEW_REQUIRED"
                        and known_cost is not None and 0 <= known_cost <= 0.10
                        and settlement_receipt.cost_usd == known_cost):
                    raise SettledContentRefusal(
                        f"provider refused image; {refusal}; code=CONTENT_REVIEW_REQUIRED",
                        total_cost + known_cost, reason,
                    ) from exc
                raise GenerationHold(f"provider refused image; {refusal}; code=CONTENT_REVIEW_REQUIRED") from exc
            total_cost += known_cost if known_cost is not None else _calc_cost(
                _estimate_prompt_tokens(prompt, ref_paths), _ESTIMATED_IMAGE_OUTPUT_TOKENS
            )
            if enabled and known_cost is None:
                raise GenerationHold("Image usage missing; reconciliation required") from exc
            if enabled and attempt < allowed_calls:
                sleeper(retry_delay(attempt))
            continue
        except Exception as exc:
            if (provider_state is not None and not plan and _gemini_quota_exhausted(exc)):
                from engine.image.openai_client import fallback_ready
                if fallback_ready():
                    _settle_gemini_quota(exc, token=token, settle=settle, guard=guard,
                                         record=record, started=started, log_path=log_path,
                                         panel_idx=panel_idx)
                    if attempt >= allowed_calls:
                        raise GenerationHold(
                            f"Gemini quota exhausted; no panel budget left for OpenAI; panel={panel_idx}"
                        ) from exc
                    provider_state.switch(panel_idx, QUOTA_REASON)
                    continue
            # Even server errors can have ambiguous billing; never automatically retry.
            terminal = _terminal_error(exc)
            record.update(status="terminal" if terminal else "unknown", error=str(exc),
                          latency_sec=round(time.monotonic() - started, 2))
            # Never let a ledger-settlement exception erase the provider failure.
            # Keep full exception text out of public GitHub logs (may contain request data).
            provider_type = type(exc).__name__
            settlement_type = None
            try:
                settle(token, state="terminal" if terminal else "unknown", actual_cost=None)
            except Exception as settlement_exc:
                settlement_type = type(settlement_exc).__name__
            record["error"] = type(exc).__name__
            try:
                _write_jsonl_log(log_path, record)
            except OSError:
                logger.warning("[gemini] local evidence unavailable after uncertain outcome")
            logger.error(
                "[gemini] PROVIDER_OUTCOME_UNCERTAIN panel=%s provider_error_type=%s "
                "settlement_error_type=%s ledger_state=%s",
                panel_idx, provider_type, settlement_type or "none",
                "terminal" if terminal else "unknown",
            )
            raise GenerationHold(
                f"Provider outcome requires reconciliation; panel={panel_idx}; "
                f"provider_error_type={provider_type}; "
                f"settlement_error_type={settlement_type or 'none'}"
            ) from exc

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
            settle(token, state="failed", actual_cost=actual_cost)
            _write_jsonl_log(log_path, record)
            if enabled and actual_cost is None:
                raise GenerationHold("Image usage missing; reconciliation required")
            if enabled and attempt < allowed_calls:
                sleeper(retry_delay(attempt))
            continue
        try:
            _persist_exclusive(output_path, image_bytes)
            settle(token, state="success", actual_cost=actual_cost,
                         output_hash=hashlib.sha256(image_bytes).hexdigest())
        except Exception as exc:
            # A paid result exists or its ledger commit failed; preserve it and stop.
            record.update(status="hold", output=str(output_path), error=str(exc))
            _write_jsonl_log(log_path, record)
            raise GenerationHold("Image persistence/ledger requires reconciliation: " + str(exc)) from exc
        record.update(status="success", output=str(output_path))
        _write_jsonl_log(log_path, record)
        if provider_state is not None:
            provider_state.record(panel_idx, output_path, "gemini", _MODEL)
        return output_path, total_cost
    if enabled:
        raise PanelGenerationFailed("image retry exhausted", total_cost)
    return None, total_cost


class PanelGenerationFailed(GenerationHold):
    """A settled panel failure; independent panels can still be generated."""

    def __init__(self, message: str, cost: float = 0.0):
        super().__init__(message)
        self.cost = cost


class SettledContentRefusal(GenerationHold):
    """Confirmed ordinary refusal; never retry this panel or release its ledger hold."""

    def __init__(self, message: str, cost: float, provider_reason: str):
        super().__init__(message)
        self.cost = cost
        self.provider_reason = provider_reason


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
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    log_path = output_dir / "gemini_run.log"
    enabled = retry_enabled()
    limit = max_retries() if enabled else 2
    # Validate every provided plan before P1 can spend money. Missing plans retain
    # the ordinary fail-closed contract; a retry flag is never an approval.
    for panel in panels:
        if enabled and panel.get("retry_plan"):
            ReviewedRetryPlan.from_bundle(panel["retry_plan"], panel.get("prompt_text", ""),
                                           [Path(p) for p in panel.get("ref_image_paths", [])])
    reviewed_count = sum(bool(p.get("retry_plan")) for p in panels) if enabled else 0
    from engine.image.openai_client import fallback_enabled, fallback_ready
    provider_state = ProviderState(output_dir) if fallback_ready() else None
    if provider_state is None and fallback_enabled():
        logger.warning("[image] OpenAI fallback enabled but OPENAI_API_KEY missing; "
                       "Gemini quota exhaustion keeps the existing HOLD")
    # Verify every protected image before any missing panel can spend money.
    # A missing receipt/file must never fall through to a provider reservation.
    preserved_results = {}
    for panel in panels:
        if panel.get("reuse_only"):
            if panel.get("retry_plan"):
                raise GenerationHold("Preserved image cannot have a retry plan")
            preserved_results[panel["panel_idx"]] = generate_panel(
                panel_idx=panel["panel_idx"], prompt_text=panel["prompt_text"],
                ref_paths=panel["ref_image_paths"], output_dir=output_dir,
                log_path=log_path, reuse_only=True,
                aspect_ratio=panel.get("aspect_ratio"),
            )
    logger.info("[gemini] image tasks=%d; reviewed content retry plans=%d; extra retry limit=%d. "
                "A refused panel always requires review; only verified opt-in v4 outcomes allow independent panels.",
                len(panels), reviewed_count, limit)
    results: list[Path | None] = []
    summary = []
    content_holds = []
    total_cost = 0.0

    def write_summary(*, complete=False, held_panel=None, provider_reason=None):
        if held_panel is None and content_holds:
            held_panel = content_holds[0]["panel"]
            if provider_reason is None:
                provider_reason = content_holds[0]["provider_reason"]
        pending = [{"panel": p.get("panel_idx", 0), "status": "not_attempted",
                    "cost_usd": None} for p in panels[len(summary):]]
        observed_cost = 0.0
        try:
            for line in log_path.read_text(encoding="utf-8").splitlines():
                try:
                    item = json.loads(line)
                    if (item.get("run_id") == os.environ.get("GITHUB_RUN_ID", "local")
                            and item.get("run_attempt") == os.environ.get("GITHUB_RUN_ATTEMPT", "1")
                            and isinstance(item.get("cost_usd"), (int, float))):
                        observed_cost += item["cost_usd"]
                except (ValueError, AttributeError, TypeError):
                    continue
        except OSError:
            pass
        records = summary + pending
        (output_dir / "generation-summary.json").write_text(
            json.dumps({"panels": records, "complete": complete,
                        "run_id": os.environ.get("GITHUB_RUN_ID", "local"),
                        "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT", "1"),
                        "expected_images": len(panels),
                        "successful_images": sum(p["status"] == "success" for p in records),
                        "not_attempted_images": len(pending),
                        "reviewed_retry_panels": reviewed_count,
                        "content_retry_policy": "reviewed_plan_required",
                        "provider_reason": provider_reason,
                        "observed_provider_cost_usd": observed_cost,
                        "observed_usage_cost_usd": observed_cost,
                        "returned_panel_cost_usd": total_cost,
                        "cost_scope": "current_run_attempt",
                        "cost_source": "usage_calculation",
                        "result_code": "CONTENT_REVIEW_REQUIRED" if provider_reason in CONTENT_REASONS | REVIEW_REASONS else
                                       "IMAGE_SUCCESS" if complete else "IMAGE_INCOMPLETE",
                        "cost_usd": total_cost, "held_panel": held_panel,
                        "image_provider_fallback": provider_state.fallback if provider_state else None,
                        "provider_by_panel": {k: v["provider"] for k, v in provider_state.panels.items()}
                        if provider_state else {},
                        "held_panels": [p["panel"] for p in summary if p["status"] == "held"],
                        "cost_complete": len(summary) == len(panels) and all(
                            isinstance(p.get("cost_usd"), (int, float)) for p in summary)}), encoding="utf-8",
        )
        from engine.image.provider_outcome import outcome_v3_enabled
        if outcome_v3_enabled():
            # Per-execution telemetry never overwrites narrative status or artifact pointers.
            from engine.common.supabase_client import get_client, get_schema
            from engine.image.generation_guard import generation_revision
            report = json.loads((output_dir / "generation-summary.json").read_text())
            keys = {"run_id", "run_attempt", "expected_images", "successful_images",
                    "not_attempted_images", "held_panel", "provider_reason", "complete",
                    "result_code", "observed_usage_cost_usd", "cost_complete"}
            try:
                result = get_client().schema(get_schema()).rpc("image_generation_store_run_status_v3", {
                    "p_scope": output_dir.as_posix(), "p_revision": generation_revision(),
                    "p_run_id": report["run_id"], "p_run_attempt": report["run_attempt"],
                    "p_summary": {k: v for k, v in report.items() if k in keys},
                }).execute().data
                if not isinstance(result, dict) or result.get("stored") is not True:
                    raise ValueError("Run status not stored")
            except Exception:
                logger.warning("[gemini] run status telemetry unavailable; artifact summary preserved")

    write_summary()

    for panel in panels:
        idx = panel.get("panel_idx", 0)
        prompt = panel.get("prompt_text", "")
        refs = panel.get("ref_image_paths", [])

        try:
            kwargs = {"retry_plan": panel.get("retry_plan")} if retry_enabled() else {}
            if panel.get("reuse_only"):
                kwargs["reuse_only"] = True
            if provider_state is not None:
                kwargs["provider_state"] = provider_state
            path, panel_cost = preserved_results[idx] if idx in preserved_results else generate_panel(
                panel_idx=idx, prompt_text=prompt, ref_paths=refs,
                output_dir=output_dir, log_path=log_path,
                **({"aspect_ratio": panel["aspect_ratio"]} if "aspect_ratio" in panel else {}), **kwargs,
            )
        except SettledContentRefusal as exc:
            # This typed exception is emitted only after a verified v3 receipt and diagnostics.
            # The opt-in v4 DB contract still enforces the scope budgets and unresolved holds.
            content_holds.append({"panel": idx, "provider_reason": exc.provider_reason})
            results.append(None)
            total_cost += exc.cost
            summary.append({"panel": idx, "status": "held", "cost_usd": exc.cost})
            write_summary()
            logger.warning("[gemini] panel=%s settled content refusal isolated; review required", idx)
            continue
        except PanelGenerationFailed as exc:
            logger.warning("[gemini] panel=%s settled failure: %s", idx, exc)
            path, panel_cost = None, exc.cost
        except GenerationHold as exc:
            summary.append({"panel": idx, "status": "held", "cost_usd": None})
            cause = exc.__cause__
            provider_reason = normalized_reason(cause.reason) if isinstance(cause, NoImageResponse) else None
            write_summary(held_panel=idx, provider_reason=provider_reason)
            logger.error("[gemini] IMAGE_HOLD: %d/%d images ready; P%d held; %d not attempted. "
                         "Preserve successful PNGs; inspect original inputs before recovery.",
                         sum(p["status"] == "success" for p in summary), len(panels), idx,
                         len(panels) - len(summary))
            raise
        results.append(path)
        total_cost += panel_cost
        summary.append({"panel": idx, "status": "success" if path else "failed",
                        "cost_usd": panel_cost})
        write_summary()

    if content_holds:
        write_summary()
        held = ",".join(str(item["panel"]) for item in content_holds)
        raise GenerationHold(
            f"code=CONTENT_REVIEW_REQUIRED; held_panels={held}; "
            "independent panels processed; preserve successful PNGs"
        )

    success_count = sum(1 for p in results if p is not None)
    logger.info(
        "[gemini] 에피소드 생성 완료: %d/%d 패널 성공 (cost=$%.4f)",
        success_count,
        len(results),
        total_cost,
    )
    write_summary(complete=success_count == len(panels))
    return results, total_cost
