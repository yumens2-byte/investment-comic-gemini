"""
engine/data/crypto_fetcher.py
Crypto.com Exchange API — BTC perp-spot basis spread 수집.

Crypto.com은 인증 불필요 (public endpoint).
basis_spread = (mark_price - index_price) / index_price * 100

State 판정:
  basis_spread > 1.0  → "Premium"  (선물 과열)
  -1.0 ~ 1.0          → "Normal"
  basis_spread < -1.0 → "Discount" (공포)
"""

from __future__ import annotations

import logging

import requests

from engine.common.retry import api_retry

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.crypto.com/exchange/v1/public"


@api_retry(max_attempts=3, min_wait=1.0, max_wait=10.0)
def _get_mark_price(instrument: str = "BTCUSD-PERP") -> float | None:
    """Crypto.com mark price 조회."""
    resp = requests.get(
        f"{_BASE_URL}/get-mark-price",
        params={"instrument_name": instrument},
        timeout=8,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != 0:
        raise ValueError(f"Crypto.com mark-price error: code={data.get('code')}")
    items = data.get("result", {}).get("data", [])
    if not items:
        return None
    return float(items[0]["v"])


@api_retry(max_attempts=3, min_wait=1.0, max_wait=10.0)
def _get_index_price(instrument: str = "BTCUSD-INDEX") -> float | None:
    """Crypto.com index price 조회."""
    resp = requests.get(
        f"{_BASE_URL}/get-index-price",
        params={"instrument_name": instrument},
        timeout=8,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != 0:
        raise ValueError(f"Crypto.com index-price error: code={data.get('code')}")
    items = data.get("result", {}).get("data", [])
    if not items:
        return None
    return float(items[0]["v"])


def _calc_state(basis_pct: float) -> str:
    if basis_pct > 1.0:
        return "Premium"
    if basis_pct < -1.0:
        return "Discount"
    return "Normal"


def fetch_all(target_date: str | None = None) -> dict[str, float | str | None]:
    """
    BTC basis spread 수집.

    Returns:
        {
            "crypto_basis_spread": float | None,
            "crypto_basis_state": str,   # "Premium" | "Normal" | "Discount" | "Unknown"
        }
    """
    try:
        mark = _get_mark_price()
        index = _get_index_price()

        if mark is None or index is None or index == 0:
            logger.warning("[Crypto] mark(%s) 또는 index(%s) 없음", mark, index)
            return {"crypto_basis_spread": None, "crypto_basis_state": "Unknown"}

        basis = round((mark - index) / index * 100, 6)
        state = _calc_state(basis)

        logger.info(
            "[Crypto] basis=%.4f%% state=%s (mark=%.1f index=%.1f)", basis, state, mark, index
        )
        return {"crypto_basis_spread": basis, "crypto_basis_state": state}

    except Exception as exc:
        logger.warning("[Crypto] 수집 실패 (영향 없음): %s", exc)
        return {"crypto_basis_spread": None, "crypto_basis_state": "Unknown"}
