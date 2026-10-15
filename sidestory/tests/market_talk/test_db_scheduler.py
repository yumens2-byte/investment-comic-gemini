"""On-time DB scheduler ticks must behave exactly like GitHub schedule events."""

import json

import yaml

from sidestory.market_talk import reporting
from sidestory.tests.conftest import REPO_ROOT, SIDE_ROOT

WF = REPO_ROOT / ".github/workflows/sidestory_market_talk.yml"
MIGRATION = next((SIDE_ROOT / "supabase/migrations").glob("*_market_talk_db_scheduler.sql"))


def workflow():
    return yaml.safe_load(WF.read_text(encoding="utf-8"))


def test_actions_owns_scheduling_and_reuses_worker():
    wf = workflow()
    assert "scheduler" not in wf[True]["workflow_dispatch"]["inputs"]
    assert wf["jobs"]["market-talk"]["uses"].endswith("sidestory_market_talk_execute.yml")
    assert wf[True]["schedule"][0]["cron"] == "7,27,47 4-8 * * 1-5"


def test_retirement_preserves_audit_and_other_cron():
    sql = next((SIDE_ROOT / "supabase/migrations").glob("*_remove_market_talk_db_scheduler.sql")).read_text()
    for name in ["icg_talk_dispatch", "icg_talk_dispatch_cutoff", "icg_talk_dispatch_reconcile"]:
        assert name in sql
    assert "cron.unschedule" in sql
    assert "drop table" not in sql.lower()
    assert "drop extension" not in sql.lower()


def test_missed_window_is_surfaced_as_warning(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "output").mkdir()
    (tmp_path / "output/market-talk-report.json").write_text(json.dumps({"status": "MISSED_WINDOW"}))
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    reporting.main()
    assert "::warning::" in capsys.readouterr().out
