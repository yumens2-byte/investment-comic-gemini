"""Selective recovery keeps successful inputs immutable and never regenerates them."""
import copy
import hashlib
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from engine.image import gemini_client as adapter
from engine.image import recovery_service as service
from engine.image.generation_guard import GenerationHold, ProductionGenerationGuard
from engine.image.ref_loader import get_refs_for_panel
from engine.image.reviewed_inputs import reviewed_panel_prompts
from engine.publish.manifest import script_hash
from tests.test_common_image_recovery import recovery  # noqa: F401
from tests.test_image_adapter_guard_v2 import png


@pytest.fixture
def selective(recovery, monkeypatch, tmp_path):  # noqa: F811
    request, asset, calls, root = recovery
    source = asset["script_json"]
    evidence = {}
    for call in calls:
        if call["state"] != "success":
            continue
        call.update(token=f"token-{call['panel']}", scope=f"output/episodes/{source['date']}/panels")
        refs = get_refs_for_panel([c["char_id"] for c in source["panels"][call["panel"] - 1]["characters"]])
        prompt = f"Original approved input for panel {call['panel']}"
        guard = ProductionGenerationGuard(scope=call["scope"], panel=call["panel"],
                                         prompt=prompt + "\n[model=gemini-2.5-flash-image;aspect=None]", refs=refs)
        call["fingerprint"] = guard.fingerprint
        evidence[str(call["panel"])] = {"call": call, "payload": {
            "prompt_text": prompt, "model": "gemini-2.5-flash-image", "aspect_ratio": None,
            "ref_sha256": [hashlib.sha256(ref.read_bytes()).hexdigest() for ref in refs]}}
    monkeypatch.setattr(service, "success_inputs", lambda rows: evidence)
    scenes = json.loads(Path(request["scenes_path"]).read_text())
    document = {"version": "selective-image-scenes-1",
                "panels": {k: v for k, v in scenes.items() if k not in request["success_hashes"]}}
    # Keep repository-path validation active without changing tracked fixtures.
    scene_path = Path("config/image-recovery/scenes/pilot-test.json")
    monkeypatch.setattr(service, "_repo_file", lambda *args: tmp_path / "scenes.json")
    (tmp_path / "scenes.json").write_text(json.dumps(document))
    request.update(scenes_path=scene_path.as_posix(), preserve_successful_images=True,
                   scenes_sha256=hashlib.sha256((tmp_path / "scenes.json").read_bytes()).hexdigest())
    return request, asset, calls, root, evidence


def test_selective_candidate_preserves_all_success_inputs_and_public_story(selective):
    request, asset, calls, root, evidence = selective
    before = copy.deepcopy(asset)
    _, candidate = service.prepare_request(request, asset, calls, root)
    assert asset == before
    for item in candidate["_reviewed_image_inputs"]["panels"]:
        if str(item["idx"]) in evidence:
            source_panel = asset["script_json"]["panels"][item["idx"] - 1]
            assert candidate["panels"][item["idx"] - 1] == source_panel
            assert item["reuse_only"] is True
            assert item["fingerprint"] == evidence[str(item["idx"])]["call"]["fingerprint"]
            assert item["prompt_text"] == evidence[str(item["idx"])]["payload"]["prompt_text"]
    assert candidate["panels"][6:] == asset["script_json"]["panels"][6:]


@pytest.mark.parametrize("change", ["prompt", "ref", "panel", "output", "coverage"])
def test_preserved_identity_drift_stops_before_provider(selective, monkeypatch, change):
    request, asset, calls, root, evidence = selective
    _, candidate = service.prepare_request(request, asset, calls, root)
    if change in {"prompt", "ref"}:
        evidence["1"]["payload"]["prompt_text" if change == "prompt" else "ref_sha256"] = "changed"
        with pytest.raises(GenerationHold):
            service.prepare_request(request, asset, calls, root)
        return
    if change == "panel":
        candidate["panels"][0]["action"] = "changed scene"
    elif change == "output":
        candidate["_reviewed_image_inputs"]["panels"][0]["output_hash"] = "0" * 64
    else:
        candidate["_scene_contracts"].pop("1")
    candidate["_reviewed_image_inputs"]["script_hash"] = script_hash(candidate)
    monkeypatch.setenv("ICG_GENERATION_REVISION", "2")
    with pytest.raises(GenerationHold):
        reviewed_panel_prompts(candidate)


