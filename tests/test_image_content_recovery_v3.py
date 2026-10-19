"""Offline contracts: no paid API calls or production DB access."""
import json
from unittest.mock import Mock

import pytest

from engine.image import gemini_client as adapter
from engine.image import prompt_builder
from engine.image.action_safety import check_action
from engine.image.generation_guard import GenerationHold, ProductionGenerationGuard
from engine.image.provider_outcome import SettlementReceipt
from engine.image.scene_contract import text_hash, validate_scene_contracts, validate_scene_text
from scripts.prepare_image_recovery import prepare, validate_candidate

LONG_ATTACK = ("Debt Titan hurls a cascading wave of luminous debt-chain energy across the corridor "
               "toward Iron Securities Nuna; she raises her shield and braces")
ACTION = "Iron Securities Nuna and Debt Titan remain still beside a separate display."
SETTING = "A fictional financial control room with abstract unlabelled diagrams."
NOTE = "Reviewed stationary display scene; preserve cast and unresolved shield clue."


def fixture_script():
    panel = {"idx": 1, "panel_type": "BATTLE", "action": ACTION, "setting": SETTING,
             "characters": [], "narration": "The shield clue remains unresolved."}
    contract = {"version": "scene-contract-1", "panel_idx": 1, "actor_ids": [],
        "visual_mode": "SYMBOLIC_STANDOFF", "interaction": "OBSERVE_SEPARATE_DISPLAY",
        "target_kind": "DISPLAY", "physical_contact": False, "weapon_discharge": False,
        "injury": "NONE", "required_story_facts": ["shield_clue"], "review_evidence": NOTE,
        "action_sha256": text_hash(ACTION), "setting_sha256": text_hash(SETTING)}
    return {"episode_id": "ICG-2026-10-20-001", "date": "2026-10-20", "event_type": "BATTLE",
        "_state_candidate": {"version": "state-candidate-1"}, "panels": [panel],
        "_scene_contracts": {"1": contract}}


@pytest.mark.parametrize("action", [LONG_ATTACK, "Debt Titan hurls energy toward Iron Securities Nuna",
                                         LONG_ATTACK.replace("hurls", "ｈｕｒｌｓ")])
def test_verbose_and_unicode_directed_attacks_are_not_exempt(action):
    assert "ACTION_ATTACK_ON_CHARACTER" in {v.rule for v in check_action(action)}


@pytest.mark.parametrize("text", [ACTION, "No attacks, weapon discharge or injury.",
    "A camera shot frames the analyst.", "The analyst marks the strike price."])
def test_non_contact_scene_language(text):
    validate_scene_text(text, 1)


@pytest.mark.parametrize("text", [LONG_ATTACK, "Hero punches the console.",
    "No attacks but the hero fires her rifle.", "The figures are clashing.",
    "Hero hits the console.", "Hero swings her sword."])
def test_scene_contract_rejects_contact_even_if_self_declared_safe(text):
    with pytest.raises(GenerationHold):
        validate_scene_text(text, 1)


@pytest.mark.parametrize("change", [
    lambda s: s["_scene_contracts"].clear(),
    lambda s: s["panels"][0].update(action="Changed action"),
    lambda s: s["_scene_contracts"]["1"].update(physical_contact="false"),
    lambda s: s["_scene_contracts"]["1"].update(target_kind="PROP"),
    lambda s: s["_scene_contracts"]["1"].update(actor_ids=["invented"]),
])
def test_contract_coverage_type_cast_and_text_binding(change):
    source = fixture_script()
    change(source)
    with pytest.raises(GenerationHold):
        validate_scene_contracts(source)


def test_builder_suppresses_combat_staging_and_checks_runtime_style(monkeypatch):
    script = fixture_script()
    monkeypatch.setattr(prompt_builder, "_get_style_block", lambda: "Original bold ink illustration")
    monkeypatch.setattr(prompt_builder, "_get_negative_block", lambda: "No real people")
    monkeypatch.setattr(prompt_builder, "_get_panel_visual_spec", lambda _: "COMPOSITION: characters clashing")
    prompt = prompt_builder.build_for_episode(script, battle_outcome="DRAW")[0].prompt_text
    assert ACTION in prompt and SETTING in prompt
    assert "characters clashing" not in prompt
    monkeypatch.setattr(prompt_builder, "_get_style_block", lambda: "The hero fires her rifle")
    with pytest.raises(GenerationHold):
        prompt_builder.build_for_episode(script)


