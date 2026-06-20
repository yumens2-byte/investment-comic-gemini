"""
engine/data/feargreed_fetcher.py
Fear & Greed Index 수집.

엔드포인트: alternative.me 공개 API (무료 / 인증 불필요).
  기존 CNN API (production.dataviz.cnn.io) 418 봇 차단으로 교체.
  2026-05-02 교체.

실패 시 None 반환 (파이프라인 중단 안 함).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import requests

from engine.common.retry import api_retry

logger = logging.getLogger(__name__)

_FNG_URL = "https://api.alternative.me/fng/?limit=1"
_CACHE_KEY = "feargreed:alternative_me:latest"
_TTL_HOURS = 12

_LABEL_MAP = {
    "Extreme Fear": "Extreme Fear",
    "Fear": "Fear",
    "Neutral": "Neutral",
    "Greed": "Greed",
    "Extreme Greed": "Extreme Greed",
}


def _get_cache(*, allow_stale: bool = False) -> dict | None:
    """Return fresh or stale Fear & Greed cache from icg.api_cache."""
    try:
        from engine.common.supabase_client import icg_table

        query = icg_table("api_cache").select("value,expires_at,created_at").eq(
            "cache_key", _CACHE_KEY
        )
        if allow_stale:
            query = query.order("created_at", desc=True).limit(1)
        rows = query.execute()
        if not rows.data:
            return None

        row = rows.data[0]
        if not allow_stale:
            expires_at_str = row.get("expires_at", "")
            expires_at = datetime.fromisoformat(expires_at_str.replace("Z", "+00:00"))
            if datetime.now(timezone.utc) >= expires_at:
                return None
            logger.info("[F&G] 캐시 HIT (expires=%s)", expires_at_str[:19])
        else:
            logger.warning("[F&G] stale 캐시 fallback 사용")
        return row.get("value")
    except Exception as exc:
        logger.warning("[F&G] 캐시 조회 실패: %s", exc)
        return None


def _save_cache(parsed: dict) -> None:
    """Persist parsed Fear & Greed payload for fresh/stale fallback."""
    try:
        from engine.common.supabase_client import icg_table

        expires_at = (datetime.now(timezone.utc) + timedelta(hours=_TTL_HOURS)).isoformat()
        icg_table("api_cache").upsert(
            {
                "cache_key": _CACHE_KEY,
                "value": {**parsed, "fetched_at": datetime.now(timezone.utc).isoformat()},
                "source": "alternative.me",
                "expires_at": expires_at,
            },
            on_conflict="cache_key",
        ).execute()
        logger.info("[F&G] 캐시 저장 완료 (TTL=%dh)", _TTL_HOURS)
    except Exception as exc:
        logger.warning("[F&G] 캐시 저장 실패 (영향 없음): %s", exc)


@api_retry(max_attempts=3, min_wait=2.0, max_wait=15.0)
def _call_api() -> dict:
    """alternative.me F&G API 호출."""
    resp = requests.get(
        _FNG_URL,
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def fetch_all(target_date: str | None = None) -> dict[str, int | str | None]:
    """
    Fear & Greed 지수 수집 (alternative.me).

    응답 구조:
        {
            "data": [
                {
                    "value": "40",
                    "value_classification": "Fear",
                    "timestamp": "1551157200"
                }
            ]
        }

    Returns:
        {
            "fear_greed": int (0~100),
            "fear_greed_label": str,
        }
        실패 시 None 값 반환.
    """
    cached = _get_cache()
    if cached:
        return {
            "fear_greed": cached.get("fear_greed"),
            "fear_greed_label": cached.get("fear_greed_label"),
        }

    try:
        data = _call_api()
        entries = data.get("data") or []
        if not entries:
            logger.warning("[F&G] data 배열 비어 있음 — API 구조 변경 가능성")
            raise ValueError("Fear & Greed data array empty")

        entry = entries[0]
        raw_value = entry.get("value")
        raw_label = entry.get("value_classification", "")

        if raw_value is None:
            logger.warning("[F&G] value 없음 — API 구조 변경 가능성")
            raise ValueError("Fear & Greed value missing")

        score_int = int(round(float(raw_value)))
        label = _LABEL_MAP.get(raw_label, raw_label)
        result = {"fear_greed": score_int, "fear_greed_label": label}
        _save_cache(result)

        logger.info("[F&G] score=%d label=%s", score_int, label)
        return result

    except Exception as exc:
        logger.warning("[F&G] 수집 실패 (영향 없음): %s", exc)
        stale = _get_cache(allow_stale=True)
        if stale:
            return {
                "fear_greed": stale.get("fear_greed"),
                "fear_greed_label": stale.get("fear_greed_label"),
            }
        return {"fear_greed": None, "fear_greed_label": None}
