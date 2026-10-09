"""Regression for scheduled Run Market: no reviewed plan and no paid requests."""
import hashlib
import json
from unittest.mock import Mock

import pytest

from engine.image import gemini_client as adapter
from engine.image.generation_guard import GenerationHold, ProductionGenerationGuard
from engine.narrative.production_quality import (
    build_production_retry_feedback,
    validate_production_episode,
)
from tests.test_image_adapter_guard_v2 import png

REAL_GENERATE_ONE = adapter._generate_one

@pytest.fixture
def ordinary(monkeypatch, tmp_path):
    monkeypatch.setenv("ICG_IMAGE_RETRY_V2_ENABLED", "false")
    monkeypatch.setenv("GITHUB_RUN_ID", "scheduled-run")
    monkeypatch.setattr(adapter, "PROVIDER_REFUSAL_PATH", tmp_path / "refusals.jsonl")
    guard = Mock()
    guard.reuse.return_value = False
    guard.reserve.return_value = "token"
    ref = tmp_path / "ref.png"
    ref.write_bytes(png())
    gen = Mock(return_value=(png(), 100, 1290))
    monkeypatch.setattr(adapter, "_get_client", Mock())
    monkeypatch.setattr(adapter, "_generate_one", gen)

    def run():
        return adapter.generate_panel(2, "adult fictional analyst observes abstract data",
                                      [ref], tmp_path / "panels", tmp_path / "run.log",
                                      guard=guard)
    return run, guard, gen, ref, tmp_path


def test_default_inputs_persist_before_provider_call(ordinary):
    run, guard, gen, ref, _ = ordinary
    order = Mock()
    order.attach_mock(guard.store_attempt_diagnostic, "diagnostic")
    order.attach_mock(gen, "provider")
    run()
    assert [c[0] for c in order.mock_calls] == ["diagnostic", "provider"]
    token, kind, payload = guard.store_attempt_diagnostic.call_args.args
    assert (token, kind) == ("token", "inputs")
    assert payload["prompt_text"] == gen.call_args.args[1]
    assert payload["ref_sha256"] == [hashlib.sha256(ref.read_bytes()).hexdigest()]
    assert payload["run_id"] == "scheduled-run"


def test_default_refusal_details_survive_settlement_hold(ordinary):
    run, guard, gen, _, _ = ordinary
    gen.side_effect = adapter.NoImageResponse("FinishReason.PROHIBITED_CONTENT", 2070, 0,
                                             {"finish_message": "provider evidence"})
    guard.finish.side_effect = GenerationHold("provider outcome or cost requires reconciliation")
    with pytest.raises(GenerationHold, match="provider_reason=.*PROHIBITED_CONTENT; panel=2"):
        run()
    assert gen.call_count == 1
    assert [c.args[1] for c in guard.store_attempt_diagnostic.call_args_list] == ["inputs", "refusal"]
    payload = guard.store_attempt_diagnostic.call_args.args[2]
    assert payload["details"]["finish_message"] == "provider evidence"
    assert payload["cost_usd"] == pytest.approx(0.000621)


def test_diagnostic_failure_releases_uncalled_reservation_at_zero_cost(ordinary):
    run, guard, gen, _, _ = ordinary
    guard.store_attempt_diagnostic.side_effect = GenerationHold("DB unavailable")
    with pytest.raises(GenerationHold, match="provider not called"):
        run()
    gen.assert_not_called()
    assert guard.finish.call_args.kwargs == {
        "state": "failed", "actual_cost": 0.0, "output_hash": None,
    }


def test_refusal_evidence_failure_still_settles_once_without_retry(ordinary):
    run, guard, gen, _, _ = ordinary
    guard.store_attempt_diagnostic.side_effect = [None, GenerationHold("storage unavailable")]
    gen.side_effect = adapter.NoImageResponse("SAFETY", 100, 0)
    with pytest.raises(GenerationHold, match="provider_reason=SAFETY"):
        run()
    guard.finish.assert_called_once()
    assert guard.finish.call_args.kwargs["state"] == "terminal"
    assert gen.call_count == 1


def test_success_reuse_does_not_write_another_attempt(ordinary):
    run, guard, gen, _, root = ordinary
    path = root / "panels/P2.png"
    path.parent.mkdir()
    path.write_bytes(png())
    guard.reuse.return_value = True
    assert run() == (path, 0.0)
    guard.store_attempt_diagnostic.assert_not_called()
    gen.assert_not_called()


