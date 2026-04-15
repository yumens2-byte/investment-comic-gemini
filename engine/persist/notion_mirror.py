"""
engine/persist/notion_mirror.py
Notion ICG Episode Tracker에 에피소드 메타데이터 미러링.

원칙 (doc 16b):
  - 전체 JSON은 Supabase에만.
  - Notion에는 title, status, cost, count 메타만.
  - Data Source ID: 환경변수 NOTION_TRACKER_DS 참조
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

_TRACKER_DS_ID = os.environ.get("NOTION_TRACKER_DS", "")

# Notion Tracker의 Villain 표기 ↔ char_id 매핑
_VILLAIN_LABELS: dict[str, str] = {
    "CHAR_VILLAIN_001": "Debt Titan",
    "CHAR_VILLAIN_002": "Oil Shock Titan",
    "CHAR_VILLAIN_003": "Liquidity Leviathan",
    "CHAR_VILLAIN_004": "Volatility Hydra",
    "CHAR_VILLAIN_005": "Algorithm Reaper",
    "CHAR_VILLAIN_006": "War Dominion",
}

# Notion Tracker의 Hero 표기 ↔ char_id 매핑
_HERO_LABELS: dict[str, str] = {
    "CHAR_HERO_001": "EDT",
    "CHAR_HERO_002": "Iron Nuna",
    "CHAR_HERO_003": "Leverage",
    "CHAR_HERO_004": "Futures Girl",
    "CHAR_HERO_005": "Gold Bond",
}

# Supabase status → Notion Status 매핑
_STATUS_MAP: dict[str, str] = {
    "draft": "Draft",
    "narrative_done": "Narrative Done",
    "image_generated": "Image Generated",
    "dialog_pending": "Dialog Pending",
    "dialog_confirmed": "Dialog Confirmed",
    "assembled": "Assembled",
    "published": "Published",
    "failed": "Failed",
    "aborted": "Aborted",
}


def create_or_update(
    episode_date: str,
    episode_id: str,
    title: str,
    event_type: str,
    status: str,
    hero_id: str,
    villain_id: str,
    outcome: str,
    balance: int,
    panel_count: int = 0,
    claude_cost_usd: float = 0.0,
    gemini_cost_usd: float = 0.0,
    runtime_sec: float = 0.0,
    supabase_row_url: str = "",
    log_path: str = "",
) -> str | None:
    """
    Notion ICG Episode Tracker에 에피소드 페이지 생성.

    전체 JSON은 Supabase에만 저장하고, Notion에는 요약 메타만 기록.

    Args:
        episode_date: 'YYYY-MM-DD'.
        episode_id: 'ICG-YYYY-MM-DD-NNN'.
        title: 에피소드 제목.
        event_type: BATTLE / SHOCK 등.
        status: Supabase status (draft, narrative_done ...).
        hero_id: CHAR_HERO_00N.
        villain_id: CHAR_VILLAIN_00N.
        outcome: HERO_VICTORY 등.
        balance: 전투 balance 수치.
        panel_count: 생성된 패널 수.
        claude_cost_usd: Claude API 비용.
        gemini_cost_usd: Gemini API 비용.
        runtime_sec: 파이프라인 총 실행 시간.
        supabase_row_url: Supabase 대시보드 링크.
        log_path: run.log 경로.

    Returns:
        생성된 Notion 페이지 URL 또는 None (실패 시).
    """
    notion_token = os.environ.get("NOTION_API_KEY", "")
    if not notion_token:
        logger.warning("[notion_mirror] NOTION_API_KEY 없음 — 미러링 생략")
        return None

    try:
        from notion_client import Client

        client = Client(auth=notion_token)

        notion_status = _STATUS_MAP.get(status, "Draft")
        hero_label = _HERO_LABELS.get(hero_id, hero_id)
        villain_label = _VILLAIN_LABELS.get(villain_id, villain_id)

        properties = {
            "Title": {"title": [{"text": {"content": title}}]},
            "Episode ID": {"rich_text": [{"text": {"content": episode_id}}]},
            "Date": {"date": {"start": episode_date}},
            "Status": {"select": {"name": notion_status}},
            "Event Type": {"select": {"name": event_type}},
            "Hero": {"multi_select": [{"name": hero_label}]},
            "Villain": {"multi_select": [{"name": villain_label}]},
            "Outcome": {"select": {"name": outcome}},
            "Balance": {"number": balance},
            "Panel Count": {"number": panel_count},
            "Claude Cost": {"number": claude_cost_usd},
            "Gemini Cost": {"number": gemini_cost_usd},
            "Runtime (sec)": {"number": runtime_sec},
            "Log Path": {"rich_text": [{"text": {"content": log_path}}]},
        }

        if supabase_row_url:
            properties["Supabase Row"] = {"url": supabase_row_url}

        response = client.pages.create(
            parent={"database_id": _TRACKER_DS_ID},
            properties=properties,
        )

        page_url = response.get("url", "")
        logger.info("[notion_mirror] 페이지 생성 완료: %s", page_url)
        return page_url

    except Exception as exc:
        # Notion 실패는 파이프라인 중단 사유 아님
        logger.warning("[notion_mirror] 페이지 생성 실패 (영향 없음): %s", exc)
        return None


def update_status(
    page_id: str,
    status: str,
    extra_props: dict | None = None,
) -> None:
    """
    기존 Notion 페이지의 Status 업데이트.

    Args:
        page_id: Notion 페이지 ID.
        status: Supabase status 문자열.
        extra_props: 추가 업데이트할 properties.
    """
    notion_token = os.environ.get("NOTION_API_KEY", "")
    if not notion_token or not page_id:
        return

    try:
        from notion_client import Client

        client = Client(auth=notion_token)
        notion_status = _STATUS_MAP.get(status, "Draft")

        props = {"Status": {"select": {"name": notion_status}}}
        if extra_props:
            props.update(extra_props)

        client.pages.update(page_id=page_id, properties=props)
        logger.info(
            "[notion_mirror] 페이지 업데이트 page_id=%s status=%s", page_id[:8], notion_status
        )

    except Exception as exc:
        logger.warning("[notion_mirror] 페이지 업데이트 실패 (영향 없음): %s", exc)
