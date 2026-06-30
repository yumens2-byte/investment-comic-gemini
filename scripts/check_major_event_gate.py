"""Check whether expensive stages (Claude/Gemini) should run for a date.

Usage:
  python -m scripts.check_major_event_gate --date 2026-05-03

Prints GitHub Actions output lines:
  event_type=...
  episode_type_v3=...
  gate_source=regime|episode_type_v3|none
  should_run_expensive=true|false
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
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


@dataclass(frozen=True)
class MajorGateDecision:
    """Resolved cost-control decision for a market run."""

    regime: str
    episode_type_v3: str
    should_run_expensive: bool
    gate_source: str


def decide_major_gate(regime: str, episode_type_v3: str = "") -> MajorGateDecision:
    """Decide whether expensive stages should run.

    The legacy scheduled gate keys off ``daily_analysis.regime``.  Phase 2.3 can
    also compute a richer ``analysis_ctx_json.episode_type_v3`` such as
    BATTLE_PLUS/EMERGENCE.  Treat either signal as major so scheduled runs do
    not skip a v3 major episode just because the legacy regime stayed calm.
    """
    normalized_regime = str(regime or "NORMAL").upper()
    normalized_v3 = str(episode_type_v3 or "").upper()

    if should_run_expensive(normalized_regime):
        return MajorGateDecision(
            regime=normalized_regime,
            episode_type_v3=normalized_v3,
            should_run_expensive=True,
            gate_source="regime",
        )
    if should_run_expensive(normalized_v3):
        return MajorGateDecision(
            regime=normalized_regime,
            episode_type_v3=normalized_v3,
            should_run_expensive=True,
            gate_source="episode_type_v3",
        )
    return MajorGateDecision(
        regime=normalized_regime,
        episode_type_v3=normalized_v3,
        should_run_expensive=False,
        gate_source="none",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Major event gate checker")
    parser.add_argument("--date", required=True, help="analysis date (YYYY-MM-DD)")
    args = parser.parse_args()

    from engine.common.supabase_client import icg_table

    rows = (
        icg_table("daily_analysis")
        .select("regime,analysis_ctx_json")
        .eq("analysis_date", args.date)
        .limit(1)
        .execute()
    )
    event_type = "NORMAL"
    episode_type_v3 = ""
    if rows.data:
        row = rows.data[0]
        event_type = str(row.get("regime") or "NORMAL")
        ctx = row.get("analysis_ctx_json") if isinstance(row, dict) else {}
        if isinstance(ctx, dict):
            episode_type_v3 = str(ctx.get("episode_type_v3") or "")

    decision = decide_major_gate(event_type, episode_type_v3)

    print(f"event_type={decision.regime}")
    print(f"episode_type_v3={decision.episode_type_v3}")
    print(f"gate_source={decision.gate_source}")
    print(f"should_run_expensive={'true' if decision.should_run_expensive else 'false'}")


if __name__ == "__main__":
    main()