def test_offline_recovery_preserves_public_story_and_fixes_all_inputs(monkeypatch):
    monkeypatch.setattr("scripts.prepare_image_recovery.get_refs_for_panel", lambda _: [])
    monkeypatch.setattr("engine.image.reviewed_inputs.get_refs_for_panel", lambda _: [])
    source = fixture_script()
    scenes = {"1": {"action": ACTION, "setting": SETTING, "prompt_text": SETTING + "\n" + ACTION,
                    "contract": source["_scene_contracts"]["1"]}}
    candidate = prepare(source, scenes, 2, actor="operator", note=NOTE)
    validate_candidate(candidate)
    assert candidate["panels"] == source["panels"]
    assert candidate["_state_candidate"] == source["_state_candidate"]
    assert "_generation_revision" not in source
    assert len(candidate["_reviewed_image_inputs"]["panels"]) == 1
    candidate["panels"][0]["action"] = "Changed action"
    with pytest.raises(GenerationHold):
        validate_candidate(candidate)
    with pytest.raises(GenerationHold):
        prepare(source, {}, 2, actor="operator", note=NOTE)


def test_recovery_changed_prompt_does_not_match_scene(monkeypatch):
    monkeypatch.setattr("scripts.prepare_image_recovery.get_refs_for_panel", lambda _: [])
    source = fixture_script()
    scenes = {"1": {"action": ACTION, "setting": SETTING, "prompt_text": "some other scene",
                     "contract": source["_scene_contracts"]["1"]}}
    with pytest.raises(GenerationHold, match="exact action"):
        prepare(source, scenes, 2, actor="operator", note=NOTE)


def test_v3_receipt_distinguishes_settled_content_from_unknown():
    receipt = {"settled": True, "state": "terminal", "result_code": "CONTENT_REVIEW_REQUIRED",
               "hold_code": "CONTENT_REVIEW_REQUIRED", "cost_usd": .0007752, "retry_allowed": False}
    assert SettlementReceipt.parse(receipt).cost_usd == .0007752
    with pytest.raises(GenerationHold, match="PROVIDER_OUTCOME_UNKNOWN"):
        SettlementReceipt.parse({**receipt, "state": "unknown", "result_code": "PROVIDER_OUTCOME_UNKNOWN",
                                 "hold_code": "PROVIDER_OUTCOME_UNKNOWN"})
    with pytest.raises(GenerationHold):
        SettlementReceipt.parse({**receipt, "settled": False})


def test_guard_v3_sends_exact_reservation_identity(monkeypatch):
    monkeypatch.setenv("ICG_IMAGE_OUTCOME_V3_ENABLED", "true")
    guard = ProductionGenerationGuard(scope="output/episodes/2026-10-20/panels",
                                      panel=1, prompt="observation", refs=[])
    rpc = Mock(return_value={"settled": True, "state": "terminal", "result_code": "CONTENT_REVIEW_REQUIRED",
                            "hold_code": "CONTENT_REVIEW_REQUIRED", "retry_allowed": False, "cost_usd": .001})
    monkeypatch.setattr(guard, "_rpc", rpc)
    guard.finish_outcome("token", state="terminal", actual_cost=.001, reason="SAFETY")
    name, args = rpc.call_args.args
    assert name == "image_generation_finish_outcome_v3"
    assert args["p_token"] == "token" and args["p_fingerprint"] == guard.fingerprint
    assert args["p_reason"] == "SAFETY" and args["p_revision"] == 1


def test_v3_missing_database_contract_blocks_before_reservation(monkeypatch, tmp_path):
    monkeypatch.setenv("ICG_IMAGE_OUTCOME_V3_ENABLED", "true")
    guard = ProductionGenerationGuard(scope="output/episodes/2026-10-20/panels",
                                      panel=1, prompt="observation", refs=[])
    rpc = Mock(return_value={})
    monkeypatch.setattr(guard, "_rpc", rpc)
    with pytest.raises(GenerationHold, match="provider not called"):
        guard.reuse(tmp_path / "P1.png")
    assert rpc.call_args.args == ('image_generation_outcome_v3_capability', {})


