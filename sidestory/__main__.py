"""CLI: python -m sidestory --stage gate|echo [--date YYYY-MM-DD] [--force] [--no-persist]."""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone

from sidestory.app.pipeline import P0_STAGES, STAGES, run_gate_and_echo
from sidestory.app.settings import load_settings

KST = timezone(timedelta(hours=9))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sidestory")
    parser.add_argument("--stage", choices=STAGES, required=True)
    parser.add_argument("--date", default="", help="side slot date (KST). default=today KST")
    parser.add_argument("--force", action="store_true", help="ignore Tue/Thu slot check")
    parser.add_argument("--no-persist", action="store_true", help="read-only (no icg_side writes)")
    args = parser.parse_args(argv)

    if args.stage not in P0_STAGES:
        print(json.dumps({"stage": args.stage, "status": "not_implemented_in_P0"}))
        return 2

    settings = load_settings()
    side_day = date.fromisoformat(args.date) if args.date else datetime.now(KST).date()

    from sidestory.adapters.supabase.client import SideSetupError, preflight, side_client
    from sidestory.adapters.supabase.main_feed_reader import SupabaseMainFeedReader
    from sidestory.adapters.supabase.side_store import SupabaseSideStore

    client = side_client(settings)
    try:
        preflight(client)
    except SideSetupError as exc:
        print(json.dumps({"stage": args.stage, "status": "setup_error", "error": str(exc)},
                         ensure_ascii=False))
        return 3
    persist = not (args.no_persist or args.stage == "gate")
    dxy_source = None
    if os.environ.get("SIDESTORY_DXY_SOURCE", "yfinance").lower() == "yfinance":
        from sidestory.adapters.market.yfinance_dxy import YFinanceDxySource

        dxy_source = YFinanceDxySource()
    result = run_gate_and_echo(
        side_day,
        SupabaseMainFeedReader(client),
        SupabaseSideStore(client),
        force=args.force,
        persist=persist,
        dxy_source=dxy_source,
    )
    print(json.dumps({
        "side_episode_id": result.side_episode_id,
        "skipped": result.skipped,
        "persisted": result.persisted,
        "gates": [g.model_dump() for g in result.gates],
        "echo": result.echo if args.stage == "echo" else None,
    }, ensure_ascii=False, indent=2))
    if result.skipped:
        return 0
    return 0 if all(g.passed for g in result.gates) else 1


if __name__ == "__main__":
    sys.exit(main())
