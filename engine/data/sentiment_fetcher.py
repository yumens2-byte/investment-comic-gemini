"""
engine/data/sentiment_fetcher.py
LunarCrush BTC Social Sentiment 수집.

무료 플랜 제약:
  4 req/min, 100 req/day
  Galaxy Score / AltRank 마스킹됨
  Sentiment %, Social Dominance 가용

캐싱 전략:
  icg.api_cache 테이블 TTL 60분
  캐시 HIT → API 호출 0
  rate limit 시 만료 캐시도 fallback 사용
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone

import requests

from engine.common.retry import api_retry

logger = logging.getLogger(__name__)

_LUNAR_BASE = "https://lunarcrush.com/api4/public"
_CACHE_KEY = "lunarcrush:topic:bitcoin"
_TTL_MINUTES = 60


def _get_cache() -> dict | None:
    """icg.api_cache에서 캐시 조회 (유효 기간 내)."""
    try:
        from engine.common.supabase_client import icg_table

        rows = (
            icg_table("api_cache").select("value,expires_at").eq("cache_key", _CACHE_KEY).execute()
        )
        if not rows.data:
            return None

        row = rows.data[0]
        expires_at_str = row.get("expires_at", "")
        expires_at = datetime.fromisoformat(expires_at_str.replace("Z", "+00:00"))

        if datetime.now(timezone.utc) < expires_at:
            logger.info("[LunarCrush] 캐시 HIT (expires=%s)", expires_at_str[:19])
            return row["value"]
        return None

    except Exception as exc:
        logger.warning("[LunarCrush] 캐시 조회 실패: %s", exc)
        return None


def _get_stale_cache() -> dict | None:
    """만료된 캐시도 fallback으로 반환 (rate limit 대응)."""
    try:
        from engine.common.supabase_client import icg_table

        rows = (
            icg_table("api_cache")
            .select("value")
            .eq("cache_key", _CACHE_KEY)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        if rows.data:
            logger.warning("[LunarCrush] stale 캐시 fallback 사용")
            return rows.data[0]["value"]
        return None

    except Exception as exc:
        logger.warning("[LunarCrush] stale 캐시 조회 실패: %s", exc)
        return None


def _save_cache(raw_data: dict) -> None:
    """icg.api_cache에 응답 저장 (UPSERT)."""
    try:
        from engine.common.supabase_client import icg_table

        expires_at = (datetime.now(timezone.utc) + timedelta(minutes=_TTL_MINUTES)).isoformat()
        icg_table("api_cache").upsert(
            {
                "cache_key": _CACHE_KEY,
                "value": raw_data,
                "source": "lunarcrush",
                "expires_at": expires_at,
            },
            on_conflict="cache_key",
        ).execute()
        logger.info("[LunarCrush] 캐시 저장 완료 (TTL=%dmin)", _TTL_MINUTES)

    except Exception as exc:
        logger.warning("[LunarCrush] 캐시 저장 실패 (영향 없음): %s", exc)


@api_retry(max_attempts=2, min_wait=3.0, max_wait=15.0)
def _call_api(api_key: str) -> dict:
    """LunarCrush Topic API 호출."""
    resp = requests.get(
        f"{_LUNAR_BASE}/topic/bitcoin/v1",
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def _parse_sentiment(raw: dict) -> dict[str, float | str | None]:
    """LunarCrush 응답 파싱 → snapshot 필드."""
    data = raw.get("data", {})
    sentiment = data.get("sentiment")

    if sentiment is None:
        return {"btc_social_sentiment": None, "btc_sentiment_state": "Unknown"}

    sentiment_val = float(sentiment)

    if sentiment_val > 70:
        state = "Bullish"
    elif sentiment_val >= 50:
        state = "Neutral"
    else:
        state = "Bearish"

    return {
        "btc_social_sentiment": round(sentiment_val, 2),
        "btc_sentiment_state": state,
    }


def fetch_all(target_date: str | None = None) -> dict[str, float | str | None]:
    """
    BTC Social Sentiment 수집 (캐싱 전략 포함).

    Returns:
        {
            "btc_social_sentiment": float | None,
            "btc_sentiment_state": str,  # "Bullish" | "Neutral" | "Bearish" | "Unknown"
        }
    """
    api_key = os.environ.get("LUNAR_CRUSH_API_KEY", "")

    # 1. 캐시 HIT
    cached = _get_cache()
    if cached:
        return _parse_sentiment(cached)

    # 2. API 키 없음
    if not api_key:
        logger.warning("[LunarCrush] LUNAR_CRUSH_API_KEY 없음 — Unknown 반환")
        return {"btc_social_sentiment": None, "btc_sentiment_state": "Unknown"}

    # 3. API 호출
    try:
        raw = _call_api(api_key)
        _save_cache(raw)
        result = _parse_sentiment(raw)
        logger.info(
            "[LunarCrush] sentiment=%.1f state=%s",
            result.get("btc_social_sentiment") or 0,
            result.get("btc_sentiment_state"),
        )
        return result

    except Exception as exc:
        logger.warning("[LunarCrush] API 실패: %s", exc)

        # 4. stale 캐시 fallback
        stale = _get_stale_cache()
        if stale:
            return _parse_sentiment(stale)

        return {"btc_social_sentiment": None, "btc_sentiment_state": "Unknown"}
