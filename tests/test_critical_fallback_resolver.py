from engine.data.critical_fallback_resolver import resolve_critical_fallbacks
from engine.data.snapshot_writer import enforce_critical_quality


def _complete_payload() -> dict:
    return {
        "fed_funds_rate": 3.62,
        "us10y": 4.45,
        "vix": 15.74,
        "oil_wti": 97.63,
        "dollar_index": 119.2868,
        "hy_spread": 2.72,
        "yield_curve": 0.47,
        "spy_change": 0.25,
        "nasdaq_change": 0.20,
        "btc_usd": 72591.1,
        "usdkrw": 1508.7,
        "fear_greed": 29,
        "fear_greed_label": "Fear",
        "crypto_basis_spread": 0.1,
        "crypto_basis_state": "Normal",
        "btc_social_sentiment": 61.0,
        "btc_sentiment_state": "Bullish",
    }


def test_resolver_leaves_complete_payload_complete() -> None:
    payload = _complete_payload()

    resolved, data_quality = resolve_critical_fallbacks(
        snapshot_date="2026-06-20",
        payload=payload,
        recent_snapshots=[],
    )

    assert resolved == payload
    assert data_quality["status"] == "complete"
    assert data_quality["missing_before"] == []
    assert data_quality["fallbacks"] == []
    enforce_critical_quality(resolved)


def test_resolver_fills_missing_critical_from_previous_snapshot() -> None:
    payload = _complete_payload()
    payload["fear_greed"] = None
    payload["usdkrw"] = None
    recent = [
        {
            "snapshot_date": "2026-06-19",
            "fear_greed": 41,
            "usdkrw": 1472.3,
        }
    ]

    resolved, data_quality = resolve_critical_fallbacks(
        snapshot_date="2026-06-20",
        payload=payload,
        recent_snapshots=recent,
    )

    assert resolved["fear_greed"] == 41
    assert resolved["usdkrw"] == 1472.3
    assert data_quality["status"] == "resolved_with_fallback"
    assert data_quality["missing_before"] == ["usdkrw", "fear_greed"]
    assert data_quality["missing_after"] == []
    assert [item["field"] for item in data_quality["fallbacks"]] == ["usdkrw", "fear_greed"]
    enforce_critical_quality(resolved)


def test_resolver_blocks_stale_market_sensitive_field() -> None:
    payload = _complete_payload()
    payload["vix"] = None
    recent = [{"snapshot_date": "2026-06-18", "vix": 21.2}]

    resolved, data_quality = resolve_critical_fallbacks(
        snapshot_date="2026-06-20",
        payload=payload,
        recent_snapshots=recent,
    )

    assert resolved["vix"] is None
    assert data_quality["status"] == "blocked"
    assert data_quality["missing_after"] == ["vix"]
    assert data_quality["blocked_fields"] == ["vix: stale source too old age_days=2 max=1"]


def test_resolver_ignores_future_snapshot_candidate() -> None:
    payload = _complete_payload()
    payload["fear_greed"] = None
    recent = [
        {"snapshot_date": "2026-06-21", "fear_greed": 80},
        {"snapshot_date": "2026-06-19", "fear_greed": 42},
    ]

    resolved, data_quality = resolve_critical_fallbacks(
        snapshot_date="2026-06-20",
        payload=payload,
        recent_snapshots=recent,
    )

    assert resolved["fear_greed"] == 42
    assert data_quality["status"] == "resolved_with_fallback"
