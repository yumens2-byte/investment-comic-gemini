"""Exercise real STEP_2 wiring through provider fixtures and snapshot upsert."""

from unittest.mock import MagicMock

import pandas as pd
import pytest

from engine.data import (
    crypto_fetcher,
    feargreed_fetcher,
    market_fetcher,
    sentiment_fetcher,
    snapshot_writer,
)
from scripts.run_market import step_data


@pytest.mark.parametrize("macro_available", [True, False])
def test_step_data_saves_selected_sources_and_units(monkeypatch, macro_available):
    monkeypatch.setenv("FRED_API_KEY", "fixture-not-a-secret")
    monkeypatch.setenv("MARKET_DATA_EXTENDED_ENABLED", "false")
    monkeypatch.setenv("CRITICAL_DATA_GATE_ENABLED", "true")
    import fredapi

    class Fred:
        def __init__(self, **kwargs):
            pass

        def get_series(self, series, **kwargs):
            values = {"DGS10": 4.2, "VIXCLS": 20.0, "DCOILWTICO": 70.0}
            return pd.Series([values.get(series, 1.0)], index=pd.to_datetime(["2026-10-08"]))

    monkeypatch.setattr(fredapi, "Fred", Fred)

    def download(ticker, period):
        if ticker in {"^VIX", "CL=F"} and not macro_available:
            return pd.DataFrame()
        values = [20.0, 21.0] if ticker == "^VIX" else [100.0, 102.0]
        return pd.DataFrame({"Close": values}, index=pd.to_datetime(["2026-10-07", "2026-10-08"]))

    monkeypatch.setattr(market_fetcher, "_download_ticker", download)
    monkeypatch.setattr(feargreed_fetcher, "_get_cache", lambda **kwargs: None)
    monkeypatch.setattr(feargreed_fetcher, "_save_cache", lambda parsed: None)
    monkeypatch.setattr(
        feargreed_fetcher,
        "_call_api",
        lambda: {"data": [{"value": "44", "timestamp": "1791417600"}]},
    )
    monkeypatch.setattr(crypto_fetcher, "fetch_all", lambda day: {})
    monkeypatch.setattr(sentiment_fetcher, "fetch_all", lambda day: {})
    saved = []
    monkeypatch.setattr(
        snapshot_writer, "upsert_payload", lambda day, payload: saved.append((day, payload))
    )
    step_data("2026-10-09", MagicMock())
    day, payload = saved[0]
    assert day == "2026-10-09"
    quality = payload["data_quality"]
    assert quality["status"] == "complete"
    assert quality["fallbacks"] == []
    sources = quality["source_status"]
    assert all(
        sources[field]["status"] == "ok"
        for field in ("vix", "us10y", "oil_wti", "spy_change", "nasdaq_change", "fear_greed")
    )
    assert sources["us10y"]["market_session_date"] == "2026-10-08"
    assert sources["us10y"]["unit"] == "percent"
    assert sources["vix"]["provider"] == ("yfinance" if macro_available else "FRED")
    assert payload["vix"] == (21.0 if macro_available else 20.0)
    assert sources["fear_greed"]["market_domain"] == "crypto"
    assert sources["fear_greed"]["observed_at_kind"] == "provider_timestamp"
