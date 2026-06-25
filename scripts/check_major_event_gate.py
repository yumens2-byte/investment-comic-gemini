"""Check whether expensive stages (Claude/Gemini) should run for a date.

Usage:
  python -m scripts.check_major_event_gate --date 2026-05-03

Prints a single line for GitHub Actions:
  should_run_expensive=true|false
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _ensure_repo_root_on_path() -> None:
    """Allow this script to import project packages when run as a file."""
    repo_root = Path(__file__).resolve().parents[1]
    repo_root_text = str(repo_root)
    if repo_root_text not in sys.path:
        sys.path.insert(0, repo_root_text)


_ensure_repo_root_on_path()

MAJOR_EVENT_TYPES = frozenset(
    {
        "BATTLE",
        "SHOCK",
        "AFTERMATH",
        "BATTLE_PLUS",
        "BATTLE_PLUS_FORM2",
        "BATTLE_PLUS_FORM3",
        "EMERGENCE",
        "SEASON_FINALE",
    }
)


def should_run_expensive(event_type: str) -> bool:
    return (event_type or "").upper() in MAJOR_EVENT_TYPES


def main() -> None:
    parser = argparse.ArgumentParser(description="Major event gate checker")
    parser.add_argument("--date", required=True, help="analysis date (YYYY-MM-DD)")
    args = parser.parse_args()

    from engine.common.supabase_client import icg_table

    rows = (
        icg_table("daily_analysis")
        .select("regime")
        .eq("analysis_date", args.date)
        .limit(1)
        .execute()
    )
    event_type = "NORMAL"
    if rows.data:
        event_type = str(rows.data[0].get("regime") or "NORMAL")

    print(f"event_type={event_type}")
    print(f"should_run_expensive={'true' if should_run_expensive(event_type) else 'false'}")


if __name__ == "__main__":
    main()
