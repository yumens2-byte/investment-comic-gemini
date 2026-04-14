"""
engine/image/gemini_client.py
Gemini 2.5 Flash Image API 클라이언트.

⚠️ CRITICAL:
  genai.Client(api_key=os.environ["GEMINI_API_SUB_PAY_KEY"]) — GEMINI_API_SUB_PAY_KEY 고정.
  GEMINI_API_KEY 이름 절대 사용 금지 (doc 19 patch).

RULE 07: 모든 패널에 캐릭터 REF 이미지 멀티 입력 주입.
재시도: 패널별 3회, 최종 실패 시 text_card fallback.
비용 계산: prompt_tokens * 0.30 + output_tokens * 30.0, 분모 1e6.
로그: output/episodes/{date}/panels/gemini_run.log (JSONL)
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

from engine.common.retry import image_retry

logger = logging.getLogger(__name__)

_MODEL = "gemini-2.5-flash-image"
_COST_INPUT_PER_1M = 0.30   # USD per 1M input tokens
_COST_OUTPUT_PER_1M = 30.0  # USD per 1M output tokens


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
    return genai.Client(api_key=pay_key)


def _calc_cost(prompt_tokens: int, output_tokens: int) -> float:
    """Gemini 비용 계산 (USD)."""
    return (
        prompt_tokens * _COST_INPUT_PER_1M / 1_000_000
        + output_tokens * _COST_OUTPUT_PER_1M / 1_000_000
    )


def _write_jsonl_log(log_path: Path, record: dict) -> None:
    """gemini_run.log에 JSONL 레코드 추가."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


@image_retry()
def _generate_one(
    client,
    prompt_text: str,
    ref_paths: list[Path],
) -> bytes:
    """
    Gemini API 단일 패널 이미지 생성.

    Args:
        client: genai.Client 인스턴스.
        prompt_text: 패널 프롬프트.
        ref_paths: 캐릭터 REF 이미지 경로 목록.

    Returns:
        이미지 바이너리 (PNG).

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
            logger.warning("[gemini] REF 이미지 없음: %s", ref_path)

    response = client.models.generate_content(
        model=_MODEL,
        contents=contents,
    )

    # 응답에서 이미지 추출
    for part in response.candidates[0].content.parts:
        if hasattr(part, "inline_data") and part.inline_data:
            return part.inline_data.data

    raise RuntimeError("Gemini 응답에 이미지 없음 — fallback 필요")


def generate_panel(
    panel_idx: int,
    prompt_text: str,
    ref_paths: list[Path],
    output_dir: Path,
    log_path: Path,
) -> Path | None:
    """
    패널 이미지 생성 + P{N}.png 저장 + gemini_run.log 기록.

    Args:
        panel_idx: 패널 번호 (1-based).
        prompt_text: 프롬프트.
        ref_paths: REF 이미지 경로 목록.
        output_dir: 출력 디렉토리 (output/episodes/DATE/panels/).
        log_path: gemini_run.log 경로.

    Returns:
        저장된 PNG 경로 또는 None (3회 실패 시 fallback).
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"P{panel_idx}.png"
    start_ts = time.monotonic()

    log_record: dict = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "panel": panel_idx,
        "model": _MODEL,
        "ref_images": [str(p) for p in ref_paths],
        "status": "unknown",
        "prompt_tokens": 0,
        "output_tokens": 0,
        "latency_sec": 0.0,
        "cost_usd": 0.0,
        "output": None,
    }

    try:
        client = _get_client()
        image_bytes = _generate_one(client, prompt_text, ref_paths)

        latency = round(time.monotonic() - start_ts, 2)

        # usage_metadata에서 토큰 수 추출 (SDK 버전마다 구조 다를 수 있음)
        prompt_tokens = 0
        output_tokens = 0
        cost_usd = _calc_cost(prompt_tokens, output_tokens)

        output_path.write_bytes(image_bytes)

        log_record.update({
            "status": "success",
            "prompt_tokens": prompt_tokens,
            "output_tokens": output_tokens,
            "latency_sec": latency,
            "cost_usd": cost_usd,
            "output": str(output_path),
        })
        _write_jsonl_log(log_path, log_record)

        logger.info(
            "[gemini] 패널 P%d 생성 완료 (%.2fs, $%.4f)",
            panel_idx, latency, cost_usd
        )
        return output_path

    except Exception as exc:
        latency = round(time.monotonic() - start_ts, 2)
        log_record.update({
            "status": "failed",
            "latency_sec": latency,
            "error": str(exc),
        })
        _write_jsonl_log(log_path, log_record)

        logger.error("[gemini] 패널 P%d 생성 실패 → text_card fallback: %s", panel_idx, exc)
        return None  # 상위에서 text_card fallback 처리


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

        path = generate_panel(
            panel_idx=idx,
            prompt_text=prompt,
            ref_paths=refs,
            output_dir=output_dir,
            log_path=log_path,
        )
        results.append(path)

    success_count = sum(1 for p in results if p is not None)
    logger.info(
        "[gemini] 에피소드 생성 완료: %d/%d 패널 성공 (cost=$%.4f)",
        success_count, len(results), total_cost
    )
    return results, total_cost
