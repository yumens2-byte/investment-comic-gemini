"""Reviewed dynamic repair alternatives; no paid provider or production DB calls."""
import copy
import hashlib
import json
from unittest.mock import Mock

import pytest

from engine.image import gemini_client as adapter
from engine.image.generation_guard import GenerationHold
from engine.image.repair_plan import digest, make_bundle, prepare, register, validate_bundle
from engine.image.retry_policy import ReviewedRetryPlan
from tests.test_image_adapter_guard_v2 import png


@pytest.fixture
def reviewed(tmp_path):
    ref = tmp_path / "hero.png"
    ref.write_bytes(png())
    cast = [{"char_id": "CHAR_HERO_002", "role": "hero", "form": "form1", "position": "LEFT"}]
    panel = {"idx": 4, "panel_type": "BATTLE", "characters": cast,
             "action": "Iron Securities Nuna braces behind her shield.",
             "setting": "A fictional control room.",
             "narration": "The inner shield crack remains unnoticed.", "key_text": "A hidden clue."}
    actions = [("TURN", "DISPLAY", "Iron Securities Nuna turns toward a separate display."),
               ("PROP_INSPECTION", "PROP", "Iron Securities Nuna tilts her shield to inspect its front surface.")]
    repairs = []
    for motion, target, action in actions:
        repairs.append({"action": action, "setting": panel["setting"], "cast": copy.deepcopy(cast),
                        "story_facts": ["unnoticed shield crack"], "camera": "OVER_SHOULDER",
                        "motion": motion, "target_kind": target, "physical_contact": False,
                        "weapon_discharge": False, "injury": "NONE",
                        "change_note": "Replace direct confrontation with a different non-contact action.",
                        "prompt_text": panel["setting"] + "\n" + action +
                        "\nPreserve the unnoticed shield crack and the exact reference identity. "
                        "No injury, contact, text or weapon discharge."})
    original = panel["setting"] + "\n" + panel["action"]
    bundle = make_bundle(panel, original, [ref], repairs, story_facts=["unnoticed shield crack"],
                         actor="reviewer", note="Reviewed two non-contact actions preserving the hidden shield clue.")
    return panel, original, ref, repairs, bundle


def resign(bundle):
    bundle["plan_id"] = digest({k: v for k, v in bundle.items() if k != "plan_id"})


def test_dynamic_alternatives_bind_cast_story_and_source(reviewed):
    panel, original, ref, _, bundle = reviewed
    result = ReviewedRetryPlan.from_bundle(bundle, original, [ref])
    assert len(result.prompts) == 3
    assert bundle["review"]["source"]["cast"] == panel["characters"]
    assert bundle["review"]["source_sha256"] == digest(bundle["review"]["source"])


@pytest.mark.parametrize("change", ["same_action", "static", "cast", "facts", "injury",
                                    "contact", "unsafe", "source_hash", "camera_only"])
def test_unreviewed_or_cosmetic_repair_is_rejected(reviewed, change):
    _, original, ref, _, bundle = reviewed
    r = bundle["review"]["repairs"][0]
    if change in {"same_action", "camera_only"}:
        r["action"] = bundle["review"]["source"]["action"]
        r["camera"] = "WIDE"
    elif change == "static":
        r["action"] = "Iron Securities Nuna stands still beside a display."
    elif change == "cast":
        r["cast"] = []
    elif change == "facts":
        r["story_facts"] = []
    elif change == "injury":
        r["injury"] = "PRESENT"
    elif change == "contact":
        r["physical_contact"] = True
    elif change == "unsafe":
        r["action"] = "Iron Securities Nuna turns and fires her rifle toward Debt Titan."
    else:
        bundle["review"]["source_sha256"] = "0" * 64
    # Re-signing cannot bless a semantically ineligible structured scene.
    r["prompt_text"] = r["setting"] + "\n" + r["action"] + "\nunnoticed shield crack"
    bundle["prompts"][1] = r["prompt_text"]
    resign(bundle)
    with pytest.raises(GenerationHold):
        validate_bundle(bundle, original, [ref])


