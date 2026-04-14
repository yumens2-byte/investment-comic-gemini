"""
engine/publish/history_writer.py
발행 이력을 icg.published_comics + icg.episode_assets에 기록.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


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
) -> None:
    """
    발행 완료 후 이력 기록.

    1. icg.published_comics INSERT
    2. icg.episode_assets.status = published 업데이트
    """
    from engine.common.supabase_client import icg_table
    from engine.persist.asset_writer import upsert as asset_upsert

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
    except Exception as exc:
        logger.warning("[history_writer] published_comics 기록 실패: %s", exc)

    # 2. episode_assets status → published
    try:
        asset_upsert(
            episode_date,
            event_type,
            {
                "status": "published",
                "total_runtime_sec": runtime_sec,
            },
        )
        logger.info("[history_writer] episode_assets status=published")
    except Exception as exc:
        logger.warning("[history_writer] episode_assets 업데이트 실패: %s", exc)
