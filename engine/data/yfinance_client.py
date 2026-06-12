"""Thread-safe yfinance download helpers for GitHub Actions.

The GitHub hosted runner can execute several ``yf.download`` calls in parallel.
yfinance initializes a SQLite-backed timezone cache on first use, and concurrent
initialization/downloads can surface noisy ``OperationalError: database is locked``
messages even when retries later succeed.  This module gives the pipeline one
isolated cache directory per run/process and serializes yfinance access so those
cache writes cannot race each other.
"""

from __future__ import annotations

import logging
import os
import tempfile
import threading
from pathlib import Path
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

_CACHE_ENV = "YFINANCE_CACHE_DIR"
_CONFIG_LOCK = threading.Lock()
_DOWNLOAD_LOCK = threading.Lock()
_CONFIGURED_CACHE_DIR: Path | None = None


def _default_cache_dir() -> Path:
    """Return an isolated cache path for this workflow run/process."""
    run_id = os.environ.get("GITHUB_RUN_ID") or "local"
    run_attempt = os.environ.get("GITHUB_RUN_ATTEMPT") or "0"
    return Path(tempfile.gettempdir()) / "icg-yfinance" / f"{run_id}-{run_attempt}-{os.getpid()}"


def _create_cache_dir(cache_dir: Path) -> Path:
    """Create a yfinance cache directory, falling back if the requested path is invalid."""
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        if cache_dir.is_dir():
            return cache_dir
        raise NotADirectoryError(str(cache_dir))
    except OSError as exc:
        fallback_dir = Path(tempfile.mkdtemp(prefix="icg-yfinance-"))
        logger.warning(
            "[yfinance] cache dir unavailable path=%s fallback=%s error=%s",
            cache_dir,
            fallback_dir,
            type(exc).__name__,
        )
        return fallback_dir


def configure_yfinance_cache() -> Path:
    """Configure yfinance to use an isolated cache directory once per process."""
    global _CONFIGURED_CACHE_DIR

    with _CONFIG_LOCK:
        if _CONFIGURED_CACHE_DIR is not None:
            return _CONFIGURED_CACHE_DIR

        requested_dir = Path(os.environ.get(_CACHE_ENV) or _default_cache_dir())
        cache_dir = _create_cache_dir(requested_dir)

        import yfinance as yf

        set_cache_location = getattr(yf, "set_tz_cache_location", None)
        if callable(set_cache_location):
            try:
                set_cache_location(str(cache_dir))
            except OSError as exc:
                fallback_dir = Path(tempfile.mkdtemp(prefix="icg-yfinance-"))
                logger.warning(
                    "[yfinance] cache setup failed path=%s fallback=%s error=%s",
                    cache_dir,
                    fallback_dir,
                    type(exc).__name__,
                )
                set_cache_location(str(fallback_dir))
                cache_dir = fallback_dir
        else:
            logger.warning("[yfinance] set_tz_cache_location unavailable; using default cache")

        _CONFIGURED_CACHE_DIR = cache_dir
        return cache_dir


def download(*args: Any, **kwargs: Any) -> pd.DataFrame:
    """Run ``yf.download`` with cache setup and a process-local download lock."""
    import yfinance as yf

    configure_yfinance_cache()
    with _DOWNLOAD_LOCK:
        return yf.download(*args, **kwargs)
