"""
engine/persist/asset_writer.py
icg.episode_assets UPSERT + Status State Machine.

State Machine (doc 16b):
  draft → narrative_done → image_generated → dialog_pending
        → dialog_confirmed → assembled → published
  + failed / aborted (어느 단계에서도 전환 가능)
"""

from __future__ import annotations

import logging

from engine.common.exceptions import InvalidStatusTransition

logger = logging.getLogger(__name__)

# ── 허용 상태 전환 테이블 ──────────────────────────────────────────────────────
_ALLOWED_TRANSITIONS: dict[str, list[str]] = {
    "draft": ["narrative_done", "failed", "aborted"],
    "narrative_done": ["image_generated", "failed", "aborted"],
    "image_generated": ["dialog_pending", "failed", "aborted"],
    "dialog_pending": ["dialog_confirmed", "aborted"],
    "dialog_confirmed": ["assembled", "failed", "aborted"],
    "assembled": ["published", "failed", "aborted"],
    "published": [],
    "failed": ["draft"],  # 재시도 허용
    "aborted": [],
}


def validate_transition(current: str, target: str) -> None:
    """
    status 전환 유효성 검증.

    Raises:
        InvalidStatusTransition: 허용되지 않은 전환 시.
    """
    allowed = _ALLOWED_TRANSITIONS.get(current, [])
    if target not in allowed:
        raise InvalidStatusTransition(current, target)


def upsert(
    episode_date: str,
    event_type: str,
    data: dict,
    *,
    expected_current_status: str | None = None,
) -> None:
    """
    icg.episode_assets UPSERT.

    Args:
        episode_date: 'YYYY-MM-DD'.
        event_type: 에피소드 타입 (예: 'BATTLE').
        data: 업데이트할 필드 딕셔너리.
        expected_current_status: 지정 시 status 전환 유효성 검증.

    Raises:
        InvalidStatusTransition: 허용되지 않은 status 전환 시.
    """
    from engine.common.supabase_client import icg_table

    new_status = data.get("status")

    # status 전환 검증 (expected_current_status 지정 시)
    if expected_current_status and new_status:
        validate_transition(expected_current_status, new_status)

    icg_table("episode_assets").upsert(
        {"episode_date": episode_date, "event_type": event_type, **data},
        on_conflict="episode_date,event_type",
    ).execute()

    logger.info(
        "[asset_writer] upsert date=%s type=%s status=%s",
        episode_date,
        event_type,
        new_status or "unchanged",
    )


def get_current_status(episode_date: str, event_type: str) -> str | None:
    """
    현재 episode_assets.status 조회.

    Returns:
        status 문자열 또는 None (행 없음).
    """
    from engine.common.supabase_client import icg_table

    rows = (
        icg_table("episode_assets")
        .select("status")
        .eq("episode_date", episode_date)
        .eq("event_type", event_type)
        .limit(1)
        .execute()
    )
    if not rows.data:
        return None
    return rows.data[0].get("status")


def get_episode(episode_date: str, event_type: str) -> dict | None:
    """
    episode_assets 전체 row 조회.

    Returns:
        row dict 또는 None.
    """
    from engine.common.supabase_client import icg_table

    rows = (
        icg_table("episode_assets")
        .select("*")
        .eq("episode_date", episode_date)
        .eq("event_type", event_type)
        .limit(1)
        .execute()
    )
    if not rows.data:
        return None
    return rows.data[0]


def patch(
    episode_date: str,
    event_type: str,
    data: dict,
) -> None:
    """
    icg.episode_assets 특정 컬럼만 UPDATE.
    upsert와 달리 기존 컬럼값을 보존.
    STEP 6처럼 일부 컬럼만 업데이트할 때 사용.

    Args:
        episode_date: 'YYYY-MM-DD'.
        event_type: 에피소드 타입.
        data: 업데이트할 필드만 포함한 딕셔너리.
    """
    from engine.common.supabase_client import icg_table

    icg_table("episode_assets").update(data).eq("episode_date", episode_date).eq(
        "event_type", event_type
    ).execute()

    logger.info(
        "[asset_writer] patch date=%s type=%s fields=%s",
        episode_date,
        event_type,
        list(data.keys()),
    )


def set_failed(episode_date: str, event_type: str, error_message: str) -> None:
    """
    episode_assets.status = 'failed' + error_message 업데이트.
    state machine 검증 없이 강제 전환.
    """
    from engine.common.supabase_client import icg_table

    icg_table("episode_assets").upsert(
        {
            "episode_date": episode_date,
            "event_type": event_type,
            "status": "failed",
            "error_message": error_message,
        },
        on_conflict="episode_date,event_type",
    ).execute()

    logger.error(
        "[asset_writer] status=failed date=%s type=%s error=%s",
        episode_date,
        event_type,
        error_message[:200],
    )


def save_analysis_ctx(episode_date: str, event_type: str, ctx: dict) -> None:
    """
    step_analysis 결과 ctx를 daily_analysis.analysis_ctx_json에 저장.

    Hybrid 설계: daily_analysis는 analysis stage에서 이미 UPSERT 완료이므로
    행이 반드시 존재 → NOT NULL 제약 충돌 없이 안전하게 UPDATE 가능.

    Args:
        episode_date: 'YYYY-MM-DD'.
        event_type: 에피소드 타입 (예: 'NORMAL'). 로그용.
        ctx: step_analysis() 반환값.
    """
    from engine.common.supabase_client import icg_table

    icg_table("daily_analysis").update(
        {"analysis_ctx_json": ctx}
    ).eq("analysis_date", episode_date).execute()

    logger.info(
        "[asset_writer] analysis_ctx_json 저장 완료 date=%s type=%s",
        episode_date,
        event_type,
    )


def load_analysis_ctx(episode_date: str) -> dict | None:
    """
    daily_analysis.analysis_ctx_json에서 ctx 복원.

    narrative/persist/image stage가 별도 프로세스로 실행될 때 호출.

    Args:
        episode_date: 'YYYY-MM-DD'.

    Returns:
        ctx dict 또는 None (analysis 미실행).
    """
    from engine.common.supabase_client import icg_table

    rows = (
        icg_table("daily_analysis")
        .select("analysis_ctx_json")
        .eq("analysis_date", episode_date)
        .limit(1)
        .execute()
    )
    if not rows.data:
        logger.warning(
            "[asset_writer] load_analysis_ctx: date=%s daily_analysis 행 없음 "
            "— analysis stage를 먼저 실행하세요.",
            episode_date,
        )
        return None

    ctx = rows.data[0].get("analysis_ctx_json")
    if not ctx:
        logger.warning(
            "[asset_writer] load_analysis_ctx: date=%s analysis_ctx_json 없음 "
            "— analysis stage를 먼저 실행하세요.",
            episode_date,
        )
        return None

    logger.info("[asset_writer] analysis_ctx_json 복원 완료 date=%s", episode_date)
    return ctx
