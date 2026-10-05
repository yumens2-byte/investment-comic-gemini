"""Static checks on the side workflow and migration (K-1 isolation)."""
from __future__ import annotations

import re

import yaml

from sidestory.tests.conftest import REPO_ROOT, SIDE_ROOT
from sidestory.tests.diff_guard import violations

RUN_WF = REPO_ROOT / ".github/workflows/sidestory_run.yml"
MIGRATION = SIDE_ROOT / "migrations/0001_icg_side_schema.sql"


def test_run_workflow_isolation() -> None:
    text = RUN_WF.read_text(encoding="utf-8")
    wf = yaml.safe_load(text)
    job = wf["jobs"]["sidestory"]
    assert job["env"]["SUPABASE_SCHEMA"] == "icg_side"
    assert wf["concurrency"]["group"].startswith("sidestory-")
    assert wf[True]["schedule"][0]["cron"] == "17 1 * * 2,4"  # Tue/Thu 10:17 KST
    assert "SIDESTORY_SCHEDULE_ENABLED" in job["if"]
    for forbidden in ("X_API_KEY", "X_ACCESS_TOKEN", "TELEGRAM_FREE_CHANNEL_ID",
                      "TELEGRAM_PAID_CHANNEL_ID", "NOTION_TRACKER_DS"):
        assert forbidden not in text


def test_migration_never_writes_main_schema() -> None:
    sql = MIGRATION.read_text(encoding="utf-8").lower()
    for pattern in (r"\balter\s+table\s+icg\.", r"\binsert\s+into\s+icg\.", r"\bupdate\s+icg\.",
                    r"\bdelete\s+from\s+icg\.", r"\bdrop\s+\w+\s+(if\s+exists\s+)?icg\.",
                    r"\bcreate\s+(or\s+replace\s+)?(table|view|function|index)\s+icg\."):
        assert not re.search(pattern, sql), pattern
    created = re.findall(r"\bcreate\s+(?:unique\s+)?(?:table|view|function|index)\s+(\S+)", sql)
    for name in created:
        if "." in name and not name.startswith("side_"):
            assert name.startswith("icg_side."), name


def test_diff_guard_rules() -> None:
    assert violations(["sidestory/core/x.py", ".github/workflows/sidestory_run.yml"]) == []
    assert violations(["engine/a.py"]) == []  # main-only change sets are out of scope
    assert violations(["sidestory/core/x.py", "engine/a.py"]) == ["engine/a.py"]
