"""CLI: python -m sidestory --stage gate|echo|narrative|image|assembly|p1
   [--date YYYY-MM-DD] [--force] [--no-persist] [--retry-hold]."""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone

from sidestory.app.pipeline import P0_STAGES, P1_STAGES, STAGES, run_gate_and_echo
from sidestory.app.settings import load_settings

KST = timezone(timedelta(hours=9))


def _dxy_source():
    if os.environ.get("SIDESTORY_DXY_SOURCE", "yfinance").lower() == "yfinance":
        from sidestory.adapters.market.yfinance_dxy import YFinanceDxySource

        return YFinanceDxySource()
    return None


def _p1_deps(stage: str, settings, feed, store):
    from sidestory.app.p1 import P1Deps
    from sidestory.app.settings import load_characters

    deps = P1Deps(feed=feed, store=store, characters=load_characters(),
                  nn_stage=settings.nn_stage, dxy_source=_dxy_source())
    if stage in {"narrative", "p1"}:
        from sidestory.adapters.icg.llm_adapter import ClaudeNarrativeLLM
        from sidestory.adapters.notion.prompt_loader import NotionPromptSource

        deps.llm, deps.prompts = ClaudeNarrativeLLM(), NotionPromptSource()
    if stage in {"image", "p1"}:
        from sidestory.adapters.icg.image_adapter import GeminiPanelGenerator

        deps.images = GeminiPanelGenerator()
    if stage in {"assembly", "p1"}:
        from sidestory.adapters.icg.composer_adapter import PilSlideComposer

        deps.composer = PilSlideComposer()
    return deps


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sidestory")
    parser.add_argument("--stage", choices=STAGES, required=True)
    parser.add_argument("--date", default="", help="side slot date (KST). default=today KST")
    parser.add_argument("--force", action="store_true", help="ignore Tue/Thu slot check")
    parser.add_argument("--no-persist", action="store_true",
                        help="read-only (gate/echo only; P1 stages always persist)")
    parser.add_argument("--retry-hold", action="store_true",
                        help="p1: release a held episode and resume from its last artifact")
    args = parser.parse_args(argv)

    if args.stage not in P0_STAGES + P1_STAGES:
        print(json.dumps({"stage": args.stage, "status": "not_implemented"}))
        return 2
    if args.stage in P1_STAGES and args.no_persist:
        print(json.dumps({"stage": args.stage, "status": "usage_error",
                          "error": "--no-persist is not supported for P1 stages"}))
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
    feed, store = SupabaseMainFeedReader(client), SupabaseSideStore(client)

    if args.stage in P1_STAGES:
        from sidestory.app.p1 import run_p1, run_stage

        deps = _p1_deps(args.stage, settings, feed, store)
        if args.stage == "p1":
            results = run_p1(side_day, deps, force=args.force, retry_hold=args.retry_hold)
        else:
            results = [run_stage(args.stage, side_day, deps)]
        print(json.dumps({"stage": args.stage, "results": [r.as_dict() for r in results]},
                         ensure_ascii=False, indent=2, default=str))
        last = results[-1]
        if last.status == "skipped":
            return 0
        return 0 if all(r.ok for r in results) else 1

    persist = not (args.no_persist or args.stage == "gate")
    result = run_gate_and_echo(side_day, feed, store, force=args.force, persist=persist,
                               dxy_source=_dxy_source())
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
