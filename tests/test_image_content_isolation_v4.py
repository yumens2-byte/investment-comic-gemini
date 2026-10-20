"""Offline tests for explicitly gated, settled content refusal isolation."""
import json
from unittest.mock import Mock

import pytest

from engine.image import gemini_client as adapter
from engine.image.generation_guard import GenerationHold, ProductionGenerationGuard
from engine.image.provider_outcome import SettlementReceipt, content_isolation_v4_enabled
from tests.test_image_adapter_guard_v2 import png


@pytest.fixture
def isolation(monkeypatch, tmp_path):
    monkeypatch.setenv("ICG_IMAGE_OUTCOME_V3_ENABLED", "true")
    monkeypatch.setenv("ICG_IMAGE_CONTENT_ISOLATION_V4_ENABLED", "true")
    monkeypatch.setenv("ICG_IMAGE_RETRY_V2_ENABLED", "false")
    monkeypatch.setenv("ICG_GENERATION_REVISION", "1")
    monkeypatch.setattr(adapter, "PROVIDER_REFUSAL_PATH", tmp_path / "refusal.jsonl")
    monkeypatch.setattr(adapter, "_get_client", Mock())
    gen = Mock(side_effect=adapter.NoImageResponse("PROHIBITED_CONTENT", 100, 0))
    monkeypatch.setattr(adapter, "_generate_one", gen)
    guard = Mock()
    guard.revision = 1
    guard.reuse.return_value = False
    guard.reserve.return_value = "token"
    guard.finish_outcome.return_value = SettlementReceipt(
        "CONTENT_REVIEW_REQUIRED", "terminal", .00003, "CONTENT_REVIEW_REQUIRED")
    def run():
        return adapter.generate_panel(
            4, "fictional adults observe separate data", [],
            tmp_path / "panels", tmp_path / "calls.jsonl", guard=guard)
    return run, guard, gen


def test_settled_refusal_is_typed_once_without_retry(isolation):
    run, guard, gen = isolation
    with pytest.raises(adapter.SettledContentRefusal) as exc:
        run()
    assert exc.value.cost == pytest.approx(.00003)
    assert exc.value.provider_reason == "PROHIBITED_CONTENT"
    gen.assert_called_once()
    guard.finish_outcome.assert_called_once()
    assert [c.args[1] for c in guard.store_attempt_diagnostic.call_args_list] == ["inputs", "refusal"]


@pytest.mark.parametrize("failure", ["unknown", "diagnostics", "settlement", "bad_receipt", "revision"])
def test_unconfirmed_outcomes_never_become_isolatable(isolation, failure):
    run, guard, gen = isolation
    if failure == "unknown":
        gen.side_effect = adapter.NoImageResponse("PROHIBITED_CONTENT", 0, 0)
    elif failure == "diagnostics":
        guard.store_attempt_diagnostic.side_effect = [None, GenerationHold("diagnostics missing")]
    elif failure == "settlement":
        guard.finish_outcome.side_effect = GenerationHold("unknown settlement")
    elif failure == "revision":
        guard.revision = 2
    else:
        guard.finish_outcome.return_value = {}
    with pytest.raises(GenerationHold) as exc:
        run()
    assert not isinstance(exc.value, adapter.SettledContentRefusal)
    gen.assert_called_once()


def test_disabled_flag_retains_existing_stop(isolation, monkeypatch):
    run, _, gen = isolation
    monkeypatch.setenv("ICG_IMAGE_CONTENT_ISOLATION_V4_ENABLED", "false")
    with pytest.raises(GenerationHold) as exc:
        run()
    assert not isinstance(exc.value, adapter.SettledContentRefusal)
    gen.assert_called_once()


