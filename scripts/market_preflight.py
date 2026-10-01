"""Read-only Run Market eligibility and cached-input inspection (no paid calls)."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path


def inspect_market(episode_date: str, stage: str, *, dry_run: bool) -> dict:
    from engine.common.supabase_client import icg_table
    from scripts.run_market import GenerationBlocked, _assert_generation_allowed, _make_episode_id

    if date.fromisoformat(episode_date).isoformat() != episode_date:
        raise ValueError("Date must use YYYY-MM-DD")
    if stage not in {'all', 'data', 'analysis', 'narrative', 'persist', 'image'}:
        raise ValueError('Invalid stage')
    episode_id = _make_episode_id(episode_date)
    report = {'mode': 'dry_run' if dry_run else 'live_preflight', 'status': 'pass',
              'episode_date': episode_date, 'episode_id': episode_id, 'requested_stage': stage,
              'allowed': False, 'database_writes': 0, 'paid_calls': 0, 'publishes': 0,
              'unverified': ['new_data_collection', 'new_narrative', 'new_images', 'live_delivery']}
    try:
        _assert_generation_allowed(episode_date, episode_id)
        report['live_generation_allowed'] = True
    except GenerationBlocked as exc:
        report['live_generation_allowed'] = False
        report['live_block_reason'] = exc.reason
        if not dry_run:
            report['status'] = 'blocked'
            return report
    if report['live_generation_allowed']:
        calls = icg_table('image_generation_calls').select('state').eq(
            'scope', f'output/episodes/{episode_date}/panels'
        ).limit(31).execute().data
        if (not isinstance(calls, list) or any(
            not isinstance(row, dict) or row.get('state') not in
            {'reserved', 'success', 'failed', 'unknown', 'terminal'} for row in calls
        )):
            raise RuntimeError('Invalid image reservation response')
        if any(row['state'] in {'reserved', 'unknown', 'terminal'} for row in calls):
            report['live_generation_allowed'] = False
            report['live_block_reason'] = 'image_generation_reconciliation_hold'
            if not dry_run:
                report['status'] = 'blocked'
                return report
    if not dry_run:
        report['allowed'] = True
        return report

    def read(table, column, fields):
        rows = icg_table(table).select(fields).eq(column, episode_date).limit(1).execute().data
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise RuntimeError('Invalid cached-input response')
        return rows[0] if rows else {}

    snapshot = read('daily_snapshots', 'snapshot_date', 'snapshot_date')
    analysis = read('daily_analysis', 'analysis_date',
                    'analysis_ctx_json,narrative_script_json')
    cached_ctx = analysis.get('analysis_ctx_json')
    cached_script = analysis.get('narrative_script_json')
    if cached_ctx is not None and not isinstance(cached_ctx, dict):
        raise RuntimeError('Malformed cached analysis')
    if cached_script is not None and not isinstance(cached_script, dict):
        raise RuntimeError('Malformed cached narrative')
    report['cached_inputs'] = {'snapshot_present': bool(snapshot),
                               'analysis_present': bool(cached_ctx),
                               'narrative_present': bool(cached_script)}
    report['pipeline_readiness'] = 'ready' if all(report['cached_inputs'].values()) else 'incomplete'
    report['stage_execution'] = 'not_executed_read_only_preflight'
    report['allowed'] = True  # Allowed to inspect; never permission to generate or publish.
    return report


def emit_report(report: dict, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))
