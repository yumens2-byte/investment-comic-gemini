import json
import sys
from unittest.mock import Mock

import pytest

from engine.quality import content_qc
from scripts import notify_failure


@pytest.fixture(autouse=True)
def isolate_evidence(monkeypatch, tmp_path):
    monkeypatch.setattr(content_qc, "WARNING_PATH", tmp_path / "warnings.jsonl")


def test_warning_retains_hold_and_writes_evidence(caplog):
    script = {"episode_id": "ICG-2026-10-02-001", "_recovery_qc": {"status": "HOLD"}}
    assert content_qc.require_content_ready(script)
    assert script["_recovery_qc"]["status"] == "HOLD"
    record = json.loads(content_qc.WARNING_PATH.read_text())
    assert record["code"] == "CONTENT_QC_WARNING"
    assert "CONTENT_QC_WARNING" in caplog.text


def test_evidence_write_failure_does_not_stop(monkeypatch, tmp_path):
    monkeypatch.setattr(content_qc, "WARNING_PATH", tmp_path)  # Directory is not writable as file.
    assert content_qc.require_content_ready({"_recovery_qc": None})


def test_invalid_narrative_structure_remains_an_error():
    with pytest.raises(ValueError, match="Malformed"):
        content_qc.require_content_ready(None)


def test_warning_notification_noop_without_findings(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["notify", "--qc-warnings"])
    send = Mock()
    monkeypatch.setattr(notify_failure, "_send_telegram", send)
    notify_failure.main()
    send.assert_not_called()


def test_warning_notification_keeps_existing_failure_notifier(monkeypatch):
    content_qc.require_content_ready({"_recovery_qc": None})
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test")
    monkeypatch.setenv("TELEGRAM_FREE_CHANNEL_ID", "test")
    send = Mock(return_value=True)
    monkeypatch.setattr(notify_failure, "_send_telegram", send)
    monkeypatch.setattr(sys, "argv", ["notify", "--qc-warnings"])
    with pytest.raises(SystemExit) as exited:
        notify_failure.main()
    assert exited.value.code == 0
    assert "QC 경고" in send.call_args.args[2]
    monkeypatch.setattr(sys, "argv", ["notify"])
    with pytest.raises(SystemExit):
        notify_failure.main()
    assert "파이프라인 실패" in send.call_args.args[2]


def test_workflows_keep_failure_and_add_warning_notifier():
    from pathlib import Path

    import yaml

    for name in ["run_market", "resume_episode", "publish_sns"]:
        workflow = yaml.safe_load(Path(f".github/workflows/{name}.yml").read_text())
        steps = [s for job in workflow["jobs"].values() for s in job.get("steps", [])]
        warnings = next(s for s in steps if s.get("name") == "Notify Content QC Warnings")
        assert "always()" in warnings["if"]
        assert "--qc-warnings" in warnings["run"]
        assert any(s.get("name") == "Notify Failure" and "failure()" in s["if"] for s in steps)
