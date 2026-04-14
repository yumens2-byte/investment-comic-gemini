"""
engine/data/feargreed_fetcher.py
CNN Fear & Greed Index 수집.

엔드포인트: CNN 비공식 API (공개 JSON).
실패 시 None 반환 (파이프라인 중단 안 함).
"""

from __future__ import annotations

import logging

import requests

from engine.common.retry import api_retry

logger = logging.getLogger(__name__)

_FNG_URL = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"

_LABEL_MAP = {
    "Extreme Fear": "Extreme Fear",
    "Fear": "Fear",
    "Neutral": "Neutral",
    "Greed": "Greed",
    "Extreme Greed": "Extreme Greed",
}


@api_retry(max_attempts=3, min_wait=2.0, max_wait=15.0)
def _call_api() -> dict:
    """CNN F&G API 호출."""
    resp = requests.get(
        _FNG_URL,
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def fetch_all(target_date: str | None = None) -> dict[str, int | str | None]:
    """
    CNN Fear & Greed 지수 수집.

    Returns:
        {
            "fear_greed": int (0~100),
            "fear_greed_label": str,
        }
        실패 시 None 값 반환.
    """
    try:
        data = _call_api()
        score_data = data.get("fear_and_greed", {})
        score = score_data.get("score")
        rating = score_data.get("rating", "")

        if score is None:
            logger.warning("[F&G] score 없음 — API 구조 변경 가능성")
            return {"fear_greed": None, "fear_greed_label": None}

        score_int = int(round(float(score)))
        label = _LABEL_MAP.get(rating, rating)

        logger.info("[F&G] score=%d label=%s", score_int, label)
        return {"fear_greed": score_int, "fear_greed_label": label}

    except Exception as exc:
        logger.warning("[F&G] 수집 실패 (영향 없음): %s", exc)
        return {"fear_greed": None, "fear_greed_label": None}
