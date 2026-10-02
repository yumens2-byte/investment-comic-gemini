"""DR-01: a provider refusal reason survives settlement and reaches logs and alerts."""
import json
import logging
from unittest.mock import Mock

import pytest

from engine.image import gemini_client as adapter
from engine.image.generation_guard import GenerationHold
from tests.test_image_adapter_guard_v2 import png

REASON = "FinishReason.PROHIBITED_CONTENT"


@pytest.fixture
def setup(monkeypatch, tmp_path):
    """Same offline harness as test_image_adapter_guard_v2: no paid requests."""
    guard = Mock()
    guard.reuse.return_value = False
    guard.reserve.side_effect = ["r1", "r2", "r3"]
    monkeypatch.setattr(adapter, "_get_client", lambda: Mock())
    gen = Mock(return_value=(png(), 100, 1290))
    monkeypatch.setattr(adapter, "_generate_one", gen)
    ref = tmp_path / "hero.png"
    ref.write_bytes(png())

    def run():
        return adapter.generate_panel(1, "hero and villain", [ref], tmp_path / "panels",
                                      tmp_path / "run.log", guard=guard)
    return run, guard, gen, tmp_path


@pytest.fixture
def refusal_path(monkeypatch, tmp_path):
    path = tmp_path / "provider-refusals.jsonl"
    monkeypatch.setattr(adapter, "PROVIDER_REFUSAL_PATH", path)
    monkeypatch.setenv("GITHUB_RUN_ID", "37028115726")
    return path


def test_refusal_reason_in_hold_when_settlement_reports_hold(setup, refusal_path, caplog):
    run, guard, gen, root = setup
    gen.side_effect = adapter.NoImageResponse(REASON, 2629, 0)
    guard.finish.side_effect = GenerationHold("provider outcome or cost requires reconciliation")
    with caplog.at_level(logging.WARNING), pytest.raises(GenerationHold) as raised:
        run()
    message = str(raised.value)
    assert "provider outcome or cost requires reconciliation" in message
    assert f"provider_reason={REASON}" in message and "panel=1" in message
    assert gen.call_count == 1  # terminal: never retried
    assert guard.finish.call_args.kwargs["state"] == "terminal"
    assert "PROVIDER_REFUSAL" in caplog.text and REASON in caplog.text
    record = json.loads(refusal_path.read_text().splitlines()[0])
    assert record == {"code": "PROVIDER_REFUSAL", "panel": 1, "finish_reason": REASON,
                      "cost_usd": adapter._calc_cost(2629, 0), "run_id": "37028115726"}


def test_refusal_reason_in_hold_when_settlement_succeeds(setup, refusal_path):
    run, guard, gen, _ = setup
    gen.side_effect = adapter.NoImageResponse(REASON, 100, 0)
    with pytest.raises(GenerationHold, match="provider refused image; provider_reason="):
        run()


def test_nonterminal_noimage_is_not_recorded_as_refusal(setup, refusal_path):
    run, guard, gen, _ = setup
    gen.side_effect = adapter.NoImageResponse("STOP", 100, 30)
    result, _ = run()
    assert result is None and gen.call_count == 3
    assert not refusal_path.exists()


def test_refusal_evidence_write_failure_does_not_change_outcome(setup, monkeypatch, tmp_path):
    run, guard, gen, _ = setup
    blocker = tmp_path / "file"
    blocker.write_text("x")
    monkeypatch.setattr(adapter, "PROVIDER_REFUSAL_PATH", blocker / "nested.jsonl")
    gen.side_effect = adapter.NoImageResponse(REASON, 100, 0)
    with pytest.raises(GenerationHold, match="provider_reason="):
        run()
    assert guard.finish.call_args.kwargs["state"] == "terminal"


def test_failure_alert_lists_refusals_for_this_run_only(monkeypatch, tmp_path):
    from scripts import notify_failure

    path = tmp_path / "provider-refusals.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in [
        {"code": "PROVIDER_REFUSAL", "panel": 3, "finish_reason": REASON, "run_id": "1"},
        {"code": "PROVIDER_REFUSAL", "panel": 9, "finish_reason": "OTHER", "run_id": "2"},
        "not-a-record",
    ]))
    monkeypatch.setattr(adapter, "PROVIDER_REFUSAL_PATH", path)
    monkeypatch.setenv("GITHUB_RUN_ID", "1")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test")
    monkeypatch.setenv("TELEGRAM_FREE_CHANNEL_ID", "test")
    sent = {}
    monkeypatch.setattr(notify_failure, "_send_telegram",
                        lambda token, channel, text: sent.setdefault("text", text) or True)
    monkeypatch.setattr("sys.argv", ["notify_failure"])
    with pytest.raises(SystemExit):
        notify_failure.main()
    assert "P3: FinishReason.PROHIBITED_CONTENT" in sent["text"]
    assert "P9" not in sent["text"]
