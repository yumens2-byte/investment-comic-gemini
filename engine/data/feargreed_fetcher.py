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

import requests

from engine.common.retry import api_retry

logger = logging.getLogger(__name__)

_FNG_URL = "https://api.alternative.me/fng/?limit=1"

_LABEL_MAP = {
    "Extreme Fear": "Extreme Fear",
    "Fear": "Fear",
    "Neutral": "Neutral",
    "Greed": "Greed",
    "Extreme Greed": "Extreme Greed",
}


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
    try:
        data = _call_api()
        entries = data.get("data") or []
        if not entries:
            logger.warning("[F&G] data 배열 비어 있음 — API 구조 변경 가능성")
            return {"fear_greed": None, "fear_greed_label": None}

        entry = entries[0]
        raw_value = entry.get("value")
        raw_label = entry.get("value_classification", "")

        if raw_value is None:
            logger.warning("[F&G] value 없음 — API 구조 변경 가능성")
            return {"fear_greed": None, "fear_greed_label": None}

        score_int = int(round(float(raw_value)))
        label = _LABEL_MAP.get(raw_label, raw_label)

        logger.info("[F&G] score=%d label=%s", score_int, label)
        return {"fear_greed": score_int, "fear_greed_label": label}

    except Exception as exc:
        logger.warning("[F&G] 수집 실패 (영향 없음): %s", exc)
        return {"fear_greed": None, "fear_greed_label": None}
