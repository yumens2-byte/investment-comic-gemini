"""Provider fixtures verify no cache/DB fallback and safe evidence failures."""

from datetime import datetime, timezone
from unittest.mock import Mock

import pytest

from engine.data import feargreed_fetcher
from scripts import market_source_probe as probe


@pytest.mark.parametrize("failure", [False, True])
def test_cache_free_fear_greed_never_accesses_database(monkeypatch, failure):
    forbidden = Mock(side_effect=AssertionError("database cache must not be accessed"))
    monkeypatch.setattr(feargreed_fetcher, "_get_cache", forbidden)
    monkeypatch.setattr(feargreed_fetcher, "_save_cache", forbidden)

    def response():
        if failure:
            raise RuntimeError("offline")
        return {"data": [{"value": "44", "timestamp": "1791417600"}]}

    monkeypatch.setattr(feargreed_fetcher, "_call_api", response)
    sources = {}
    value = feargreed_fetcher.fetch_all(source_status=sources, use_cache=False)
    assert value["fear_greed"] == (None if failure else 44)
    forbidden.assert_not_called()


def test_probe_never_loads_previous_snapshot_fallback(monkeypatch):
    from engine.data import critical_fallback_resolver

    forbidden = Mock(side_effect=AssertionError("DB fallback forbidden"))
    monkeypatch.setattr(critical_fallback_resolver, "_load_recent_snapshots", forbidden)
    for module in (probe.fred_fetcher, probe.market_fetcher, probe.feargreed_fetcher):
        monkeypatch.setattr(module, "fetch_all", lambda *args, **kwargs: {})
    monkeypatch.setattr(probe.market_fetcher, "fetch_macro_overrides", lambda **kwargs: {})
    snapshot = probe.collect_snapshot(datetime(2026, 10, 9, 1, tzinfo=timezone.utc))
    assert snapshot["data_quality"]["status"] == "blocked"
    assert snapshot["data_quality"]["fallbacks"] == []
    forbidden.assert_not_called()


def test_success_requires_exact_validator_and_does_not_claim_persistence(monkeypatch):
    snapshot = {"snapshot_date": "2026-10-09"}
    monkeypatch.setattr(probe, "collect_snapshot", lambda now: snapshot)
    validator = Mock()
    now = datetime(2026, 10, 9, tzinfo=timezone.utc)
    report = probe.probe(validator, now=now)
    validator.assert_called_once_with(snapshot, now)
    assert report["status"] == "PASS"
    assert report["database_writes"] == report["paid_calls"] == report["publishes"] == 0
    assert "persisted_snapshot" in report["unverified"]


def test_provider_exception_text_never_reaches_evidence(monkeypatch):
    monkeypatch.setattr(
        probe, "collect_snapshot", Mock(side_effect=RuntimeError("secret-url-and-token"))
    )
    report = probe.probe(Mock())
    assert report["status"] == "BLOCKED"
    assert "secret-url-and-token" not in str(report)


def test_non_finite_value_becomes_null_not_invalid_json():
    assert probe.safe_json({"value": float("nan"), "list": [float("inf")]}) == {
        "value": None,
        "list": [None],
    }
