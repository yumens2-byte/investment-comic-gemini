"""The production market beta must never generate, mutate, or create log state."""
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from scripts import run_market


class ReadOnlyTable:
    """Deliberately lacks insert/update/upsert/delete and RPC methods."""

    def __init__(self, rows):
        self.rows = rows

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, *_args, **_kwargs):
        return self

    def order(self, *_args, **_kwargs):
        return self

    def limit(self, *_args, **_kwargs):
        return self

    def execute(self):
        return SimpleNamespace(data=self.rows)


@pytest.fixture
def immutable(monkeypatch, tmp_path):
    from engine.common import logger, supabase_client

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DRY_RUN", "true")
    forbidden = Mock(side_effect=AssertionError("mutable or paid operation called in dry-run"))
    for stage in ("step_data", "step_analysis", "step_narrative", "step_persist", "step_image"):
        monkeypatch.setattr(run_market, stage, forbidden)
    monkeypatch.setattr(logger, "StepLogger", forbidden)
    monkeypatch.setattr(supabase_client, "get_client", forbidden)
    monkeypatch.setattr(supabase_client, "icg_table", lambda _table: ReadOnlyTable([]))
    return forbidden, tmp_path


@pytest.mark.parametrize("env", ["treu", "1", "yes", "", "truee"])
def test_invalid_dryrun_environment_rejected_before_mutation(immutable, monkeypatch, env):
    forbidden, root = immutable
    monkeypatch.setenv("DRY_RUN", env)
    monkeypatch.setattr(sys, "argv", ["run_market", "--stage", "all", "--date", "2026-10-01"])
    with pytest.raises((ValueError, RuntimeError, SystemExit)):
        run_market.main()
    forbidden.assert_not_called()
    assert not (root / "output" / "episodes").exists()


@pytest.mark.parametrize("target", ["2026-02-30", "2026-1-1", "20261001", "../2026-10-01", "not-a-date"])
def test_invalid_date_rejected_before_logging(immutable, monkeypatch, target):
    forbidden, root = immutable
    monkeypatch.setattr(sys, "argv", ["run_market", "--stage", "all", "--date", target])
    with pytest.raises((ValueError, RuntimeError, SystemExit)):
        run_market.main()
    forbidden.assert_not_called()
    assert not (root / "output" / "episodes").exists()


@pytest.mark.parametrize("stage", ["all", "data", "analysis", "narrative", "persist", "image", "recovery"])
def test_dry_run_never_enters_mutable_stages(immutable, monkeypatch, stage, capsys):
    import json

    forbidden, root = immutable
    monkeypatch.setattr(sys, "argv", ["run_market", "--stage", stage, "--date", "2026-10-01"])
    run_market.main()
    forbidden.assert_not_called()
    report = json.loads(capsys.readouterr().out)
    assert report["mode"] == "dry_run"
    assert report["requested_stage"] == stage
    assert report["database_writes"] == report["paid_calls"] == report["publishes"] == 0
    assert report["stage_execution"] == "not_executed_read_only_preflight"
    assert report["pipeline_readiness"] == "incomplete"
    assert not (root / "output" / "episodes").exists()


def test_explicit_dryrun_flag_works_when_env_false(immutable, monkeypatch, capsys):
    import json

    forbidden, _ = immutable
    monkeypatch.setenv("DRY_RUN", "false")
    monkeypatch.setattr(sys, "argv", ["run_market", "--dry-run", "--date", "2026-10-01"])
    run_market.main()
    assert json.loads(capsys.readouterr().out)["mode"] == "dry_run"
    forbidden.assert_not_called()


def test_published_episode_allows_inspection_only(immutable, monkeypatch, capsys):
    import json

    from engine.common import supabase_client

    forbidden, _ = immutable
    published = [{"episode_no": 7, "status": "published"}]
    cached = [{"analysis_ctx_json": {"event_type": "RATE_UP"},
               "narrative_script_json": {"panels": [{"panel_idx": 1}]}}]
    tables = {"episode_assets": published, "daily_snapshots": [{"snapshot_date": "2026-10-01"}],
              "daily_analysis": cached}
    monkeypatch.setattr(supabase_client, "icg_table", lambda table: ReadOnlyTable(tables.get(table, [])))
    monkeypatch.setattr(sys, "argv", ["run_market", "--stage", "all", "--date", "2026-10-01"])
    run_market.main()
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "pass"
    assert report["episode_id"] == "ICG-2026-10-01-007"
    assert report["live_generation_allowed"] is False
    assert report["live_block_reason"] == "already_published"
    assert report["pipeline_readiness"] == "ready"
    assert report["allowed"] is True
    forbidden.assert_not_called()


def test_dry_db_failure_is_not_success(immutable, monkeypatch, capsys):
    import json

    from engine.common import supabase_client

    forbidden, _ = immutable
    monkeypatch.setattr(supabase_client, "icg_table", Mock(side_effect=ConnectionError("private-provider-url")))
    monkeypatch.setattr(sys, "argv", ["run_market", "--date", "2026-10-01"])
    with pytest.raises(SystemExit) as exc:
        run_market.main()
    assert exc.value.code == 1
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "failed"
    assert report["allowed"] is False
    assert "private-provider-url" not in str(report)
    forbidden.assert_not_called()