@pytest.mark.parametrize("held", [(4,), (2, 4)])
def test_episode_finishes_independent_panels_but_never_succeeds(monkeypatch, tmp_path, held):
    monkeypatch.setenv("ICG_IMAGE_OUTCOME_V3_ENABLED", "false")
    attempted = []
    def generate(**kw):
        idx = kw["panel_idx"]
        attempted.append(idx)
        if idx in held:
            raise adapter.SettledContentRefusal("review required", .001, "PROHIBITED_CONTENT")
        path = tmp_path / f"P{idx}.png"
        path.write_bytes(png())
        return path, .04
    monkeypatch.setattr(adapter, "generate_panel", generate)
    with pytest.raises(GenerationHold, match="CONTENT_REVIEW_REQUIRED"):
        adapter.generate_episode([{"panel_idx": i} for i in range(1, 7)], tmp_path)
    summary = json.loads((tmp_path / "generation-summary.json").read_text())
    assert attempted == list(range(1, 7))
    assert summary["successful_images"] == 6 - len(held)
    assert summary["not_attempted_images"] == 0
    assert summary["held_panels"] == list(held)
    assert summary["held_panel"] == held[0]
    assert summary["complete"] is False and summary["cost_complete"] is True
    assert summary["cost_usd"] == pytest.approx(.04 * (6 - len(held)) + .001 * len(held))
    assert all((tmp_path / f"P{i}.png").exists() == (i not in held) for i in range(1, 7))


def test_reconciliation_after_isolated_refusal_still_stops(monkeypatch, tmp_path):
    monkeypatch.setenv("ICG_IMAGE_OUTCOME_V3_ENABLED", "false")
    calls = []
    def generate(**kw):
        idx = kw["panel_idx"]
        calls.append(idx)
        if idx == 2:
            raise adapter.SettledContentRefusal("review required", .001, "SAFETY")
        if idx == 3:
            raise GenerationHold("scope requires reconciliation")
        return tmp_path / "P1.png", .04
    monkeypatch.setattr(adapter, "generate_panel", generate)
    with pytest.raises(GenerationHold, match="scope requires reconciliation"):
        adapter.generate_episode([{"panel_idx": i} for i in range(1, 7)], tmp_path)
    summary = json.loads((tmp_path / "generation-summary.json").read_text())
    assert calls == [1, 2, 3]
    assert summary["held_panel"] == 3
    assert summary["provider_reason"] is None
    assert summary["result_code"] == "IMAGE_INCOMPLETE"
    assert summary["not_attempted_images"] == 3
    assert summary["cost_complete"] is False and summary["complete"] is False


def test_missing_v4_capability_stops_before_reservation(isolation, monkeypatch, tmp_path):
    guard = ProductionGenerationGuard(scope="output/episodes/2026-10-21/panels",
                                      panel=5, prompt="observation", refs=[])
    rpc = Mock(side_effect=[{"version": "image-outcome-3"}, {}])
    monkeypatch.setattr(guard, "_rpc", rpc)
    with pytest.raises(GenerationHold, match="provider not called"):
        guard.reuse(tmp_path / "P5.png")
    assert [c.args[0] for c in rpc.call_args_list] == [
        "image_generation_outcome_v3_capability", "image_generation_content_isolation_v4_capability"]


def test_v4_routes_both_inspect_and_atomic_reserve(isolation, monkeypatch, tmp_path):
    guard = ProductionGenerationGuard(scope="output/episodes/2026-10-21/panels",
                                      panel=5, prompt="observation", refs=[])
    responses = {
        "image_generation_outcome_v3_capability": {"version": "image-outcome-3"},
        "image_generation_content_isolation_v4_capability": {"version": "image-content-isolation-4"},
        "image_generation_inspect_independent_v4": {},
        "image_generation_reserve_independent_v4": {"token": "token"},
    }
    rpc = Mock(side_effect=lambda name, params: responses[name])
    monkeypatch.setattr(guard, "_rpc", rpc)
    assert guard.reuse(tmp_path / "P5.png") is False
    assert guard.reserve() == "token"
    assert rpc.call_args.args[1]["p_revision"] == 1


def test_feature_flag_requires_outcome_contract(monkeypatch):
    monkeypatch.setenv("ICG_IMAGE_CONTENT_ISOLATION_V4_ENABLED", "true")
    monkeypatch.setenv("ICG_IMAGE_OUTCOME_V3_ENABLED", "false")
    with pytest.raises(GenerationHold, match="requires outcome"):
        content_isolation_v4_enabled()
