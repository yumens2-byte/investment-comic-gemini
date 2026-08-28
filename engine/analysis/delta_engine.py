"""
engine/analysis/delta_engine.py
icg.daily_snapshots 두 row에서 전일 대비 delta 계산.

출력 형식 (doc 16a Claude 입력 context):
  {
    "VIX":   {"prev": 18.2, "curr": 24.1, "pct": 32.4},
    "WTI":   {"prev": 82.1, "curr": 88.5, "pct":  7.8},
    "DGS10": {"prev":  4.5, "curr":  4.9, "pct":  8.9},
    ...
  }
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# snapshot 컬럼 → delta key 매핑
_METRIC_MAP: dict[str, str] = {
    "vix": "VIX",
    "oil_wti": "WTI",
    "us10y": "DGS10",
    "spy_change": "SPY",
    "nasdaq_change": "NASDAQ",
    "fed_funds_rate": "DFF",
    "hy_spread": "HY_SPREAD",
    "dollar_index": "DXY",
    "usdkrw": "USDKRW",
    "btc_usd": "BTC",
    "fear_greed": "FEAR_GREED",
    "crypto_basis_spread": "CRYPTO_BASIS",
    "btc_social_sentiment": "BTC_SENTIMENT",
}

# Snapshot columns do not all contain a comparable market *level*.  In
# particular, spy_change/nasdaq_change are already daily returns.  Recomputing
# their percentage change across snapshot rows produces meaningless values such
# as +1190%.  Keep this registry beside the mapping so every downstream consumer
# receives an explicit semantic contract.
_SEMANTICS: dict[str, tuple[str, str]] = {
    "spy_change": ("daily_return_pct", "pct"),
    "nasdaq_change": ("daily_return_pct", "pct"),
    "crypto_basis_spread": ("spread", "ratio"),
    "fed_funds_rate": ("rate", "pct"),
    "us10y": ("rate", "pct"),
    "hy_spread": ("spread", "pct_point"),
    "fear_greed": ("index_score", "score"),
    "btc_social_sentiment": ("index_score", "score"),
}


def compute(
    curr_row: dict,
    prev_row: dict | None = None,
) -> dict[str, dict[str, float | None]]:
    """
    두 snapshot row에서 delta 계산.

    Args:
        curr_row: 오늘 daily_snapshots row.
        prev_row: 어제 row. None이면 pct는 None.

    Returns:
        delta dict (doc 16a Claude context 형식).
    """
    delta: dict[str, dict] = {}

    for col, key in _METRIC_MAP.items():
        curr_val = curr_row.get(col)
        prev_val = prev_row.get(col) if prev_row else None

        if curr_val is None:
            continue

        semantic_type, unit = _SEMANTICS.get(col, ("level", "native"))
        pct: float | None = None
        if semantic_type == "daily_return_pct":
            # Compatibility: formula engines historically read row["pct"].
            # For a daily-return snapshot the supplied value itself is the
            # percentage move; it must never be compared to yesterday's return.
            pct = float(curr_val)
        elif semantic_type == "level" and prev_val is not None and prev_val != 0:
            pct = round((curr_val - prev_val) / abs(prev_val) * 100, 4)

        change = None
        if prev_val is not None and semantic_type in {"rate", "spread", "index_score"}:
            change = round(float(curr_val) - float(prev_val), 6)

        delta[key] = {
            "prev": prev_val,
            "curr": curr_val,
            "pct": pct,
            "semantic_type": semantic_type,
            "unit": unit,
            "change": change,
        }

    logger.debug("[delta] %d개 지표 계산 완료", len(delta))
    return delta
