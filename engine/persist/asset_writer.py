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


def get_episode_by_no(episode_date: str, episode_no: int) -> dict | None:
    """episode_date + episode_no 기준으로 episode_assets row 조회."""
    from engine.common.supabase_client import icg_table

    rows = (
        icg_table("episode_assets")
        .select("*")
        .eq("episode_date", episode_date)
        .eq("episode_no", episode_no)
        .limit(1)
        .execute()
    )
    data = getattr(rows, "data", None)
    if not data:
        return None
    return data[0]


def patch_by_episode(episode_date: str, episode_no: int, data: dict) -> None:
    """episode_date + episode_no 기준으로 episode_assets 특정 컬럼만 UPDATE.

    Resume/Publish처럼 episode_id 기반으로 대상을 확정한 뒤에는 event_type보다
    episode_no를 사용해야 같은 날짜 동일 event_type row 덮어쓰기 위험을 줄일 수 있다.
    """
    from engine.common.supabase_client import icg_table

    icg_table("episode_assets").update(data).eq("episode_date", episode_date).eq(
        "episode_no", episode_no
    ).execute()

    logger.info(
        "[asset_writer] patch_by_episode date=%s no=%s fields=%s",
        episode_date,
        episode_no,
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


def _top_candidate(selection: dict, faction: str) -> dict:
    """Return highest-ranked/highest-score candidate for a faction."""
    candidates = [
        c for c in selection.get("all_candidates", [])
        if isinstance(c, dict) and c.get("faction") == faction
    ]
    if not candidates:
        return {}
    return sorted(
        candidates,
        key=lambda c: (
            c.get("rank") is None,
            c.get("rank") or 9999,
            -(c.get("score") or 0),
        ),
    )[0]


def character_selection_summary(ctx: dict) -> dict:
    """Build reporting-safe daily_analysis summary fields from ctx.character_selection."""
    selection = ctx.get("character_selection") or {}
    if not isinstance(selection, dict) or not selection:
        return {
            "character_selection": {},
            "character_selector_version": None,
            "character_selector_mode": None,
            "selected_hero_id": None,
            "selected_villain_id": None,
            "selected_villain_ids": [],
            "support_heroes_json": [],
            "neutral_guests_json": [],
            "top_hero_score": None,
            "top_villain_score": None,
            "neutral_guest_count": 0,
            "character_selection_reason": None,
        }

    version = selection.get("version")
    top_hero = _top_candidate(selection, "HERO")
    top_villain = _top_candidate(selection, "VILLAIN")
    neutral_guests = selection.get("neutral_guests") or []
    if not isinstance(neutral_guests, list):
        neutral_guests = []

    return {
        "character_selection": selection,
        "character_selector_version": version,
        "character_selector_mode": (
            "scored" if version == "character-appearance-v2" else "legacy-trace"
        ),
        "selected_hero_id": selection.get("primary_hero"),
        "selected_villain_id": selection.get("primary_villain"),
        "selected_villain_ids": selection.get("villains") or (
            [selection.get("primary_villain")] if selection.get("primary_villain") else []
        ),
        "support_heroes_json": selection.get("support_heroes") or [],
        "neutral_guests_json": neutral_guests,
        "top_hero_score": top_hero.get("score"),
        "top_villain_score": top_villain.get("score"),
        "neutral_guest_count": len(neutral_guests),
        "character_selection_reason": selection.get("selection_reason"),
    }


def character_selection_candidate_rows(
    episode_date: str,
    event_type: str,
    ctx: dict,
) -> list[dict]:
    """Flatten ctx.character_selection.all_candidates into candidate fact rows."""
    selection = ctx.get("character_selection") or {}
    if not isinstance(selection, dict):
        return []

    selected_ids = {selection.get("primary_hero"), selection.get("primary_villain")}
    selected_ids.update(selection.get("support_heroes") or [])
    selected_ids.update(selection.get("support_villains") or [])
    selected_ids.update(selection.get("villains") or [])
    selected_ids.discard(None)

    rows: list[dict] = []
    for candidate in selection.get("all_candidates") or []:
        if not isinstance(candidate, dict) or not candidate.get("char_id"):
            continue
        rows.append({
            "analysis_date": episode_date,
            "event_type": event_type,
            "scenario_type": selection.get("scenario_type") or ctx.get("scenario_type"),
            "risk_level": selection.get("risk_level") or ctx.get("risk_level"),
            "selector_version": selection.get("version"),
            "char_id": candidate.get("char_id"),
            "faction": candidate.get("faction"),
            "role": candidate.get("role"),
            "appear": bool(candidate.get("appear")),
            "selected": candidate.get("char_id") in selected_ids,
            "score": candidate.get("score") or 0,
            "threshold": candidate.get("threshold") or 0,
            "rank": candidate.get("rank"),
            "reasons": candidate.get("reasons") or [],
            "score_breakdown": candidate.get("score_breakdown") or {},
            "metrics_used": candidate.get("metrics_used") or {},
        })
    return rows


def save_character_selection_candidates(
    episode_date: str,
    event_type: str,
    ctx: dict,
) -> None:
    """Persist candidate-level selection facts when the optional table exists."""
    rows = character_selection_candidate_rows(episode_date, event_type, ctx)
    if not rows:
        return

    from engine.common.supabase_client import icg_table

    icg_table("character_selection_candidates").upsert(
        rows,
        on_conflict="analysis_date,event_type,char_id,faction",
    ).execute()
    logger.info(
        "[asset_writer] character_selection_candidates 저장 완료 date=%s rows=%d",
        episode_date,
        len(rows),
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

    payload = {"analysis_ctx_json": ctx}
    payload.update(character_selection_summary(ctx))

    try:
        icg_table("daily_analysis").update(payload).eq(
            "analysis_date", episode_date
        ).execute()
    except Exception as exc:
        # Backward compatibility: allow code rollout before the observability migration.
        logger.warning(
            "[asset_writer] character_selection summary 저장 실패 — "
            "analysis_ctx_json only fallback: %s",
            exc,
        )
        icg_table("daily_analysis").update({"analysis_ctx_json": ctx}).eq(
            "analysis_date", episode_date
        ).execute()

    try:
        save_character_selection_candidates(episode_date, event_type, ctx)
    except Exception as exc:
        logger.warning(
            "[asset_writer] character_selection_candidates 저장 실패 (진행): %s", exc
        )

    logger.info(
        "[asset_writer] analysis_ctx_json 저장 완료 date=%s type=%s character_selection=%s",
        episode_date,
        event_type,
        bool(ctx.get("character_selection")),
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


def save_narrative_script(episode_date: str, script_dict: dict) -> None:
    """
    step_narrative 결과 script_dict를 daily_analysis.narrative_script_json에 저장.

    Hybrid 설계: persist/image stage 독립 실행 시 script_json 복원 소스.
    daily_analysis는 analysis stage에서 이미 행이 존재하므로 UPDATE만 수행.
    """
    from engine.common.supabase_client import icg_table

    icg_table("daily_analysis").update(
        {"narrative_script_json": script_dict}
    ).eq("analysis_date", episode_date).execute()

    logger.info("[asset_writer] narrative_script_json 저장 완료 date=%s", episode_date)


def load_narrative_script(episode_date: str) -> dict | None:
    """
    daily_analysis.narrative_script_json에서 script_dict 복원.

    persist/image stage가 별도 프로세스로 실행될 때 호출.

    Returns:
        script_dict 또는 None (narrative 미실행).
    """
    from engine.common.supabase_client import icg_table

    rows = (
        icg_table("daily_analysis")
        .select("narrative_script_json")
        .eq("analysis_date", episode_date)
        .limit(1)
        .execute()
    )
    if not rows.data:
        logger.warning(
            "[asset_writer] load_narrative_script: date=%s daily_analysis 행 없음 "
            "— analysis stage를 먼저 실행하세요.",
            episode_date,
        )
        return None

    script = rows.data[0].get("narrative_script_json")
    if not script:
        logger.warning(
            "[asset_writer] load_narrative_script: date=%s narrative_script_json 없음 "
            "— narrative stage를 먼저 실행하세요.",
            episode_date,
        )
        return None

    logger.info("[asset_writer] narrative_script_json 복원 완료 date=%s", episode_date)
    return script
