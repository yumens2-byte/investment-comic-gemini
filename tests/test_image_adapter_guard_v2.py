"""Production image adapter safety contract, using no paid requests."""
import io
import json
from unittest.mock import Mock

import pytest
from PIL import Image

from engine.image import gemini_client as adapter
from engine.image.generation_guard import GenerationHold


def png():
    out = io.BytesIO()
    Image.new("RGB", (4, 4), "red").save(out, "PNG")
    return out.getvalue()


@pytest.fixture
def setup(monkeypatch, tmp_path):
    guard = Mock()
    guard.reuse.return_value = False
    guard.reserve.side_effect = ["r1", "r2", "r3"]
    client = Mock()
    monkeypatch.setattr(adapter, "_get_client", lambda: client)
    gen = Mock(return_value=(png(), 100, 1290))
    monkeypatch.setattr(adapter, "_generate_one", gen)
    ref = tmp_path / "hero.png"
    ref.write_bytes(png())

    def run(**kwargs):
        return adapter.generate_panel(1, "hero and villain", [ref], tmp_path / "panels",
                                      tmp_path / "run.log", guard=guard, **kwargs)
    return run, guard, gen, tmp_path


def test_success_reserved_and_durable(setup):
    run, guard, gen, _ = setup
    result, cost = run()
    assert result.read_bytes() == png()
    assert cost > 0
    assert gen.call_count == 1
    guard.reserve.assert_called_once()
    assert guard.finish.call_args.kwargs["state"] == "success"
    assert len(guard.finish.call_args.kwargs["output_hash"]) == 64


@pytest.mark.parametrize("exc", [TimeoutError("timeout"), ConnectionError("connection lost"),
                                   RuntimeError("500 backend error")])
def test_ambiguous_outcome_no_retry(setup, exc):
    run, guard, gen, root = setup
    gen.side_effect = exc
    with pytest.raises(GenerationHold):
        run()
    assert gen.call_count == 1
    assert guard.finish.call_args.kwargs["state"] == "unknown"
    assert guard.finish.call_args.kwargs["actual_cost"] is None
    assert json.loads((root / "run.log").read_text())["cost_usd"] is None


@pytest.mark.parametrize("message", ["quota exhausted", "billing budget", "safety policy", "invalid_argument"])
def test_terminal_error_aborts(setup, message):
    run, guard, gen, _ = setup
    gen.side_effect = RuntimeError(message)
    with pytest.raises(GenerationHold):
        run()
    assert gen.call_count == 1
    assert guard.finish.call_args.kwargs["state"] == "terminal"


def test_completed_noimage_retry_bounded_and_costed(setup):
    run, guard, gen, _ = setup
    gen.side_effect = adapter.NoImageResponse("STOP", 100, 30)
    result, cost = run()
    assert result is None
    assert gen.call_count == 3
    assert cost == pytest.approx(3 * adapter._calc_cost(100, 30))
    assert all(c.kwargs["actual_cost"] > 0 for c in guard.finish.call_args_list)


def test_noimage_policy_does_not_retry(setup):
    run, guard, gen, _ = setup
    gen.side_effect = adapter.NoImageResponse("SAFETY", 0, 0)
    with pytest.raises(GenerationHold):
        run()
    assert gen.call_count == 1


def test_corrupted_provider_data_not_persisted(setup):
    run, guard, gen, root = setup
    gen.return_value = b"broken", 100, 1290
    result, cost = run()
    assert result is None and cost > 0
    assert not (root / "panels/P1.png").exists()
    assert gen.call_count == 3
    assert all(c.kwargs["state"] == "failed" for c in guard.finish.call_args_list)


def test_missing_reference_precedes_paid_call(setup):
    run, guard, gen, root = setup
    (root / "hero.png").unlink()
    with pytest.raises(GenerationHold):
        run()
    gen.assert_not_called()
    guard.reserve.assert_not_called()


def test_reused_result_no_new_request(setup):
    run, guard, gen, root = setup
    target = root / "panels/P1.png"
    target.parent.mkdir()
    target.write_bytes(png())
    guard.reuse.return_value = True
    assert run() == (target, 0.0)
    gen.assert_not_called()
    guard.reserve.assert_not_called()


def test_guard_reservation_hold_never_falls_back(setup):
    run, guard, gen, _ = setup
    guard.reserve.side_effect = GenerationHold("budget")
    with pytest.raises(GenerationHold):
        run()
    gen.assert_not_called()


def test_never_overwrites_existing_file(setup):
    run, guard, gen, root = setup
    target = root / "panels/P1.png"
    target.parent.mkdir()
    target.write_bytes(b"existing")
    with pytest.raises(GenerationHold):
        run()
    assert target.read_bytes() == b"existing"
    assert gen.call_count == 1


def test_sdk_automatic_retries_disabled(monkeypatch):
    from google import genai
    client = Mock()
    monkeypatch.setenv("GEMINI_API_SUB_PAY_KEY", "offline-dummy")
    monkeypatch.setattr(genai, "Client", client)
    adapter._get_client()
    options = client.call_args.kwargs["http_options"]
    assert options.retry_options.attempts == 1
    assert options.timeout == 120000


def test_no_usage_cost_reconciliation_hold(setup):
    run, guard, gen, root = setup
    gen.side_effect = adapter.NoImageResponse("STOP", 0, 0)
    guard.finish.side_effect = GenerationHold("billing unknown")
    with pytest.raises(GenerationHold):
        run()
    assert gen.call_count == 1
    assert guard.finish.call_args.kwargs["actual_cost"] is None
    assert json.loads((root / "run.log").read_text())["cost_usd"] is None


def test_success_missing_usage_preserves_artifact_and_holds(setup):
    run, guard, gen, root = setup
    gen.return_value = png(), 0, 0
    guard.finish.side_effect = GenerationHold("billing unknown")
    with pytest.raises(GenerationHold):
        run()
    assert gen.call_count == 1
    assert (root / "panels/P1.png").read_bytes() == png()
    assert json.loads((root / "run.log").read_text())["status"] == "hold"


def test_prompt_feedback_block_is_terminal():
    response = {"prompt_feedback": {"block_reason": "BLOCKLIST"}}
    assert adapter._response_finish_reason(response) == "BLOCKLIST"
    assert adapter._terminal_error(adapter.NoImageResponse("BLOCKLIST", 0, 0))


def test_invalid_token_response_metadata_is_not_zero_cost_success(setup):
    run, guard, gen, root = setup
    gen.return_value = png(), 0, 0
    result, cost = run()
    assert result is not None
    assert cost > 0
    assert guard.finish.call_args.kwargs["actual_cost"] is None
    record = json.loads((root / "run.log").read_text())
    assert record["cost_usd"] is None
    assert record["estimated_cost_usd"] > 0
