import pytest

from engine.data.snapshot_writer import (
    enforce_critical_quality,
    summarize_quality,
    upsert_payload,
)


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


def test_summarize_quality_classifies_optional_story_enrichment_missing() -> None:
    payload = _complete_payload()
    payload.update(
        {
            "crypto_basis_spread": None,
            "crypto_basis_state": "Unknown",
            "btc_social_sentiment": None,
            "btc_sentiment_state": "Unknown",
        }
    )

    summary = summarize_quality(payload)

    assert summary["critical_missing"] == []
    assert summary["optional_missing"] == [
        "crypto_basis_spread",
        "crypto_basis_state",
        "btc_social_sentiment",
        "btc_sentiment_state",
    ]


def test_summarize_quality_flags_critical_market_missing() -> None:
    payload = _complete_payload()
    payload["vix"] = None
    payload["fear_greed"] = None

    summary = summarize_quality(payload)

    assert summary["critical_missing"] == ["vix", "fear_greed"]


def test_enforce_critical_quality_raises_for_autopublish_blocker() -> None:
    payload = _complete_payload()
    payload["spy_change"] = None

    with pytest.raises(RuntimeError, match="CRITICAL market data missing"):
        enforce_critical_quality(payload, context="STEP_2 date=2026-06-04")


def test_enforce_critical_quality_allows_optional_missing() -> None:
    payload = _complete_payload()
    payload["btc_social_sentiment"] = None
    payload["btc_sentiment_state"] = "Unknown"

    enforce_critical_quality(payload, context="optional sentiment missing")


def test_upsert_payload_retries_without_missing_optional_schema_column(monkeypatch) -> None:
    import sys

    sb = sys.modules["engine.common.supabase_client"]
    calls = []

    def fake_upsert_snapshot(snapshot_date: str, payload: dict):
        calls.append((snapshot_date, dict(payload)))
        if len(calls) == 1:
            raise RuntimeError(
                "{'message': \"Could not find the 'data_quality' column of "
                "'daily_snapshots' in the schema cache\", 'code': 'PGRST204'}"
            )

    monkeypatch.setattr(sb, "upsert_snapshot", fake_upsert_snapshot)

    payload = _complete_payload()
    payload["data_quality"] = {"status": "complete"}

    upsert_payload("2026-06-21", payload)

    assert len(calls) == 2
    assert "data_quality" in calls[0][1]
    assert "data_quality" not in calls[1][1]
