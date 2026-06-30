import pytest
import requests

from engine.common.retry import NonRetryableAPIError, api_retry
from engine.data.crypto_fetcher import _raise_for_retryable_status as crypto_raise_for_status
from engine.data.sentiment_fetcher import _raise_for_retryable_status as lunar_raise_for_status


def _response(status_code: int, url: str = "https://example.test/api") -> requests.Response:
    resp = requests.Response()
    resp.status_code = status_code
    resp.url = url
    resp._content = b"{}"
    return resp


def test_api_retry_does_not_retry_non_retryable_api_error() -> None:
    calls = 0

    @api_retry(max_attempts=3, min_wait=0, max_wait=0)
    def fail_permanently() -> None:
        nonlocal calls
        calls += 1
        raise NonRetryableAPIError("permanent")

    with pytest.raises(NonRetryableAPIError):
        fail_permanently()

    assert calls == 1


def test_crypto_404_is_classified_as_non_retryable() -> None:
    with pytest.raises(NonRetryableAPIError, match="permanent HTTP 404"):
        crypto_raise_for_status(_response(404), endpoint="get-mark-price")


def test_lunarcrush_402_is_classified_as_non_retryable() -> None:
    with pytest.raises(NonRetryableAPIError, match="permanent HTTP 402"):
        lunar_raise_for_status(_response(402))


def test_transient_status_remains_retryable_http_error() -> None:
    with pytest.raises(requests.HTTPError):
        crypto_raise_for_status(_response(503), endpoint="get-mark-price")


def test_crypto_valuation_uses_public_get_valuations(monkeypatch) -> None:
    from engine.data import crypto_fetcher

    calls: list[tuple[str, dict]] = []

    class FakeResponse:
        status_code = 200
        url = "https://api.crypto.com/exchange/v1/public/get-valuations"

        def json(self) -> dict:
            return {"code": 0, "result": {"data": [{"v": "50776.73", "t": 1}]}}

    def fake_get(url: str, *, params: dict, timeout: int) -> FakeResponse:
        calls.append((url, params))
        assert timeout == 8
        return FakeResponse()

    monkeypatch.setattr(crypto_fetcher.requests, "get", fake_get)

    assert crypto_fetcher._get_valuation("BTCUSD-PERP", "mark_price") == 50776.73
    assert calls == [
        (
            "https://api.crypto.com/exchange/v1/public/get-valuations",
            {
                "instrument_name": "BTCUSD-PERP",
                "valuation_type": "mark_price",
                "count": 1,
            },
        )
    ]


def test_crypto_fetch_all_calculates_basis_from_valuations(monkeypatch) -> None:
    from engine.data import crypto_fetcher

    values = {
        ("BTCUSD-PERP", "mark_price"): 101.0,
        ("BTCUSD-INDEX", "index_price"): 100.0,
    }

    monkeypatch.setattr(
        crypto_fetcher,
        "_get_valuation",
        lambda instrument, valuation_type: values[(instrument, valuation_type)],
    )

    assert crypto_fetcher.fetch_all() == {
        "crypto_basis_spread": 1.0,
        "crypto_basis_state": "Normal",
    }
