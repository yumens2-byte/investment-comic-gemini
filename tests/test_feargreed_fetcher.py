from engine.data import feargreed_fetcher


def test_fetch_all_uses_fresh_cache(monkeypatch) -> None:
    monkeypatch.setattr(
        feargreed_fetcher,
        "_get_cache",
        lambda *, allow_stale=False: {"fear_greed": 55, "fear_greed_label": "Greed"},
    )

    def fail_call() -> dict:
        raise AssertionError("API should not be called on fresh cache hit")

    monkeypatch.setattr(feargreed_fetcher, "_call_api", fail_call)

    assert feargreed_fetcher.fetch_all() == {"fear_greed": 55, "fear_greed_label": "Greed"}


def test_fetch_all_saves_successful_api_response(monkeypatch) -> None:
    saved: list[dict] = []

    monkeypatch.setattr(feargreed_fetcher, "_get_cache", lambda *, allow_stale=False: None)
    monkeypatch.setattr(
        feargreed_fetcher,
        "_call_api",
        lambda: {"data": [{"value": "44", "value_classification": "Fear"}]},
    )
    monkeypatch.setattr(feargreed_fetcher, "_save_cache", lambda parsed: saved.append(parsed))

    result = feargreed_fetcher.fetch_all()

    assert result == {"fear_greed": 44, "fear_greed_label": "Fear"}
    assert saved == [result]


def test_fetch_all_uses_stale_cache_after_api_failure(monkeypatch) -> None:
    def fake_cache(*, allow_stale=False):
        if allow_stale:
            return {"fear_greed": 33, "fear_greed_label": "Fear"}
        return None

    monkeypatch.setattr(feargreed_fetcher, "_get_cache", fake_cache)
    monkeypatch.setattr(
        feargreed_fetcher,
        "_call_api",
        lambda: (_ for _ in ()).throw(RuntimeError("temporary outage")),
    )

    assert feargreed_fetcher.fetch_all() == {"fear_greed": 33, "fear_greed_label": "Fear"}


def test_fetch_all_returns_none_when_api_and_cache_fail(monkeypatch) -> None:
    monkeypatch.setattr(feargreed_fetcher, "_get_cache", lambda *, allow_stale=False: None)
    monkeypatch.setattr(
        feargreed_fetcher,
        "_call_api",
        lambda: (_ for _ in ()).throw(RuntimeError("temporary outage")),
    )

    assert feargreed_fetcher.fetch_all() == {"fear_greed": None, "fear_greed_label": None}
