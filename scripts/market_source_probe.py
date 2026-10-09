"""Fresh provider collection; no database, paid calls, or launch approval."""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from importlib.metadata import version
from math import isfinite
from pathlib import Path

from engine.data import feargreed_fetcher, fred_fetcher, market_fetcher
from engine.data.critical_fallback_resolver import resolve_critical_fallbacks

KST = timezone(timedelta(hours=9))


def safe_json(value):
    if isinstance(value, float) and not isfinite(value):
        return None
    if isinstance(value, dict):
        return {key: safe_json(item) for key, item in value.items()}
    if isinstance(value, list):
        return [safe_json(item) for item in value]
    return value


def collect_snapshot(now):
    day = now.astimezone(KST).date().isoformat()
    sources = {}
    fred = fred_fetcher.fetch_all(day, source_status=sources)
    market = market_fetcher.fetch_all(day, source_status=sources)
    overrides = {}
    for field, value in market_fetcher.fetch_macro_overrides(source_status=overrides).items():
        if value is not None:
            fred[field] = value
            sources[field] = overrides[field]
    fg = feargreed_fetcher.fetch_all(day, source_status=sources, use_cache=False)
    payload, quality = resolve_critical_fallbacks(
        snapshot_date=day,
        payload={**fred, **market, **fg},
        source_status=sources,
        recent_snapshots=[],
    )
    return safe_json(
        {**payload, "snapshot_date": day, "created_at": now.isoformat(), "data_quality": quality}
    )


def probe(*, now=None):
    started = now or datetime.now(timezone.utc)
    report = {
        "status": "BLOCKED",
        "mode": "fresh_observation_read_only",
        "checked_at": started.isoformat(),
        "source_commit": os.environ.get("GITHUB_SHA", "local"),
        "database_writes": 0,
        "paid_calls": 0,
        "publishes": 0,
        "unverified": ["source_contract", "persisted_snapshot", "production_db_contract", "facebook_receipt"],
    }
    try:
        snapshot = collect_snapshot(started)
        report["snapshot"] = snapshot
        report["status"] = "COLLECTED"
    except Exception as exc:
        code = getattr(exc, "code", None)
        report["error_code"] = (
            code
            if isinstance(code, str) and re.fullmatch(r"[A-Z_]{1,80}", code)
            else "SOURCE_PROBE_FAILED"
        )
        report["error_type"] = type(exc).__name__
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="output/market-source-probe.json", type=Path)
    args = parser.parse_args()
    logging.disable(logging.CRITICAL)
    report = probe()
    report["dependencies"] = {
        name: version(name) for name in ("yfinance", "fredapi", "pandas", "requests")
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(report, ensure_ascii=False, sort_keys=True, allow_nan=False)
    args.output.write_text(body + "\n", encoding="utf-8")
    print("MARKET_SOURCE_PROBE_EVIDENCE=" + body)
    raise SystemExit(0 if report["status"] == "COLLECTED" else 1)


if __name__ == "__main__":
    main()
