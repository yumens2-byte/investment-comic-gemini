import pandas as pd

from engine.data import market_fetcher


def test_fetch_ticker_safe_allows_single_close_for_current_price(monkeypatch) -> None:
    frame = pd.DataFrame({"Close": [101.25]}, index=pd.to_datetime(["2026-06-09"]))
    monkeypatch.setattr(market_fetcher, "_download_ticker", lambda ticker, period: frame)

    data = market_fetcher._fetch_ticker_safe("BTC-USD", "2d")

    assert data == {"close": 101.25, "prev_close": None, "pct_change": None}


def test_fetch_ticker_safe_uses_coinbase_fallback_for_btc(monkeypatch) -> None:
    def fail_download(ticker: str, period: str) -> pd.DataFrame:
        raise ValueError("temporary yfinance outage")

    monkeypatch.setattr(market_fetcher, "_download_ticker", fail_download)
    monkeypatch.setattr(market_fetcher, "_fetch_btc_usd_fallback", lambda: 98765.43)

    data = market_fetcher._fetch_ticker_safe("BTC-USD", "2d")

    assert data == {"close": 98765.43, "prev_close": None, "pct_change": None}


def test_fetch_ticker_safe_non_btc_remains_none_on_failure(monkeypatch) -> None:
    def fail_download(ticker: str, period: str) -> pd.DataFrame:
        raise ValueError("temporary yfinance outage")

    monkeypatch.setattr(market_fetcher, "_download_ticker", fail_download)

    data = market_fetcher._fetch_ticker_safe("SPY", "5d")

    assert data == {"close": None, "prev_close": None, "pct_change": None}
