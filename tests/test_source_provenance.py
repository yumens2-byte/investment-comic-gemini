"""Offline provider fixtures; no paid APIs or publication side effects."""

from datetime import datetime, timezone

import pandas as pd
import pytest

from engine.data import feargreed_fetcher as fg
from engine.data import fred_fetcher, market_fetcher
from engine.data.critical_fallback_resolver import resolve_critical_fallbacks
from engine.data.source_provenance import provenance


@pytest.mark.parametrize("session", [None, 1, "not-a-date"])
def test_missing_source_date_is_not_replaced_by_today(session):
    meta = provenance(
        field="us10y", provider="FRED", instrument="DGS10", value=4.2, session=session
    )
    assert meta["status"] == "metadata_missing"
    assert meta["market_session_date"] is None


@pytest.mark.parametrize("value", [None, True, float("nan"), float("inf")])
def test_invalid_values_cannot_have_ok_provenance(value):
    assert (
        provenance(
            field="vix", provider="yfinance", instrument="^VIX", value=value, session="2026-10-08"
        )["status"]
        != "ok"
    )


def test_date_only_metadata_distinguishes_fetch_time_from_source_date():
    received = datetime(2026, 10, 9, 1, tzinfo=timezone.utc)
    meta = provenance(
        field="us10y",
        provider="FRED",
        instrument="DGS10",
        value=4.2,
        session="2026-10-07",
        fetched_at=received,
    )
    assert meta["market_session_date"] == "2026-10-07"
    assert meta["observed_at"] == received.isoformat()
    assert meta["observed_at_kind"] == "response_received"
    assert meta["source_time_precision"] == "date"
    assert "source_timestamp" not in meta


def test_naive_timestamps_rejected():
    with pytest.raises(ValueError):
        provenance(
            field="vix", provider="Y", instrument="V", value=20, fetched_at=datetime(2026, 10, 9)
        )


def test_fred_uses_last_non_missing_provider_date():
    class Fred:
        def get_series(self, *args, **kwargs):
            return pd.Series(
                [4.1, 4.2, None], index=pd.to_datetime(["2026-10-06", "2026-10-07", "2026-10-08"])
            )

    meta = {}
    assert (
        fred_fetcher._fetch_series(
            Fred(), "DGS10", target_date="2026-10-09", source_status=meta, field="us10y"
        )
        == 4.2
    )
    assert meta["us10y"]["market_session_date"] == "2026-10-07"
    assert meta["us10y"]["unit"] == "percent"


def test_market_parallel_collection_retains_each_ticker_session(monkeypatch):
    def download(ticker, period):
        return pd.DataFrame(
            {"Close": [100.0, 102.0]},
            index=pd.DatetimeIndex(["2026-10-07", "2026-10-08"], tz="America/New_York"),
        )

    monkeypatch.setattr(market_fetcher, "_download_ticker", download)
    meta = {}
    values = market_fetcher.fetch_all("2026-10-09", source_status=meta)
    assert values["spy_change"] == 2.0
    assert meta["spy_change"]["market_session_date"] == "2026-10-08"
    assert meta["spy_change"]["previous_session_date"] == "2026-10-07"
    assert meta["nasdaq_change"]["instrument"] == "^IXIC"
    assert set(meta) == set(values)


def test_single_bar_does_not_claim_valid_percent_change(monkeypatch):
    monkeypatch.setattr(
        market_fetcher,
        "_download_ticker",
        lambda *args: pd.DataFrame({"Close": [100.0]}, index=pd.to_datetime(["2026-10-08"])),
    )
    meta = {}
    assert market_fetcher.fetch_all(source_status=meta)["spy_change"] is None
    assert meta["spy_change"]["status"] == "missing"


def test_successful_override_pairs_value_with_yfinance_metadata(monkeypatch):
    monkeypatch.setattr(
        market_fetcher,
        "_download_ticker",
        lambda *args: pd.DataFrame({"Close": [21.0]}, index=pd.to_datetime(["2026-10-08"])),
    )
    meta = {}
    assert market_fetcher.fetch_macro_overrides(source_status=meta) == {
        "vix": 21.0,
        "oil_wti": 21.0,
    }
    assert meta["vix"]["provider"] == "yfinance"
    assert meta["oil_wti"]["unit"] == "USD_per_barrel"


