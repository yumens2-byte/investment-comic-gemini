"""Dry SNS execution must never enter the logging/claim/provider path."""
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import yaml
from PIL import Image

from scripts import publish_preflight, run_publish


@pytest.fixture
def database(monkeypatch, tmp_path):
    from engine.common import logger, supabase_client
    from engine.publish.x_publisher import DISCLAIMER_REQUIRED

    image = tmp_path / 'S1.png'
    Image.new('RGB', (2, 2)).save(image)
    row = dict(status='assembled', event_type='BATTLE', error_message=None,
               script_json={'caption_x_final': DISCLAIMER_REQUIRED},
               slides_json=[{'path': str(image)}])
    data = {'episode_assets': [row], 'published_comics': []}
    calls = []

    class Query:
        def __init__(self, name):
            self.name = name
        def select(self, *_):
            calls.append(self.name)
            return self
        def eq(self, *_):
            return self
        def limit(self, *_):
            return self
        def execute(self):
            value = data[self.name]
            if isinstance(value, Exception):
                raise value
            return SimpleNamespace(data=value)

    monkeypatch.setattr(supabase_client, 'icg_table', Query)
    log = MagicMock(side_effect=AssertionError('must not log to DB'))
    monkeypatch.setattr(logger, 'StepLogger', log)
    monkeypatch.setenv('DRY_RUN', 'true')
    for key in ('X_API_KEY', 'X_API_SECRET', 'X_ACCESS_TOKEN', 'X_ACCESS_TOKEN_SECRET',
                'TELEGRAM_BOT_TOKEN', 'TELEGRAM_FREE_CHANNEL_ID'):
        monkeypatch.setenv(key, 'test-present')
    monkeypatch.delenv('GITHUB_OUTPUT', raising=False)
    monkeypatch.chdir(tmp_path)
    return row, data, calls, log


def inspect():
    return publish_preflight.inspect_publish('ICG-2026-05-10-001', None, 'all', dry_run=True)


def test_ready_dry_report_cannot_authorize_send(database):
    report = inspect()
    assert report['status'] == 'ready'
    assert report['live_publish_ready'] is True
    assert report['allowed'] is False
    assert report['publishes'] == report['database_writes'] == 0


def test_missing_and_corrupt_images_are_incomplete(database):
    row, *_ = database
    Path(row['slides_json'][0]['path']).unlink()
    assert inspect()['status'] == 'incomplete'
    Path(row['slides_json'][0]['path']).write_text('broken')
    assert inspect()['slides_files_valid'] is False


@pytest.mark.parametrize('state', ['published', 'failed', 'draft', 'unknown'])
def test_existing_unready_episode_reports_blocked(database, state):
    row, *_ = database
    row['status'] = state
    assert inspect()['status'] == 'blocked'
    assert inspect()['allowed'] is False


def test_hold_and_duplicate_are_reported(database):
    row, data, *_ = database
    row['error_message'] = 'PUBLISH_HOLD:pending'
    data['published_comics'] = [{'id': 1}]
    assert set(inspect()['block_reasons']) == {'unresolved_publication_hold', 'publication_history_exists'}


def test_missing_disclaimer_and_channel_configuration_are_not_ready(database, monkeypatch):
    row, *_ = database
    row['script_json'] = {}
    monkeypatch.delenv('X_API_KEY')
    monkeypatch.delenv('TELEGRAM_BOT_TOKEN')
    assert set(inspect()['readiness_issues']) == {'x_disclaimer_missing', 'x_configuration_missing', 'telegram_configuration_missing'}


@pytest.mark.parametrize('response', [None, {}, [None], RuntimeError('DB unavailable')])
def test_database_failure_is_not_success(database, response):
    _, data, *_ = database
    data['episode_assets'] = response
    with pytest.raises(RuntimeError):
        inspect()


def test_ambiguous_identity_rejected(database):
    row, data, *_ = database
    data['episode_assets'] = [row, row]
    with pytest.raises(RuntimeError, match='Ambiguous'):
        inspect()


@pytest.mark.parametrize('episode', ['ICG-2026-05-10-001extra', 'ICG-2026-02-30-001', 'ICG-2026-05-10-000'])
def test_invalid_identity_before_reads(database, episode):
    _, _, calls, _ = database
    with pytest.raises(ValueError):
        publish_preflight.inspect_publish(episode, None, 'all', dry_run=True)
    assert calls == []


@pytest.mark.parametrize('value', ['', 'auto', 'tru', '1'])
def test_invalid_mode_before_database(database, monkeypatch, value):
    monkeypatch.setenv('DRY_RUN', value)
    monkeypatch.setattr(sys, 'argv', ['run_publish', '--dry-run', '--episode', 'ICG-2026-05-10-001'])
    with pytest.raises(ValueError):
        run_publish.main()
    assert database[2] == []


def test_cli_dry_branches_before_all_writes_and_publisher_calls(database, monkeypatch):
    from engine.publish import claim_guard, history_writer, telegram_publisher, x_publisher
    for module, name in [(claim_guard, 'claim_publication'), (claim_guard, 'finish_publication'),
                         (history_writer, 'record_publish'), (x_publisher, 'publish_episode_x'),
                         (telegram_publisher, 'publish_episode_telegram')]:
        monkeypatch.setattr(module, name, MagicMock(side_effect=AssertionError('forbidden send')))
    monkeypatch.setattr(sys, 'argv', ['run_publish', '--episode', 'ICG-2026-05-10-001', '--channels', 'all'])
    run_publish.main()
    database[3].assert_not_called()
    assert Path('output/publish-preflight.json').exists()


def test_live_preflight_missing_assets_fails_before_logging(database, monkeypatch):
    Path(database[0]['slides_json'][0]['path']).unlink()
    monkeypatch.setenv('DRY_RUN', 'false')
    monkeypatch.setattr(sys, 'argv', ['run_publish', '--preflight-only', '--episode', 'ICG-2026-05-10-001'])
    with pytest.raises(SystemExit) as exc:
        run_publish.main()
    assert exc.value.code == 1
    database[3].assert_not_called()


def test_workflow_mode_and_gates():
    workflow = yaml.safe_load(Path('.github/workflows/publish_sns.yml').read_text())
    trigger = workflow.get('on', workflow.get(True))
    assert trigger['workflow_dispatch']['inputs']['dry_run']['options'] == ['auto', 'true', 'false']
    pre = workflow['jobs']['pre-check']
    assert 'secrets.DRY_RYN || secrets.DRY_RUN' in pre['env']['DRY_RUN']
    publish = workflow['jobs']['publish']
    assert publish['env']['DRY_RUN'] == "${{ needs.pre-check.outputs.execution_mode == 'dry' && 'true' || 'false' }}"
    steps = {s.get('name'): s for s in publish['steps']}
    for name in ['Anti-bot random delay', 'STEP 8 — Publish SNS']:
        assert steps[name]['if'] == "steps.readiness.outputs.allowed == 'true'"
    assert "env.DRY_RUN == 'false'" in steps['Notify Failure']['if']
    confirm = next(s for s in pre['steps'] if s.get('name', '').startswith('Confirm guard'))
    assert "steps.mode.outputs.execution_mode == 'live'" in confirm['if']
    for step in publish['steps'] + pre['steps']:
        assert '${{ inputs.' not in step.get('run', '')
