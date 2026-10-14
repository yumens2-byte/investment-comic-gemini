"""On-time DB scheduler ticks must behave exactly like GitHub schedule events."""

import json

import yaml

from sidestory.market_talk import reporting
from sidestory.tests.conftest import REPO_ROOT, SIDE_ROOT

WF = REPO_ROOT / ".github/workflows/sidestory_market_talk.yml"
MIGRATION = next((SIDE_ROOT / "supabase/migrations").glob("*_market_talk_db_scheduler.sql"))


def workflow():
    return yaml.safe_load(WF.read_text(encoding="utf-8"))


def test_scheduler_input_is_gated_by_schedule_variable():
    wf = workflow()
    assert wf[True]["workflow_dispatch"]["inputs"]["scheduler"]["default"] is False
    condition = wf["jobs"]["market-talk"]["if"]
    assert "!inputs.scheduler" in condition and "MARKET_TALK_SCHEDULE_ENABLED == 'true'" in condition


def test_scheduler_tick_uses_scheduled_stage_and_live_path():
    step = next(
        s for s in workflow()["jobs"]["market-talk"]["steps"] if s.get("name", "").startswith("Inspect")
    )
    env, script = step["env"], step["run"]
    assert "!inputs.scheduler" in env["REQUEST_STAGE"]
    assert "github.event_name == 'schedule'" in env["SCHEDULER_TICK"]
    assert "inputs.scheduler" in env["SCHEDULER_TICK"]
    assert '"$SCHEDULER_TICK" == "true" ]]; then args+=(--scheduled)' in script
    assert '"$SCHEDULER_TICK" == "true" || "$REQUEST_CONFIRM" == "YES"' in script
    assert '"$EVENT_NAME" == "schedule"' not in script


def test_migration_dispatches_only_this_workflow_with_scheduler_input():
    sql = MIGRATION.read_text(encoding="utf-8")
    assert "/repos/yumens2-byte/investment-comic-gemini/actions/workflows/sidestory_market_talk.yml/dispatches" in sql
    assert "jsonb_build_object('scheduler', 'true')" in sql
    assert "'github_icg_dispatch_pat'" in sql
    assert "'*/10 4-8 * * 1-5'" in sql and "'0 9 * * 1-5'" in sql
    assert "from public, anon, authenticated" in sql


def test_missed_window_is_surfaced_as_warning(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "output").mkdir()
    (tmp_path / "output/market-talk-report.json").write_text(json.dumps({"status": "MISSED_WINDOW"}))
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    reporting.main()
    assert "::warning::" in capsys.readouterr().out