def test_default_summary_identifies_held_and_unattempted_panels(monkeypatch, tmp_path):
    monkeypatch.setenv("ICG_IMAGE_RETRY_V2_ENABLED", "false")

    def generate(**kwargs):
        if kwargs["panel_idx"] == 2:
            raise GenerationHold("provider refused image")
        return tmp_path / "P1.png", 0.04

    gen = Mock(side_effect=generate)
    monkeypatch.setattr(adapter, "generate_panel", gen)
    with pytest.raises(GenerationHold):
        adapter.generate_episode([{"panel_idx": i} for i in (1, 2, 3)], tmp_path)
    summary = json.loads((tmp_path / "generation-summary.json").read_text())
    assert [p["status"] for p in summary["panels"]] == ["success", "held", "not_attempted"]
    assert summary["complete"] is False and summary["cost_complete"] is False
    assert summary["held_panel"] == 2 and summary["cost_usd"] == 0.04
    assert gen.call_count == 2


@pytest.mark.parametrize("response", [
    {"candidates": [{"finishReason": "PROHIBITED_CONTENT", "finishMessage": "details",
                     "safetyRatings": [{"category": "evidence"}]}]},
    {"promptFeedback": {"blockReason": "PROHIBITED_CONTENT",
                        "safetyRatings": [{"category": "evidence"}]}},
])
def test_rest_response_refusal_and_safety_evidence_are_preserved(response):
    assert adapter._response_finish_reason(response) == "PROHIBITED_CONTENT"
    details = adapter._response_diagnostics(response)
    assert details["safety_ratings"] or details["prompt_safety_ratings"]


@pytest.mark.parametrize("reason", ["IMAGE_RECITATION", "ESCALATION", "PUP_LIMITED_DISABLED"])
def test_review_required_reasons_are_terminal_even_with_inline_output(monkeypatch, ordinary, reason):
    run, _, gen, _, _ = ordinary
    client = Mock()
    client.models.generate_content.return_value = {
        "candidates": [{"finishReason": reason,
                        "content": {"parts": [{"inline_data": {"data": png()}}]}}],
        "usageMetadata": {"promptTokenCount": 100},
    }
    with pytest.raises(adapter.NoImageResponse):
        REAL_GENERATE_ONE(client, "observation", [])
    gen.side_effect = adapter.NoImageResponse(reason, 100, 0)
    with pytest.raises(GenerationHold):
        run()
    assert gen.call_count == 1


def test_guard_attempt_diagnostic_is_bound_to_reservation(monkeypatch):
    guard = ProductionGenerationGuard(scope="output/episodes/2026-10-09/panels",
                                      panel=2, prompt="observation", refs=[])
    rpc = Mock(return_value={"stored": True})
    monkeypatch.setattr(guard, "_rpc", rpc)
    guard.store_attempt_diagnostic("token", "inputs", {"prompt_text": "observation"})
    name, args = rpc.call_args.args
    assert name == "image_generation_store_attempt_diagnostic"
    assert args["p_token"] == "token" and args["p_fingerprint"] == guard.fingerprint
    rpc.return_value = {"stored": False}
    with pytest.raises(GenerationHold, match="persistence not confirmed"):
        guard.store_attempt_diagnostic("token", "inputs", {})


def test_observation_conflict_reaches_narrative_regeneration_before_image():
    script = {"_episode_decision": {"scenario_type": "NO_BATTLE", "action_mode": "OBSERVATION"},
              "panels": [{"idx": 4, "panel_type": "TENSION", "characters": [],
                          "action": "Hero raises both fists and drives them into holographic columns"}]}
    violations = validate_production_episode(script, scenario_type="NO_BATTLE")
    assert "OBSERVATION_ACTION_CONFLICT" in {v.code for v in violations}
    assert "OBSERVATION IMAGE FIX" in build_production_retry_feedback(violations)
    script["panels"][0]["action"] = "Hero adjusts the console and marks a diagram"
    assert "OBSERVATION_ACTION_CONFLICT" not in {
        v.code for v in validate_production_episode(script, scenario_type="NO_BATTLE")}


def test_runtime_style_retains_technique_without_contradictory_identity(monkeypatch):
    from engine.image.prompt_builder import _get_style_block

    monkeypatch.setattr("engine.common.notion_loader.load_image_prompt_blocks", lambda: {
        "GLOBAL_STYLE_BLOCK": "DC Comics graphic novel style — Frank Miller / Jim Lee quality.\n"
        "hero faces RIGHT.\n== PROPORTION MANDATE ==\nLIMBS: LONG arms and legs.\n"
        "APPLY to ALL characters in EVERY panel.\n== END PROPORTION MANDATE =="})
    style = _get_style_block()
    assert "hero faces RIGHT" in style and "cel-shaded" in style
    assert "humanoid characters only" in style and "exact REF anatomy" in style
    assert "DC Comics" not in style and "Jim Lee" not in style
