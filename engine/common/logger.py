"""
engine/common/logger.py
ICG 파이프라인 StepLogger.

기능:
- 단계별(STEP) 구조화 로그를 output/episodes/{date}/run.log (JSONL) 파일에 기록.
- 동시에 Supabase icg.run_logs 테이블에 INSERT.
- Supabase 실패 시 파일 기록만 유지 (degraded mode), 파이프라인 중단하지 않음.

보안:
- GEMINI_API_SUB_PAY_KEY (AIza...) 패턴 → ***REDACTED***
- SUPABASE_KEY (eyJ...) 패턴 → ***REDACTED***
- Anthropic key (sk-ant-...) 패턴 → ***REDACTED***
- PII (email, phone) 패턴 → ***PII***
"""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ── 마스킹 패턴 ─────────────────────────────────────────────────────────────
_MASK_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # Google API key (AIza로 시작, 30자 이상 — 실제 길이 변동 대응)
    (re.compile(r"AIza[0-9A-Za-z\-_]{30,}"), "***REDACTED***"),
    # Supabase service_role / JWT (eyJ로 시작하는 긴 토큰)
    (re.compile(r"eyJ[A-Za-z0-9\-_=.]{40,}"), "***REDACTED***"),
    # Anthropic API key
    (re.compile(r"sk-ant-[A-Za-z0-9\-_]{20,}"), "***REDACTED***"),
    # OpenAI style (혹시 모를 혼입 방지)
    (re.compile(r"sk-[A-Za-z0-9]{40,}"), "***REDACTED***"),
    # Notion token
    (re.compile(r"ntn_[A-Za-z0-9]{40,}"), "***REDACTED***"),
    # Email (PII)
    (re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"), "***PII***"),
    # 한국 전화번호 (PII)
    (re.compile(r"01[016789]-?\d{3,4}-?\d{4}"), "***PII***"),
]


def mask_secret(text: str) -> str:
    """
    문자열에서 API key, JWT, PII 패턴을 탐지하여 ***REDACTED*** / ***PII*** 로 교체.

    Args:
        text: 마스킹 대상 문자열.

    Returns:
        민감 정보가 제거된 문자열.
    """
    for pattern, replacement in _MASK_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


