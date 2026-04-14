"""
engine/analysis/reader.py
icg.daily_snapshots에서 최근 N일 데이터 로드.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def get_latest(n: int = 2) -> list[dict]:
    """
    icg.daily_snapshots에서 최신 N개 row를 내림차순으로 반환.

    Returns:
        row 딕셔너리 목록 (최신 → 과거 순서).
    """
    from engine.common.supabase_client import icg_table

    rows = (
        icg_table("daily_snapshots")
        .select("*")
        .order("snapshot_date", desc=True)
        .limit(n)
        .execute()
    )
    data = rows.data or []
    logger.info("[reader] daily_snapshots %d행 로드", len(data))
    return data


def get_by_date(snapshot_date: str) -> dict | None:
    """특정 날짜 snapshot row 반환."""
    from engine.common.supabase_client import icg_table

    rows = (
        icg_table("daily_snapshots")
        .select("*")
        .eq("snapshot_date", snapshot_date)
        .limit(1)
        .execute()
    )
    return rows.data[0] if rows.data else None
