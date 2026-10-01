"""Operational read-only SNS verification, including historical missing artifacts."""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

from engine.common.supabase_client import icg_table
from scripts import run_publish
from scripts.publish_preflight import parse_dry_run


def evidence_hash(target: str) -> str:
    day = target[4:14]
    payload = {}
    for table, column, value in [('episode_assets', 'episode_date', day),
                                  ('published_comics', 'publish_date', day),
                                  ('run_logs', 'episode_date', day),
                                  ('video_assets', 'episode_id', target)]:
        rows = icg_table(table).select('*').eq(column, value).execute().data
        if not isinstance(rows, list):
            raise ValueError('Invalid database evidence')
        payload[table] = sorted(rows, key=lambda r: json.dumps(r, sort_keys=True, default=str))
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def main() -> int:
    root = Path('output/publish-dry-beta')
    root.mkdir(parents=True, exist_ok=True)
    report = {'status': 'failed', 'checks': [], 'paid_calls': 0, 'publishes': 0}
    try:
        rows = icg_table('episode_assets').select('episode_date,episode_no').eq(
            'status', 'published'
        ).order('episode_date', desc=True).order('episode_no', desc=True).limit(1).execute().data
        if not rows:
            raise AssertionError('No published episode')
        published = f"ICG-{rows[0]['episode_date']}-{rows[0]['episode_no']:03d}"
        historical = 'ICG-2026-05-10-001'
        targets = [historical, published]
        before = {target: evidence_hash(target) for target in targets}
        configured = parse_dry_run(os.environ.get('DRY_RUN', 'true'))

        def inspect(target, name, *, force_dry=False):
            path = root / f'{name}.json'
            sys.argv = ['run_publish', '--preflight-only', '--episode', target,
                        '--channels', 'all', '--report', str(path)]
            if force_dry:
                sys.argv.append('--dry-run')
            try:
                run_publish.main()
            except SystemExit as exc:
                if exc.code != 1:
                    raise
            result = json.loads(path.read_text())
            assert result['database_writes'] == result['paid_calls'] == result['publishes'] == 0
            assert result['allowed'] is False
            return result

        with patch('engine.common.logger.StepLogger', side_effect=AssertionError('DB logging')):
            default = inspect(published, 'repository-default')
            assert default['mode'] == ('dry_run' if configured else 'live_preflight')
            report['checks'].append('repository_secret_mode_wired')
            os.environ['DRY_RUN'] = 'true'
            old = inspect(historical, 'historical-dry')
            assert old['inspection_status'] == 'pass' and old['slides_files_valid'] is False
            report['checks'].append('historical_missing_slides_not_ready')
            done = inspect(published, 'published-dry')
            assert done['inspection_status'] == 'pass' and 'already_published' in done['block_reasons']
            report['checks'].append('published_dry_read_only')
            os.environ['DRY_RUN'] = 'false'
            blocked = inspect(published, 'published-live-preflight')
            assert blocked['status'] == 'blocked'
            report['checks'].append('published_live_block_before_send')
            old_live = inspect(historical, 'historical-live-preflight')
            assert old_live['live_publish_ready'] is False
            report['checks'].append('historical_live_not_ready')
        assert before == {target: evidence_hash(target) for target in targets}
        report.update(status='pass', episodes=targets, unchanged_database_hashes=before)
        report['checks'].append('episode_history_video_logs_unchanged')
    except Exception as exc:
        report['error_type'] = type(exc).__name__
    (root / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report))
    return 0 if report['status'] == 'pass' else 1


if __name__ == '__main__':
    raise SystemExit(main())