def test_reuse_only_missing_receipt_never_reserves_or_calls_provider(monkeypatch, tmp_path):
    guard = Mock()
    guard.reuse.return_value = False
    provider = Mock(side_effect=AssertionError("provider forbidden"))
    monkeypatch.setattr(adapter, "_get_client", provider)
    with pytest.raises(GenerationHold, match="regeneration forbidden"):
        adapter.generate_panel(1, "Original input", [], tmp_path, tmp_path / "run.log",
                               guard=guard, reuse_only=True)
    guard.reserve.assert_not_called()
    provider.assert_not_called()


def test_all_protected_images_verified_before_any_new_generation(monkeypatch, tmp_path):
    generate = Mock(side_effect=GenerationHold("missing protected artifact"))
    monkeypatch.setattr(adapter, "generate_panel", generate)
    panels = [{"panel_idx": 1, "prompt_text": "new scene", "ref_image_paths": []},
              {"panel_idx": 2, "prompt_text": "original", "ref_image_paths": [], "reuse_only": True}]
    with pytest.raises(GenerationHold):
        adapter.generate_episode(panels, tmp_path)
    assert generate.call_args.kwargs["panel_idx"] == 2
    assert generate.call_args.kwargs["reuse_only"] is True
    assert generate.call_count == 1


def test_image_stage_propagates_reuse_only_and_preserves_png_bytes(selective, monkeypatch):
    from engine.persist import asset_writer
    from scripts import run_market
    request, asset, calls, root, _ = selective
    _, candidate = service.prepare_request(request, asset, calls, root)
    monkeypatch.setenv("ICG_GENERATION_REVISION", "2")
    monkeypatch.delenv("PERFORMANCE_SPEC_ENABLED", raising=False)
    generated = Mock(return_value=([Path(f"P{i}.png") for i in range(1, 7)], .04))
    monkeypatch.setattr(adapter, "generate_episode", generated)
    monkeypatch.setattr(asset_writer, "patch_by_episode", Mock())
    run_market.step_image(request["episode_date"], request["episode_id"], {}, candidate, Mock())
    tasks = generated.call_args.args[0]
    assert [p["panel_idx"] for p in tasks if p.get("reuse_only")] == [1, 2, 3]
    assert [p["panel_idx"] for p in tasks if not p.get("reuse_only")] == [4, 5, 6]


def test_real_adapter_only_calls_provider_for_missing_panel(monkeypatch, tmp_path):
    panels = tmp_path / "panels"
    panels.mkdir()
    protected = [1, 2, 3, 4, 6]
    for idx in protected:
        (panels / f"P{idx}.png").write_bytes(png())
    before = {idx: (panels / f"P{idx}.png").read_bytes() for idx in protected}
    guards = {}
    def make_guard(**kwargs):
        idx = kwargs["panel"]
        g = Mock()
        g.reuse.return_value = idx in protected
        guards[idx] = g
        return g
    monkeypatch.setattr(adapter, "ProductionGenerationGuard", make_guard)
    monkeypatch.setattr(adapter, "_get_client", Mock())
    provider = Mock(return_value=(png(), 100, 1290))
    monkeypatch.setattr(adapter, "_generate_one", provider)
    tasks = [{"panel_idx": idx, "prompt_text": f"scene {idx}", "ref_image_paths": [],
              "reuse_only": idx in protected} for idx in range(1, 7)]
    paths, cost = adapter.generate_episode(tasks, panels)
    assert len(paths) == 6 and all(paths) and cost > 0
    provider.assert_called_once()
    assert provider.call_args.args[1] == "scene 5"
    for idx in protected:
        guards[idx].reserve.assert_not_called()
        assert (panels / f"P{idx}.png").read_bytes() == before[idx]
