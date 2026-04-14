"""
engine/common/retry.py
ICG 파이프라인 공통 재시도 데코레이터.

원칙:
- 모든 외부 API 호출은 이 모듈의 retry 데코레이터를 통과한다.
- 기본값: 최대 3회, 지수 백오프(2s → 4s → 8s), 최대 30s 대기.
- 재시도 이유(exception type, attempt)는 StepLogger 경유로 기록한다.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, TypeVar

from tenacity import (
    RetryCallState,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])


def _log_retry(retry_state: RetryCallState) -> None:
    """재시도 시 로그 출력 콜백."""
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    logger.warning(
        "[Retry] attempt=%d fn=%s exception=%s",
        retry_state.attempt_number,
        retry_state.fn.__name__ if retry_state.fn else "unknown",
        type(exc).__name__ if exc else "unknown",
    )


def api_retry(
    *,
    max_attempts: int = 3,
    min_wait: float = 2.0,
    max_wait: float = 30.0,
    reraise: bool = True,
    exceptions: tuple[type[BaseException], ...] = (Exception,),
) -> Callable[[F], F]:
    """
    외부 API 호출용 재시도 데코레이터.

    Args:
        max_attempts: 최대 시도 횟수 (기본 3).
        min_wait: 첫 대기 초 (기본 2s).
        max_wait: 최대 대기 초 (기본 30s).
        reraise: 최종 실패 시 예외 재발생 여부 (기본 True).
        exceptions: 재시도 트리거 예외 타입 튜플 (기본 모든 Exception).

    Usage:
        @api_retry()
        def call_fred_api(series_id: str) -> dict:
            ...

        @api_retry(max_attempts=2, exceptions=(requests.Timeout,))
        def call_lunar_crush() -> dict:
            ...
    """
    return retry(
        stop=stop_after_attempt(max_attempts),
        wait=wait_exponential(multiplier=1, min=min_wait, max=max_wait),
        retry=retry_if_exception_type(exceptions),
        after=_log_retry,
        reraise=reraise,
    )


def narrative_retry(
    *,
    max_attempts: int = 2,
    min_wait: float = 3.0,
    max_wait: float = 10.0,
) -> Callable[[F], F]:
    """
    Claude Narrative 생성용 재시도 데코레이터.
    최대 2회 시도 (doc 16a: 검증 실패 시 최대 2회 재전송).
    """
    return api_retry(
        max_attempts=max_attempts,
        min_wait=min_wait,
        max_wait=max_wait,
    )


def image_retry(
    *,
    max_attempts: int = 3,
    min_wait: float = 5.0,
    max_wait: float = 30.0,
) -> Callable[[F], F]:
    """
    Gemini 이미지 생성용 재시도 데코레이터.
    패널별 3회 재시도 후 fallback (doc 00 SECTION 4).
    """
    return api_retry(
        max_attempts=max_attempts,
        min_wait=min_wait,
        max_wait=max_wait,
    )
