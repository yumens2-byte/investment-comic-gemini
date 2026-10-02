"""
engine/publish/history_writer.py
발행 이력을 icg.published_comics + icg.episode_assets에 기록.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def _record_code_sha(episode_date: str, episode_no: int) -> None:
    """Best-effort evidence for the scheduled-publish code guard; never fails a delivery."""
    import os
    import re

    sha = os.environ.get("GITHUB_SHA", "")
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        return
    try:
        from engine.common.supabase_client import icg_table

        icg_table("published_comics").update({"code_sha": sha}).eq(
            "publish_date", episode_date).eq("episode_no", episode_no).execute()
    except Exception as exc:  # column may not exist before the migration is applied
        logger.warning("[history_writer] code_sha 기록 생략: %s", type(exc).__name__)


def record_publish(
    episode_date: str,
    episode_id: str,
    event_type: str,
    tweet_ids: list[str],
    telegram_sent: bool,
    slide_count: int,
    gemini_cost_usd: float,
    claude_cost_usd: float,
    runtime_sec: float,
    *,
    state_candidate: dict | None = None,
    telegram_receipts: dict | None = None,
) -> None:
    """
    발행 완료 후 이력 기록.

    1. icg.published_comics INSERT
    2. icg.episode_assets.status = published 업데이트
    """
    from engine.common.supabase_client import icg_table
    from engine.persist.asset_writer import patch_by_episode as asset_patch

    if not tweet_ids and not telegram_sent:
        raise ValueError("cannot record publication without a successful channel")

    if state_candidate is not None:
        from engine.common.supabase_client import get_client, get_schema

        if telegram_sent and not telegram_receipts:
            raise ValueError("Telegram delivery receipt required")
        receipt = get_client().schema(get_schema()).rpc("finalize_episode_publication", {
            "p_date": episode_date, "p_no": int(episode_id.split("-")[-1]),
            "p_candidate": state_candidate, "p_tweet_ids": tweet_ids,
            "p_telegram": telegram_receipts or {}, "p_slide_count": slide_count,
            "p_cost": round(gemini_cost_usd + claude_cost_usd, 6), "p_runtime": runtime_sec,
        }).execute().data
        if not isinstance(receipt, dict) or receipt.get("committed") is not True:
            raise RuntimeError("publication state commit unconfirmed; reconcile without resending")
        _record_code_sha(episode_date, int(episode_id.split("-")[-1]))
        return

    # 1. published_comics 기록
    try:
        icg_table("published_comics").insert(
            {
                "publish_date": episode_date,
                "comic_type": event_type,
                "episode_no": int(episode_id.split("-")[-1]),
                "risk_level": "MEDIUM",
                "tweet_id": tweet_ids[0] if tweet_ids else None,
                "cut_count": slide_count,
                "cost_usd": round(gemini_cost_usd + claude_cost_usd, 6),
                "status": "published",
            }
        ).execute()
        logger.info("[history_writer] published_comics 기록 완료: %s", episode_id)
        _record_code_sha(episode_date, int(episode_id.split("-")[-1]))
    except Exception as exc:
        logger.error("[history_writer] published_comics 기록 실패: %s", exc)
        raise

    # 2. episode_assets status → published (UPDATE only, script_json 같은 NOT NULL 필드 보존)
    try:
        asset_patch(
            episode_date,
            int(episode_id.split("-")[-1]),
            {
                "status": "published",
                "total_runtime_sec": runtime_sec,
            },
        )
        logger.info("[history_writer] episode_assets status=published")
    except Exception as exc:
        logger.error("[history_writer] episode_assets 업데이트 실패: %s", exc)
        raise