class StepLogger:
    """
    ICG 파이프라인 단계 로거.

    - 파일 기록: output/episodes/{date}/run.log (JSONL 형식)
    - Supabase 기록: icg.run_logs (실패 시 degraded mode)
    - 모든 출력값에 마스킹 자동 적용.

    Usage:
        logger = StepLogger(run_id="run-2026-04-14", episode_date="2026-04-14")
        logger.info("STEP_2", "daily_snapshots upsert 완료")
        with logger.timed("STEP_3"):
            ...  # 실행 시간 자동 기록
    """

    def __init__(
        self,
        run_id: str,
        episode_date: str,
        output_dir: Path | None = None,
        supabase_enabled: bool = True,
    ) -> None:
        self.run_id = run_id
        self.episode_date = episode_date
        self.supabase_enabled = supabase_enabled
        self._degraded = False  # Supabase 실패 시 True

        # 파일 경로 설정
        if output_dir is None:
            output_dir = Path("output") / "episodes" / episode_date
        output_dir.mkdir(parents=True, exist_ok=True)
        self._log_path = output_dir / "run.log"

        self._std_logger = logging.getLogger(f"icg.{run_id}")

    # ── 공개 API ─────────────────────────────────────────────────────────────

    def info(self, step: str, message: str, meta: dict | None = None) -> None:
        """INFO 수준 스텝 로그 기록."""
        self._write("info", step, message, meta=meta)

    def warning(self, step: str, message: str, meta: dict | None = None) -> None:
        """WARNING 수준 스텝 로그 기록."""
        self._write("warning", step, message, meta=meta)

    def error(
        self,
        step: str,
        message: str,
        *,
        exc: BaseException | None = None,
        meta: dict | None = None,
    ) -> None:
        """ERROR 수준 스텝 로그 기록."""
        if exc is not None:
            extra = {"exception_type": type(exc).__name__, "exception": str(exc)}
            meta = {**(meta or {}), **extra}
        self._write("error", step, message, meta=meta)

    def step_start(self, step: str, message: str = "") -> float:
        """스텝 시작 기록. 시작 타임스탬프(monotonic) 반환."""
        self.info(step, f"START {message}".strip())
        return time.monotonic()

    def step_done(
        self, step: str, start_ts: float, message: str = "", meta: dict | None = None
    ) -> int:
        """스텝 완료 기록. duration_ms 반환."""
        duration_ms = int((time.monotonic() - start_ts) * 1000)
        self._write("info", step, f"DONE {message}".strip(), duration_ms=duration_ms, meta=meta)
        return duration_ms

    def step_fail(
        self,
        step: str,
        start_ts: float,
        exc: BaseException,
        meta: dict | None = None,
    ) -> None:
        """스텝 실패 기록 + Supabase run_logs에 status=fail 기록."""
        duration_ms = int((time.monotonic() - start_ts) * 1000)
        self.error(
            step,
            f"FAILED: {type(exc).__name__}: {exc}",
            exc=exc,
            meta=meta,
        )
        self._write_supabase(
            step=step,
            status="fail",
            duration_ms=duration_ms,
            message=mask_secret(f"{type(exc).__name__}: {exc}"),
        )

    # ── 내부 구현 ─────────────────────────────────────────────────────────────

    def _write(
        self,
        level: str,
        step: str,
        message: str,
        *,
        duration_ms: int | None = None,
        meta: dict | None = None,
    ) -> None:
        """파일 + Supabase에 로그 레코드 기록."""
        safe_message = mask_secret(message)
        safe_meta = _mask_dict(meta) if meta else {}

        record: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "run_id": self.run_id,
            "episode_date": self.episode_date,
            "step": step,
            "level": level,
            "message": safe_message,
        }
        if duration_ms is not None:
            record["duration_ms"] = duration_ms
        if safe_meta:
            record["meta"] = safe_meta

        # 파일 기록 (JSONL)
        try:
            with self._log_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError as exc:
            self._std_logger.error("[StepLogger] 파일 기록 실패: %s", exc)

        # 표준 logging
        log_fn = getattr(self._std_logger, level, self._std_logger.info)
        log_fn("[%s] %s", step, safe_message)

        # Supabase 기록 (info 이상만, degraded가 아닌 경우)
        if level in ("info", "warning", "error") and not self._degraded:
            status = "ok" if level == "info" else level
            self._write_supabase(
                step=step,
                status=status,
                duration_ms=duration_ms,
                message=safe_message,
                meta=safe_meta or None,
            )

    def _write_supabase(
        self,
        step: str,
        status: str,
        *,
        duration_ms: int | None = None,
        message: str | None = None,
        meta: dict | None = None,
    ) -> None:
        """Supabase icg.run_logs INSERT. 실패 시 degraded mode 전환."""
        if not self.supabase_enabled or self._degraded:
            return

        try:
            # 순환 import 방지를 위해 지연 import
            from engine.common.supabase_client import insert_run_log

            insert_run_log(
                run_id=self.run_id,
                step=step,
                status=status,
                episode_date=self.episode_date,
                duration_ms=duration_ms,
                message=message,
                meta=meta,
            )
        except Exception as exc:
            # Supabase 실패 → degraded mode 전환, 파일 기록 계속
            self._degraded = True
            self._std_logger.warning("[StepLogger] Supabase 기록 실패 → degraded mode: %s", exc)


def _mask_dict(data: dict) -> dict:
    """dict의 모든 string 값에 마스킹 적용 (재귀)."""
    result: dict = {}
    for k, v in data.items():
        if isinstance(v, str):
            result[k] = mask_secret(v)
        elif isinstance(v, dict):
            result[k] = _mask_dict(v)
        else:
            result[k] = v
    return result


def get_run_id(episode_date: str) -> str:
    """
    run_id 생성 헬퍼.
    형식: ICG-{episode_date}-{timestamp_ms}
    """
    ts = int(time.time() * 1000)
    return f"ICG-{episode_date}-{ts}"
