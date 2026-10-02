"""Read-only recovery audit. No credentials or full scripts in console output."""
import argparse
import json
from datetime import date
from pathlib import Path

from engine.common.supabase_client import icg_table
from engine.quality.recovery_audit import audit_recovery


def inspect(episode_date: str) -> dict:
    if date.fromisoformat(episode_date).isoformat() != episode_date:
        raise ValueError('Date must use YYYY-MM-DD')
    assets = icg_table('episode_assets')
    rows = assets.select('*').eq('episode_date', episode_date).eq('episode_no', 1).execute().data
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
        raise ValueError('exactly one current episode required')
    previous = icg_table('episode_assets').select('*').eq('status', 'published').eq(
        'episode_no', 1).lt('episode_date', episode_date).order(
        'episode_date', desc=True).limit(1).execute().data
    arc = icg_table('arc_state').select('*').eq('id', 1).execute().data
    calls = icg_table('image_generation_calls').select('*').eq(
        'scope', f'output/episodes/{episode_date}/panels').order('created_at').execute().data
    if not isinstance(arc, list) or len(arc) != 1 or not isinstance(previous, list):
        raise ValueError('invalid state evidence')
    if not isinstance(calls, list) or any(not isinstance(c, dict) for c in calls):
        raise ValueError('invalid ledger response')
    return audit_recovery(rows[0], calls, arc[0], previous[0] if previous else {})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--date', required=True)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    report = inspect(args.date)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + '\n', encoding='utf-8')
    print(text)


if __name__ == '__main__':
    main()
