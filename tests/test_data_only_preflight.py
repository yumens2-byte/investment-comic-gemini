"""Data refresh is independent of existing generation holds; paid stages stay blocked."""
from unittest.mock import Mock

import pytest

from scripts.market_preflight import inspect_market
from tests.test_run_market_image_recovery import tables


@pytest.mark.parametrize('state', ['reserved', 'unknown', 'terminal'])
def test_data_refresh_does_not_consume_or_clear_image_hold(monkeypatch, state):
    monkeypatch.setenv('ICG_GENERATION_REVISION', '1')
    database = tables(monkeypatch, calls=[{'state': state, 'revision': 1}])
    report = inspect_market('2026-10-02', 'data', dry_run=False)
    assert report['allowed'] is True
    assert report['data_collection_only'] is True
    assert report['live_generation_allowed'] is False
    assert report['database_writes'] == report['paid_calls'] == report['publishes'] == 0
    database['image_generation_calls'].execute.assert_not_called()
    for table in database.values():
        table.update.assert_not_called()
        table.delete.assert_not_called()


@pytest.mark.parametrize('stage', ['all', 'narrative', 'persist', 'image', 'recovery'])
def test_non_data_stages_still_hold_terminal_images(monkeypatch, stage):
    monkeypatch.setenv('ICG_GENERATION_REVISION', '1')
    tables(monkeypatch, calls=[{'state': 'terminal', 'revision': 1}])
    report = inspect_market('2026-10-02', stage, dry_run=False)
    assert report['allowed'] is False
    assert report['status'] == 'blocked'


def test_published_episode_allows_only_data_refresh(monkeypatch):
    database = tables(monkeypatch)
    database['episode_assets'].execute.return_value.data[0]['status'] = 'published'
    assert inspect_market('2026-10-02', 'data', dry_run=False)['allowed'] is True
    assert inspect_market('2026-10-02', 'all', dry_run=False)['allowed'] is False


def test_actual_data_stage_never_invokes_paid_or_episode_stages(monkeypatch, tmp_path):
    import sys

    from engine.common import logger
    from scripts import run_market

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('DRY_RUN', 'false')
    monkeypatch.setenv('FORCE_RUN', 'true')
    monkeypatch.setattr(sys, 'argv', ['run_market', '--stage', 'data', '--date', '2026-10-02'])
    tables(monkeypatch, calls=[{'state': 'terminal', 'revision': 1}])
    monkeypatch.setattr(logger, 'StepLogger', Mock())
    collection = Mock()
    monkeypatch.setattr(run_market, 'step_data', collection)
    for name in ('step_analysis', 'step_narrative', 'step_persist', 'step_image'):
        monkeypatch.setattr(run_market, name, Mock(side_effect=AssertionError('unexpected stage')))
    run_market.main()
    collection.assert_called_once()