def test_live_preflight_published_cannot_mutate(immutable, monkeypatch, capsys):
    import json

    from engine.common import supabase_client

    forbidden, _ = immutable
    monkeypatch.setenv("DRY_RUN", "false")
    monkeypatch.setattr(supabase_client, "icg_table", lambda _: ReadOnlyTable(
        [{"episode_no": 7, "status": "published"}]
    ))
    monkeypatch.setattr(sys, "argv", ["run_market", "--preflight-only", "--date", "2026-10-01"])
    run_market.main()
    report = json.loads(capsys.readouterr().out)
    assert report["mode"] == "live_preflight"
    assert report["status"] == "blocked"
    assert report["allowed"] is False
    forbidden.assert_not_called()


@pytest.mark.parametrize("value", ["serialized dict", [], 7])
def test_malformed_cached_analysis_is_failure(immutable, monkeypatch, capsys, value):
    import json

    from engine.common import supabase_client

    forbidden, _ = immutable
    monkeypatch.setattr(supabase_client, "icg_table", lambda table: ReadOnlyTable(
        [{"analysis_ctx_json": value}] if table == "daily_analysis" else []
    ))
    monkeypatch.setattr(sys, "argv", ["run_market", "--date", "2026-10-01"])
    with pytest.raises(SystemExit):
        run_market.main()
    assert json.loads(capsys.readouterr().out)["status"] == "failed"
    forbidden.assert_not_called()


@pytest.mark.parametrize("state", ["reserved", "unknown", "terminal"])
@pytest.mark.parametrize("dry_run", [True, False])
def test_generation_ledger_hold_blocks_live_only(immutable, monkeypatch, capsys, state, dry_run):
    import json

    from engine.common import supabase_client

    forbidden, _ = immutable
    monkeypatch.setenv("DRY_RUN", str(dry_run).lower())
    monkeypatch.setattr(supabase_client, "icg_table", lambda table: ReadOnlyTable(
        [{"state": state}] if table == "image_generation_calls" else []
    ))
    monkeypatch.setattr(sys, "argv", ["run_market", "--preflight-only", "--date", "2026-10-01"])
    run_market.main()
    report = json.loads(capsys.readouterr().out)
    assert report["live_generation_allowed"] is False
    assert report["live_block_reason"] == "image_generation_reconciliation_hold"
    assert report["allowed"] is dry_run
    assert report["status"] == ("pass" if dry_run else "blocked")
    assert report["database_writes"] == report["paid_calls"] == report["publishes"] == 0
    forbidden.assert_not_called()


@pytest.mark.parametrize("rows", [None, "invalid", [{"state": "typo"}], [{}]])
def test_invalid_generation_ledger_never_reports_pass(immutable, monkeypatch, capsys, rows):
    import json

    from engine.common import supabase_client

    forbidden, _ = immutable
    monkeypatch.setattr(supabase_client, "icg_table", lambda table: ReadOnlyTable(
        rows if table == "image_generation_calls" else []
    ))
    monkeypatch.setattr(sys, "argv", ["run_market", "--date", "2026-10-01"])
    with pytest.raises(SystemExit) as exc:
        run_market.main()
    assert exc.value.code == 1
    assert json.loads(capsys.readouterr().out)["status"] == "failed"
    forbidden.assert_not_called()


def test_generation_ledger_db_error_never_reports_pass(immutable, monkeypatch, capsys):
    import json

    from engine.common import supabase_client

    forbidden, _ = immutable

    def table(name):
        if name == "image_generation_calls":
            raise ConnectionError("sensitive-database-error")
        return ReadOnlyTable([])

    monkeypatch.setattr(supabase_client, "icg_table", table)
    monkeypatch.setattr(sys, "argv", ["run_market", "--date", "2026-10-01"])
    with pytest.raises(SystemExit):
        run_market.main()
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "failed"
    assert report["allowed"] is False
    assert "sensitive-database-error" not in str(report)
    forbidden.assert_not_called()


@pytest.mark.parametrize("target", ["20261001", "2026-02-30", "../../other"])
def test_live_invalid_date_rejected_before_logger(immutable, monkeypatch, target):
    forbidden, root = immutable
    monkeypatch.setenv("DRY_RUN", "false")
    monkeypatch.setattr(sys, "argv", ["run_market", "--date", target])
    with pytest.raises(SystemExit):
        run_market.main()
    forbidden.assert_not_called()
    assert not (root / "output").exists()


def test_latest_snapshot_error_cannot_fallback_in_beta(immutable, monkeypatch, capsys):
    import json

    from engine.common import supabase_client

    forbidden, _ = immutable

    def table(name):
        if name == "daily_snapshots":
            raise ConnectionError("latest date unavailable")
        return ReadOnlyTable([])

    monkeypatch.setattr(supabase_client, "icg_table", table)
    monkeypatch.setattr(sys, "argv", ["run_market", "--stage", "image"])
    with pytest.raises(SystemExit):
        run_market.main()
    assert json.loads(capsys.readouterr().out)["status"] == "failed"
    forbidden.assert_not_called()
