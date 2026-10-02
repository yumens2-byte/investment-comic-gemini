"""Terminal receipt authorization never permits narrative replacement or unsettled calls."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from engine.image import recovery
from engine.image.generation_guard import GenerationHold
from scripts.market_preflight import assert_image_ledger_allowed
from scripts.run_market import GenerationBlocked
from tests.test_run_market_image_recovery import tables


@pytest.mark.parametrize('receipt', [None, [], {}, {'authorized': 'true'},
                                     {'authorized': True, 'hold': 'stale'}])
def test_receipt_fail_closed(monkeypatch, receipt):
    client = Mock()
    client.schema.return_value = client
    client.rpc.return_value.execute.return_value = SimpleNamespace(data=receipt)
    monkeypatch.setattr(recovery, 'get_client', lambda: client)
    with pytest.raises(GenerationHold):
        recovery.require_terminal_recovery('output/episodes/2026-10-02/panels', 3)


def test_backend_error_fail_closed(monkeypatch):
    monkeypatch.setattr(recovery, 'get_client', Mock(side_effect=RuntimeError('offline')))
    with pytest.raises(GenerationHold, match='unavailable'):
        recovery.require_terminal_recovery('output/episodes/2026-10-02/panels', 3)


def test_exact_receipt_request(monkeypatch):
    client = Mock()
    client.schema.return_value = client
    client.rpc.return_value.execute.return_value = SimpleNamespace(data={'authorized': True})
    monkeypatch.setattr(recovery, 'get_client', lambda: client)
    monkeypatch.setattr(recovery, 'get_schema', lambda: 'icg')
    recovery.require_terminal_recovery('output/episodes/2026-10-02/panels', 3)
    client.rpc.assert_called_once_with('image_generation_recovery_preflight',
                                      {'p_scope': 'output/episodes/2026-10-02/panels', 'p_revision': 3})


@pytest.mark.parametrize('stage', ['all', 'narrative', 'persist', 'recovery'])
def test_receipt_cannot_allow_narrative_mutation(monkeypatch, stage):
    monkeypatch.setenv('ICG_GENERATION_REVISION', '3')
    tables(monkeypatch, calls=[{'state': 'terminal', 'revision': 2}])
    receipt = Mock()
    monkeypatch.setattr(recovery, 'require_terminal_recovery', receipt)
    with pytest.raises(GenerationBlocked):
        assert_image_ledger_allowed('2026-10-02', 'episode', stage)
    receipt.assert_not_called()


def test_reviewed_receipt_allows_only_image_stage(monkeypatch):
    monkeypatch.setenv('ICG_GENERATION_REVISION', '3')
    tables(monkeypatch, calls=[{'state': 'terminal', 'revision': 2}])
    receipt = Mock()
    monkeypatch.setattr(recovery, 'require_terminal_recovery', receipt)
    assert_image_ledger_allowed('2026-10-02', 'episode', 'image')
    receipt.assert_called_once_with('output/episodes/2026-10-02/panels', 3)


@pytest.mark.parametrize('state', ['reserved', 'unknown'])
def test_receipt_cannot_allow_unsettled_call(monkeypatch, state):
    monkeypatch.setenv('ICG_GENERATION_REVISION', '3')
    tables(monkeypatch, calls=[{'state': 'terminal', 'revision': 2}, {'state': state, 'revision': 3}])
    receipt = Mock()
    monkeypatch.setattr(recovery, 'require_terminal_recovery', receipt)
    with pytest.raises(GenerationBlocked):
        assert_image_ledger_allowed('2026-10-02', 'episode', 'image')
    receipt.assert_not_called()


def test_absent_receipt_still_holds_image_stage(monkeypatch):
    monkeypatch.setenv('ICG_GENERATION_REVISION', '3')
    tables(monkeypatch, calls=[{'state': 'terminal', 'revision': 2}])
    monkeypatch.setattr(recovery, 'require_terminal_recovery', Mock(side_effect=GenerationHold('stale')))
    with pytest.raises(GenerationBlocked, match='reconciliation_hold'):
        assert_image_ledger_allowed('2026-10-02', 'episode', 'image')