def configure_fg(monkeypatch, *, cache=None, entry=None, fail=False):
    monkeypatch.setattr(
        fg, "_get_cache", lambda *, allow_stale=False: cache if not allow_stale else None
    )
    monkeypatch.setattr(fg, "_save_cache", lambda parsed: None)

    def call():
        if fail:
            raise RuntimeError("offline")
        return {"data": [entry]}

    monkeypatch.setattr(fg, "_call_api", call)


def test_crypto_timestamp_and_market_domain_are_preserved(monkeypatch):
    timestamp = datetime(2026, 10, 8, tzinfo=timezone.utc)
    saved = []
    configure_fg(monkeypatch, entry={"value": "44", "timestamp": str(int(timestamp.timestamp()))})
    monkeypatch.setattr(fg, "_save_cache", lambda parsed: saved.append(parsed))
    meta = {}
    assert fg.fetch_all(source_status=meta)["fear_greed"] == 44
    assert meta["fear_greed"]["observed_at"] == timestamp.isoformat()
    assert meta["fear_greed"]["market_domain"] == "crypto"
    assert saved[0]["_source_status"] == meta["fear_greed"]


def test_fresh_cache_preserves_original_observation_time(monkeypatch):
    original = provenance(
        field="fear_greed",
        provider="alternative.me",
        instrument="crypto_fng",
        value=44,
        session="2026-10-08",
    )
    configure_fg(monkeypatch, cache={"fear_greed": 44, "_source_status": original}, fail=True)
    meta = {}
    assert fg.fetch_all(source_status=meta)["fear_greed"] == 44
    assert meta["fear_greed"]["observed_at"] == original["observed_at"]
    assert meta["fear_greed"]["cache_state"] == "fresh"


def test_legacy_cache_is_refreshed_for_provenance(monkeypatch):
    configure_fg(
        monkeypatch, cache={"fear_greed": 55}, entry={"value": "44", "timestamp": "1791417600"}
    )
    meta = {}
    assert fg.fetch_all(source_status=meta)["fear_greed"] == 44
    assert meta["fear_greed"]["status"] == "ok"


@pytest.mark.parametrize("timestamp", [None, "bad", "9999999999999999999999999999999"])
def test_fg_missing_timestamp_keeps_value_but_holds_metadata(monkeypatch, timestamp):
    configure_fg(monkeypatch, entry={"value": "44", "timestamp": timestamp})
    meta = {}
    assert fg.fetch_all(source_status=meta)["fear_greed"] == 44
    assert meta["fear_greed"]["status"] == "metadata_missing"


def test_stale_cache_never_becomes_ok(monkeypatch):
    configure_fg(monkeypatch, fail=True)
    original = provenance(
        field="fear_greed",
        provider="alternative.me",
        instrument="crypto_fng",
        value=44,
        session="2026-10-07",
    )
    monkeypatch.setattr(
        fg,
        "_get_cache",
        lambda *, allow_stale=False: (
            {"fear_greed": 44, "_source_status": original} if allow_stale else None
        ),
    )
    meta = {}
    assert fg.fetch_all(source_status=meta)["fear_greed"] == 44
    assert meta["fear_greed"]["status"] == "stale_cache"
    assert meta["fear_greed"]["observed_at"] == original["observed_at"]


def test_snapshot_fallback_replaces_attempt_metadata_without_mutating_input():
    source = {"vix": {"status": "missing", "provider": "yfinance"}}
    _, quality = resolve_critical_fallbacks(
        snapshot_date="2026-10-09",
        payload={"vix": None},
        source_status=source,
        recent_snapshots=[{"snapshot_date": "2026-10-08", "vix": 20.0}],
    )
    assert quality["source_status"]["vix"]["status"] == "previous_snapshot"
    assert quality["source_status"]["vix"]["original_attempt"] == source["vix"]
    assert source["vix"]["status"] == "missing"


