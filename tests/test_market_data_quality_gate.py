import pytest

from engine.data.snapshot_writer import (
    CRITICAL_FIELDS,
    CriticalDataMissingError,
    build_snapshot_payload,
    enforce_critical_quality,
)


def _base_parts() -> tuple[dict, dict, dict, dict, dict]:
    fred = {
        "fed_funds_rate": 3.62,
        "us10y": 4.45,
        "vix": 15.74,
        "oil_wti": 97.63,
        "dollar_index": 119.2868,
        "hy_spread": 2.72,
        "yield_curve": 0.47,
    }
    market = {
        "spy_change": 0.25,
        "nasdaq_change": 0.20,
        "btc_usd": 72591.1,
        "usdkrw": 1508.7,
    }
    feargreed = {"fear_greed": 29, "fear_greed_label": "Fear"}
    crypto = {"crypto_basis_spread": 0.1, "crypto_basis_state": "Normal"}
    sentiment = {"btc_social_sentiment": 61.0, "btc_sentiment_state": "Bullish"}
    return fred, market, feargreed, crypto, sentiment


def _payload_for_day(day_idx: int) -> dict:
    fred, market, feargreed, crypto, sentiment = _base_parts()
    market["spy_change"] = round((day_idx - 3) * 0.12, 4)
    market["nasdaq_change"] = round((day_idx - 2) * 0.15, 4)
    return build_snapshot_payload(fred, market, feargreed, crypto, sentiment)


def test_full_week_pilot_gate_blocks_only_critical_market_gaps() -> None:
    """Pilot a Monday-Sunday run: optional gaps pass, critical gaps stop that day."""
    weekly_payloads = [_payload_for_day(idx) for idx in range(7)]
    weekly_payloads[2]["btc_social_sentiment"] = None
    weekly_payloads[2]["btc_sentiment_state"] = "Unknown"
    weekly_payloads[5]["vix"] = None

    passed_days: list[int] = []
    blocked: dict[int, list[str]] = {}
    for idx, payload in enumerate(weekly_payloads):
        try:
            enforce_critical_quality(payload, context=f"pilot day {idx + 1}")
            passed_days.append(idx + 1)
        except CriticalDataMissingError as exc:
            blocked[idx + 1] = exc.critical_missing

    assert passed_days == [1, 2, 3, 4, 5, 7]
    assert blocked == {6: ["vix"]}


def test_critical_field_contract_covers_autopublish_market_inputs() -> None:
    assert set(CRITICAL_FIELDS) == {
        "us10y",
        "vix",
        "oil_wti",
        "spy_change",
        "nasdaq_change",
        "btc_usd",
        "usdkrw",
        "fear_greed",
    }


@pytest.mark.parametrize("field", CRITICAL_FIELDS)
def test_each_critical_field_blocks_autopublish(field: str) -> None:
    payload = _payload_for_day(0)
    payload[field] = None

    with pytest.raises(CriticalDataMissingError) as exc_info:
        enforce_critical_quality(payload, context="single critical probe")

    assert exc_info.value.critical_missing == [field]
