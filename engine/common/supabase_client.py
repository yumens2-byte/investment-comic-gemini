"""
engine/common/supabase_client.py
Supabase 클라이언트 싱글톤.

원칙:
- service_role key 사용 (RLS 우회). 절대 클라이언트/외부에 노출 금지.
- schema("icg") 체인으로 ICG 전용 스키마 접근.
- 모든 Python 서버사이드 전용 — 브라우저/프론트엔드 경유 금지.
- Supabase 실패 시 StepLogger degraded mode (파일만 기록) 전환.
"""

from __future__ import annotations

import logging
import os

from supabase import Client, create_client

logger = logging.getLogger(__name__)

_client: Client | None = None
_schema: str = "icg"


def get_client() -> Client:
    """
    Supabase Client 싱글톤 반환.

    최초 호출 시 환경변수 SUPABASE_URL + SUPABASE_KEY 로 초기화.
    이후 동일 인스턴스 재사용.

    Returns:
        초기화된 Supabase Client.

    Raises:
        RuntimeError: 필수 환경변수 누락 시.
    """
    global _client
    if _client is None:
        url = os.environ.get("SUPABASE_URL", "")
        key = os.environ.get("SUPABASE_KEY", "")

        if not url or not key:
            raise RuntimeError(
                "SUPABASE_URL 또는 SUPABASE_KEY 환경변수 누락. "
                "GitHub Secrets 또는 .env 파일을 확인하라."
            )

        # ⚠️ service_role key는 로그에 절대 출력 금지
        logger.debug("[Supabase] 클라이언트 초기화 (url=%s)", url)
        _client = create_client(url, key)

    return _client


def get_schema() -> str:
    """현재 ICG 스키마 이름 반환 (기본: 'icg')."""
    return os.environ.get("SUPABASE_SCHEMA", _schema)


def icg_table(table_name: str):
    """
    icg 스키마의 테이블에 대한 PostgREST 쿼리 빌더를 반환하는 헬퍼.

    Usage:
        icg_table("daily_snapshots").upsert({...}).execute()
        icg_table("episode_assets").select("*").eq("status", "draft").execute()

    Args:
        table_name: icg 스키마 내 테이블명 (예: "daily_snapshots").

    Returns:
        supabase-py PostgREST 쿼리 빌더.
    """
    schema = get_schema()
    return get_client().schema(schema).table(table_name)


def upsert_snapshot(date: str, data: dict) -> None:
    """
    icg.daily_snapshots upsert 헬퍼.
    UNIQUE KEY: snapshot_date.
    """
    icg_table("daily_snapshots").upsert(
        {"snapshot_date": date, **data},
        on_conflict="snapshot_date",
    ).execute()
    logger.info("[Supabase] daily_snapshots upserted date=%s", date)


def upsert_analysis(date: str, data: dict) -> None:
    """
    icg.daily_analysis upsert 헬퍼.
    UNIQUE KEY: analysis_date.
    """
    icg_table("daily_analysis").upsert(
        {"analysis_date": date, **data},
        on_conflict="analysis_date",
    ).execute()
    logger.info("[Supabase] daily_analysis upserted date=%s", date)


def upsert_episode_assets(episode_date: str, event_type: str, data: dict) -> None:
    """
    icg.episode_assets upsert 헬퍼.
    UNIQUE KEY: (episode_date, event_type).
    """
    icg_table("episode_assets").upsert(
        {"episode_date": episode_date, "event_type": event_type, **data},
        on_conflict="episode_date,event_type",
    ).execute()
    logger.info(
        "[Supabase] episode_assets upserted date=%s event_type=%s",
        episode_date,
        event_type,
    )


def insert_run_log(
    run_id: str,
    step: str,
    status: str,
    *,
    episode_date: str | None = None,
    duration_ms: int | None = None,
    message: str | None = None,
    meta: dict | None = None,
) -> None:
    """
    icg.run_logs INSERT 헬퍼.
    Supabase 실패 시 WARNING 로그만 기록하고 파이프라인 계속 진행 (degraded mode).
    """
    try:
        icg_table("run_logs").insert(
            {
                "run_id": run_id,
                "episode_date": episode_date,
                "step": step,
                "status": status,
                "duration_ms": duration_ms,
                "message": message,
                "meta": meta or {},
            }
        ).execute()
    except Exception as exc:
        # run_logs 실패는 파이프라인 중단 사유가 아님 → degraded mode
        logger.warning("[Supabase] run_logs 기록 실패 (degraded): %s", exc)


def reset_client_for_test() -> None:
    """테스트 전용: 싱글톤 초기화 (환경변수 변경 후 재초기화용)."""
    global _client
    _client = None