def test_duplicate_motion_and_reference_drift_block(reviewed):
    _, original, ref, _, bundle = reviewed
    bundle["review"]["repairs"][1]["motion"] = "TURN"
    resign(bundle)
    with pytest.raises(GenerationHold, match="DYNAMIC_ACTION"):
        validate_bundle(bundle, original, [ref])
    bundle["review"]["repairs"][1]["motion"] = "PROP_INSPECTION"
    resign(bundle)
    ref.write_bytes(b"changed")
    with pytest.raises(GenerationHold, match="REFERENCES_CHANGED"):
        validate_bundle(bundle, original, [ref])


def test_refusal_repairs_action_then_succeeds_once(reviewed, monkeypatch, tmp_path):
    _, original, ref, _, bundle = reviewed
    monkeypatch.setenv("ICG_IMAGE_RETRY_V2_ENABLED", "true")
    monkeypatch.setenv("ICG_IMAGE_DIAGNOSTICS_DIR", str(tmp_path / "private"))
    monkeypatch.setattr(adapter, "PROVIDER_REFUSAL_PATH", tmp_path / "refusals")
    monkeypatch.setattr(adapter, "_get_client", Mock())
    gen = Mock(side_effect=[adapter.NoImageResponse("PROHIBITED_CONTENT", 100, 0),
                            (png(), 100, 1290)])
    monkeypatch.setattr(adapter, "_generate_one", gen)
    guard = Mock()
    guard.reuse.return_value = False
    guard.select_retry_variant.return_value = 0
    guard.retry_attempts_used = 0
    path, cost = adapter.generate_panel(4, original, [ref], tmp_path / "panels",
                                       tmp_path / "log", guard=guard,
                                       retry_plan=bundle, sleeper=Mock())
    assert path.read_bytes() == png()
    assert gen.call_count == 2
    assert gen.call_args_list[1].args[1] == bundle["review"]["repairs"][0]["prompt_text"]
    assert cost == pytest.approx(adapter._calc_cost(100, 0) + adapter._calc_cost(100, 1290))
    assert guard.reserve.call_count == 2


def test_preparation_preserves_episode_and_compositor_cards(reviewed, monkeypatch):
    panel, original, ref, repairs, _ = reviewed
    monkeypatch.setattr("engine.image.ref_loader.get_refs_for_panel", lambda _: [ref])
    panel["idx"] = 1
    source = {"date": "2026-10-22", "_generation_revision": 1, "panels": [
        panel, {"idx": 2, "panel_type": "DISCLAIMER", "narration": "unchanged", "characters": []}]}
    before = copy.deepcopy(source)
    spec = {"repairs": repairs, "story_facts": ["unnoticed shield crack"], "actor": "reviewer",
            "note": "Reviewed changed actions with preserved hidden shield clue."}
    candidate, fingerprints = prepare(source, {"1": original}, {"1": spec})
    assert source == before and candidate["panels"] == before["panels"]
    assert len(fingerprints["1"]) == 3
    assert len(candidate["_reviewed_image_retry_plans"]["1"]["prompts"]) == 3
    suffix = "\n[model=gemini-2.5-flash-image;aspect=None]"
    assert fingerprints["1"][0] == hashlib.sha256(json.dumps(
        [original + suffix, [hashlib.sha256(ref.read_bytes()).hexdigest()]],
        ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def test_registration_failure_never_reports_success(monkeypatch):
    client = Mock()
    client.schema.return_value = client
    client.rpc.return_value.execute.return_value.data = {"hold": "source changed"}
    monkeypatch.setattr("engine.common.supabase_client.get_client", lambda: client)
    with pytest.raises(GenerationHold, match="REGISTRATION_REJECTED"):
        register({}, {}, {})
