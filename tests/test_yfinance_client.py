import sys
import types
from pathlib import Path

import pandas as pd

from engine.data import yfinance_client


def _reset_yfinance_client(monkeypatch):
    monkeypatch.setattr(yfinance_client, "_CONFIGURED_CACHE_DIR", None)


def test_configure_yfinance_cache_uses_env_directory(monkeypatch, tmp_path):
    _reset_yfinance_client(monkeypatch)
    calls = []
    fake_yf = types.SimpleNamespace(set_tz_cache_location=lambda path: calls.append(path))
    monkeypatch.setitem(sys.modules, "yfinance", fake_yf)
    cache_dir = tmp_path / "yf-cache"
    monkeypatch.setenv("YFINANCE_CACHE_DIR", str(cache_dir))

    configured = yfinance_client.configure_yfinance_cache()

    assert configured == cache_dir
    assert cache_dir.is_dir()
    assert calls == [str(cache_dir)]


def test_configure_yfinance_cache_falls_back_when_env_path_is_file(monkeypatch, tmp_path):
    _reset_yfinance_client(monkeypatch)
    calls = []
    fake_yf = types.SimpleNamespace(set_tz_cache_location=lambda path: calls.append(Path(path)))
    monkeypatch.setitem(sys.modules, "yfinance", fake_yf)
    bad_cache_path = tmp_path / "yf-cache-file"
    bad_cache_path.write_text("not a directory", encoding="utf-8")
    monkeypatch.setenv("YFINANCE_CACHE_DIR", str(bad_cache_path))

    configured = yfinance_client.configure_yfinance_cache()

    assert configured != bad_cache_path
    assert configured.is_dir()
    assert calls == [configured]


def test_configure_yfinance_cache_falls_back_when_set_cache_location_fails(
    monkeypatch,
    tmp_path,
):
    _reset_yfinance_client(monkeypatch)
    calls = []

    def fake_set_cache_location(path: str):
        calls.append(Path(path))
        if len(calls) == 1:
            raise OSError("locked cache")

    fake_yf = types.SimpleNamespace(set_tz_cache_location=fake_set_cache_location)
    monkeypatch.setitem(sys.modules, "yfinance", fake_yf)
    cache_dir = tmp_path / "yf-cache"
    monkeypatch.setenv("YFINANCE_CACHE_DIR", str(cache_dir))

    configured = yfinance_client.configure_yfinance_cache()

    assert calls[0] == cache_dir
    assert configured != cache_dir
    assert configured.is_dir()
    assert calls[1] == configured


def test_download_configures_cache_before_yfinance_download(monkeypatch, tmp_path):
    _reset_yfinance_client(monkeypatch)
    calls = []
    frame = pd.DataFrame({"Close": [1.0]})

    def fake_download(*args, **kwargs):
        calls.append((args, kwargs))
        return frame

    fake_yf = types.SimpleNamespace(
        set_tz_cache_location=lambda path: calls.append(("cache", Path(path))),
        download=fake_download,
    )
    monkeypatch.setitem(sys.modules, "yfinance", fake_yf)
    monkeypatch.setenv("YFINANCE_CACHE_DIR", str(tmp_path / "yf-cache"))

    data = yfinance_client.download("SPY", period="5d", progress=False)

    assert data is frame
    assert calls[0] == ("cache", tmp_path / "yf-cache")
    assert calls[1] == (("SPY",), {"period": "5d", "progress": False})