def test_no_image_settles_before_local_log_io(monkeypatch, tmp_path):
    monkeypatch.setenv("ICG_IMAGE_RETRY_V2_ENABLED", "false")
    monkeypatch.setattr(adapter, "_get_client", Mock())
    monkeypatch.setattr(adapter, "PROVIDER_REFUSAL_PATH", tmp_path / "refusal.jsonl")
    gen = Mock(side_effect=adapter.NoImageResponse("SAFETY", 100, 0))
    monkeypatch.setattr(adapter, "_generate_one", gen)
    guard = Mock()
    guard.reuse.return_value = False
    guard.reserve.return_value = "token"
    order = []
    guard.finish.side_effect = lambda *a, **kw: order.append("settle")
    def fail_log(*args):
        order.append("log")
        raise OSError("disk full")
    monkeypatch.setattr(adapter, "_write_jsonl_log", fail_log)
    with pytest.raises(GenerationHold, match="CONTENT_REVIEW_REQUIRED"):
        adapter.generate_panel(1, ACTION, [], tmp_path / "panels", tmp_path / "run.log", guard=guard)
    assert order == ["settle", "log"]
    assert gen.call_count == 1


def test_refusal_v3_is_not_reported_as_unsettled(monkeypatch, tmp_path):
    monkeypatch.setenv("ICG_IMAGE_OUTCOME_V3_ENABLED", "true")
    monkeypatch.setenv("ICG_IMAGE_RETRY_V2_ENABLED", "false")
    monkeypatch.setattr(adapter, "_get_client", Mock())
    monkeypatch.setattr(adapter, "PROVIDER_REFUSAL_PATH", tmp_path / "refusal.jsonl")
    gen = Mock(side_effect=adapter.NoImageResponse("PROHIBITED_CONTENT", 100, 0))
    monkeypatch.setattr(adapter, "_generate_one", gen)
    guard = Mock()
    guard.reuse.return_value = False
    with pytest.raises(GenerationHold, match="CONTENT_REVIEW_REQUIRED"):
        adapter.generate_panel(1, ACTION, [], tmp_path / "panels", tmp_path / "run.log", guard=guard)
    row = json.loads((tmp_path / "run.log").read_text())
    assert row["settlement_status"] == "SETTLED"
    guard.finish_outcome.assert_called_once()
    gen.assert_called_once()


def test_reviewed_response_file_failure_cannot_prevent_settlement(monkeypatch, tmp_path):
    from pathlib import Path

    from tests.test_image_adapter_guard_v2 import png
    from tests.test_image_retry_defense import bundle

    monkeypatch.setenv("ICG_IMAGE_RETRY_V2_ENABLED", "true")
    monkeypatch.setenv("ICG_IMAGE_DIAGNOSTICS_DIR", str(tmp_path / "private"))
    monkeypatch.setattr(adapter, "_get_client", Mock())
    monkeypatch.setattr(adapter, "PROVIDER_REFUSAL_PATH", tmp_path / "refusal.jsonl")
    ref = tmp_path / "ref.png"
    ref.write_bytes(png())
    guard = Mock()
    guard.reuse.return_value = False
    guard.select_retry_variant.return_value = 0
    guard.retry_attempts_used = 0
    gen = Mock(side_effect=adapter.NoImageResponse("SAFETY", 100, 0))
    monkeypatch.setattr(adapter, "_generate_one", gen)
    original = Path.open
    def response_disk_failure(path, *args, **kwargs):
        if path.name.startswith("response-"):
            guard.finish_reviewed.assert_called_once()
            raise OSError("disk full")
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, "open", response_disk_failure)
    with pytest.raises(GenerationHold, match="after settlement"):
        adapter.generate_panel(1, ACTION, [ref], tmp_path / "panels", tmp_path / "run.log",
                               guard=guard, retry_plan=bundle([ACTION, "Quiet observation"], ref))
    assert gen.call_count == 1
    guard.finish_reviewed.assert_called_once()
