"""Operational verification of readonly dry runs against a published episode."""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

from engine.common.supabase_client import icg_table
from scripts import run_market


def evidence_hash(episode_date: str) -> str:
    payload = {}
    for table, column in [('episode_assets', 'episode_date'),
                          ('daily_snapshots', 'snapshot_date'),
                          ('daily_analysis', 'analysis_date'), ('run_logs', 'episode_date')]:
        rows = icg_table(table).select('*').eq(column, episode_date).execute().data
        if not isinstance(rows, list):
            raise ValueError('Invalid database evidence')
        payload[table] = sorted(rows, key=lambda r: json.dumps(r, sort_keys=True, default=str))
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def main() -> int:
    root = Path('output/run-market-dry-beta')
    root.mkdir(parents=True, exist_ok=True)
    report = {'status': 'failed', 'checks': [], 'paid_calls': 0, 'publishes': 0}
    try:
        rows = icg_table('episode_assets').select('episode_date').eq(
            'status', 'published'
        ).order('episode_date', desc=True).limit(1).execute().data
        if not rows:
            raise AssertionError('No published episode to verify protection')
        target = rows[0]['episode_date']
        before = evidence_hash(target)
        os.environ['DRY_RUN'] = 'true'
        with patch('engine.common.logger.StepLogger', side_effect=AssertionError('DB log write')):
            for stage in ('all', 'narrative', 'image'):
                path = root / f'dry-{stage}.json'
                sys.argv = ['run_market', '--stage', stage, '--date', target, '--report', str(path)]
                run_market.main()
                result = json.loads(path.read_text())
                assert result['mode'] == 'dry_run' and result['status'] == 'pass'
                assert result['live_generation_allowed'] is False
                assert result['live_block_reason'] == 'already_published'
                assert result['database_writes'] == result['paid_calls'] == result['publishes'] == 0
                report['checks'].append(f'published_dry_{stage}_pass')
            os.environ['DRY_RUN'] = 'false'
            path = root / 'live-preflight.json'
            sys.argv = ['run_market', '--preflight-only', '--stage', 'all', '--date', target,
                        '--report', str(path)]
            run_market.main()
            result = json.loads(path.read_text())
            assert result['status'] == 'blocked' and result['allowed'] is False
            report['checks'].append('published_live_block_before_mutation')
        assert before == evidence_hash(target)
        report.update(status='pass', episode_date=target, unchanged_database_hash=before)
        report['checks'].append('episode_snapshot_analysis_logs_unchanged')
    except Exception as exc:
        report['error_type'] = type(exc).__name__
    (root / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report))
    return 0 if report['status'] == 'pass' else 1


if __name__ == '__main__':
    raise SystemExit(main())