def test_zero_previous_close_does_not_claim_valid_change(monkeypatch):
    monkeypatch.setattr(
        market_fetcher,
        "_download_ticker",
        lambda *args: pd.DataFrame(
            {"Close": [0.0, 100.0]}, index=pd.to_datetime(["2026-10-07", "2026-10-08"])
        ),
    )
    meta = {}
    values = market_fetcher.fetch_all(source_status=meta)
    assert values["spy_change"] == 0.0  # preserve legacy numeric API
    assert meta["spy_change"]["status"] == "invalid_calculation"


def test_coinbase_fallback_records_actual_provider_without_inventing_date(monkeypatch):
    monkeypatch.setattr(market_fetcher, "_download_ticker", lambda *args: pd.DataFrame())
    monkeypatch.setattr(market_fetcher, "_fetch_btc_usd_fallback", lambda: 90000.0)
    meta = {}
    assert market_fetcher.fetch_all(source_status=meta)["btc_usd"] == 90000.0
    assert meta["btc_usd"]["provider"] == "Coinbase"
    assert meta["btc_usd"]["status"] == "metadata_missing"


@pytest.mark.parametrize("corrupt_metadata", [["unexpected"], {"status": "ok", "value": 99}])
def test_corrupt_fresh_cache_is_refreshed_in_metadata_mode(monkeypatch, corrupt_metadata):
    configure_fg(
        monkeypatch,
        cache={"fear_greed": 44, "_source_status": corrupt_metadata},
        entry={"value": "45", "timestamp": "1791417600"},
    )
    meta = {}
    assert fg.fetch_all(source_status=meta)["fear_greed"] == 45
    assert meta["fear_greed"]["value"] == 45


def test_corrupt_stale_cache_cannot_crash_collection(monkeypatch):
    configure_fg(monkeypatch, fail=True)
    monkeypatch.setattr(
        fg,
        "_get_cache",
        lambda *, allow_stale=False: (
            {"fear_greed": 44, "_source_status": ["bad"]} if allow_stale else None
        ),
    )
    meta = {}
    assert fg.fetch_all(source_status=meta)["fear_greed"] == 44
    assert meta["fear_greed"]["status"] == "stale_cache"


def test_vix_uses_exact_shared_equity_session_not_newer_quote(monkeypatch):
    def download(ticker, period):
        return pd.DataFrame({'Close': [15.41, 15.19]}, index=pd.to_datetime(['2026-10-08', '2026-10-09']))
    monkeypatch.setattr(market_fetcher, '_download_ticker', download)
    meta = {}
    values = market_fetcher.fetch_macro_overrides(source_status=meta, vix_session='2026-10-08')
    assert values['vix'] == 15.41
    assert meta['vix']['value'] == 15.41
    assert meta['vix']['market_session_date'] == '2026-10-08'
    assert values['oil_wti'] == 15.19
    assert meta['oil_wti']['market_session_date'] == '2026-10-09'


def test_missing_exact_vix_session_does_not_relabel_another_day(monkeypatch):
    monkeypatch.setattr(market_fetcher, '_download_ticker', lambda *args: pd.DataFrame({'Close': [15.19]}, index=pd.to_datetime(['2026-10-09'])))
    meta = {}
    values = market_fetcher.fetch_macro_overrides(source_status=meta, vix_session='2026-10-08')
    assert values['vix'] is None
    assert meta['vix']['status'] != 'ok'
    assert meta['vix']['market_session_date'] is None
    assert values['oil_wti'] == 15.19


@pytest.mark.parametrize('nasdaq, status, expected', [
    ('2026-10-08', 'ok', '2026-10-08'),
    ('2026-10-09', 'ok', None),
    ('2026-10-08', 'previous_snapshot', None),
    ('invalid', 'ok', None),
    (None, 'ok', None),
])
def test_equity_session_requires_matching_actual_provider_dates(nasdaq, status, expected):
    sources = {
        'spy_change': {'status': 'ok', 'market_session_date': '2026-10-08'},
        'nasdaq_change': {'status': status, 'market_session_date': nasdaq},
    }
    assert market_fetcher.matched_equity_session(sources) == expected
