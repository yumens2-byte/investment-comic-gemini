"""Regression for a regenerated narrative colliding with already paid panels."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from engine.image.generation_guard import GenerationHold
from scripts import run_market
from scripts.market_preflight import assert_image_ledger_allowed, inspect_market


def tables(monkeypatch, *, calls=(), script=None):
    from engine.common import supabase_client

    asset = {"episode_no": 1, "status": "narrative_done", "script_json": script}
    result = {}
    for name, rows in {"episode_assets": [asset], "image_generation_calls": list(calls)}.items():
        table = Mock()
        for method in ("select", "eq", "limit", "order"):
            getattr(table, method).return_value = table
        table.execute.return_value = SimpleNamespace(data=rows)
        result[name] = table
    monkeypatch.setattr(supabase_client, "icg_table", lambda name: result[name])
    return result


def script(revision=1):
    return {"date": "2026-10-02", "episode_id": "ICG-2026-10-02-001",
            "panels": [{"idx": 1, "narration": "unanswered question"}],
            "_generation_revision": revision,
            "_state_candidate": {"version": "state-candidate-1"}}


@pytest.mark.parametrize("stage", ["all", "narrative", "persist", "recovery"])
def test_started_revision_cannot_overwrite_narrative(monkeypatch, stage):
    monkeypatch.setenv("ICG_GENERATION_REVISION", "2")
    tables(monkeypatch, calls=[{"state": "success", "revision": 2}])
    with pytest.raises(run_market.GenerationBlocked, match="already_started"):
        assert_image_ledger_allowed("2026-10-02", "ICG-2026-10-02-001", stage)


def test_old_successes_allow_explicit_recovery_and_image_resume(monkeypatch):
    monkeypatch.setenv("ICG_GENERATION_REVISION", "2")
    tables(monkeypatch, calls=[{"state": "success", "revision": 1}])
    assert_image_ledger_allowed("2026-10-02", "ICG-2026-10-02-001", "recovery")
    assert_image_ledger_allowed("2026-10-02", "ICG-2026-10-02-001", "image")


@pytest.mark.parametrize("state", ["reserved", "unknown", "terminal"])
def test_revision_increase_cannot_bypass_reconciliation(monkeypatch, state):
    monkeypatch.setenv("ICG_GENERATION_REVISION", "2")
    tables(monkeypatch, calls=[{"state": state, "revision": 1}])
    with pytest.raises(run_market.GenerationBlocked, match="reconciliation_hold"):
        assert_image_ledger_allowed("2026-10-02", "ICG-2026-10-02-001", "recovery")


def test_recovery_requires_explicit_new_revision(monkeypatch):
    monkeypatch.delenv("ICG_GENERATION_REVISION", raising=False)
    tables(monkeypatch)
    with pytest.raises(run_market.GenerationBlocked, match="explicit_generation_revision"):
        assert_image_ledger_allowed("2026-10-02", "ICG-2026-10-02-001", "recovery")


def test_preflight_blocks_repeat_before_any_expensive_stage(monkeypatch):
    monkeypatch.setenv("ICG_GENERATION_REVISION", "1")
    tables(monkeypatch, calls=[{"state": "success", "revision": 1}])
    report = inspect_market("2026-10-02", "all", dry_run=False)
    assert report["allowed"] is False
    assert report["status"] == "blocked"
    assert report["paid_calls"] == report["database_writes"] == 0


def test_image_loads_exact_persisted_episode(monkeypatch):
    monkeypatch.setenv("ICG_GENERATION_REVISION", "2")
    saved = script(2)
    result = tables(monkeypatch, script=saved)
    assert run_market._assert_image_stage_inputs("2026-10-02", "ICG-2026-10-02-001", {}) == saved
    assert [call.args for call in result["episode_assets"].eq.call_args_list] == [
        ("episode_date", "2026-10-02"), ("episode_no", 1)]


@pytest.mark.parametrize("change,match", [
    ({"_generation_revision": 1}, "differs from persisted"),
    ({"_generation_revision": True}, "differs from persisted"),
    ({"_state_candidate": {}}, "current narrative persistence"),
    ({"episode_id": "ICG-2026-10-02-002"}, "identity mismatch"),
    ({"date": "2026-10-01"}, "identity mismatch"),
    ({"panels": []}, "persisted narrative"),
    ({"resolved_threads": ["still unknown"]}, "unverified_resolved_thread"),
])
def test_stale_or_wrong_script_stops_before_paid_call(monkeypatch, change, match):
    monkeypatch.setenv("ICG_GENERATION_REVISION", "2")
    saved = {**script(2), **change}
    tables(monkeypatch, script=saved)
    with pytest.raises(GenerationHold, match=match):
        run_market._assert_image_stage_inputs("2026-10-02", "ICG-2026-10-02-001", {})


def test_recovery_runs_narrative_persist_image_in_order(monkeypatch, tmp_path):
    import sys

    from engine.common import logger

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DRY_RUN", "false")
    monkeypatch.setenv("ICG_GENERATION_REVISION", "2")
    monkeypatch.setattr(sys, "argv", ["run_market", "--stage", "recovery", "--date", "2026-10-02"])
    tables(monkeypatch, calls=[{"state": "success", "revision": 1}])
    monkeypatch.setattr(logger, "StepLogger", Mock())
    from engine.persist import asset_writer
    monkeypatch.setattr(asset_writer, "load_analysis_ctx", lambda _: {"event_type": "BATTLE"})
    monkeypatch.setattr(asset_writer, "save_narrative_script", Mock())
    order = []
    def narrative(*_args):
        order.append("narrative")
        return script(2)
    monkeypatch.setattr(run_market, "step_narrative", narrative)
    monkeypatch.setattr(run_market, "step_persist", lambda *_: order.append("persist"))
    monkeypatch.setattr(run_market, "step_image", lambda *_: order.append("image"))
    monkeypatch.setattr(run_market, "step_data", Mock(side_effect=AssertionError("unexpected data")))
    monkeypatch.setattr(run_market, "step_analysis", Mock(side_effect=AssertionError("unexpected analysis")))
    run_market.main()
    assert order == ["narrative", "persist", "image"]
