"""Release safety: live recovery stays bound to the reviewed source and saved PNGs."""
import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import yaml

from engine.image.generation_guard import GenerationHold
from engine.publish.manifest import script_hash
from scripts import recover_reviewed_images_release as release
from tests.test_image_adapter_guard_v2 import png


@pytest.fixture
def recovery(tmp_path):
    source = {"episode_id": "ICG-2026-10-21-001", "date": "2026-10-21",
              "_generation_revision": 1, "_state_candidate": {"version": "state-candidate-1"},
              "panels": []}
    for idx in range(1, 9):
        cast = [] if idx > 6 else [{"char_id": "CHAR_HERO_002", "role": "hero", "form": "form1"}]
        if idx <= 6 and idx != 2:
            cast.append({"char_id": "CHAR_VILLAIN_001", "role": "villain", "form": None})
        source["panels"].append({
            "idx": idx, "panel_type": "BATTLE" if idx <= 6 else
            "TEXT_CARD" if idx == 7 else "DISCLAIMER",
            "action": "original scene", "setting": "original setting",
            "narration": "Public story retained.", "characters": cast})
    request = json.loads(release.REQUEST_PATH.read_text())
    request["source_script_sha256"] = release.full_hash(source)
    request["public_script_sha256"] = script_hash(source)
    digest = hashlib.sha256(png()).hexdigest()
    request["success_hashes"] = {str(i): digest for i in (1, 2, 3)}
    root = tmp_path / "episodes"
    panels = root / "2026-10-21/panels"
    panels.mkdir(parents=True)
    for idx in (1, 2, 3):
        (panels / f"P{idx}.png").write_bytes(png())
    asset = {"script_json": source, "status": "narrative_done", "artifact_run_id": "39489073022"}
    calls = [{"panel": i, "revision": 1, "state": "success", "output_hash": digest}
             for i in (1, 2, 3)]
    calls.append({"panel": 4, "revision": 1, "state": "terminal",
                  "token": request["terminal_token"], "cost": request["terminal_cost_usd"],
                  "provider_reason": "PROHIBITED_CONTENT", "result_code": "CONTENT_REVIEW_REQUIRED",
                  "settled_at": "2026-10-20T20:10:03Z"})
    return request, asset, calls, root


def test_exact_source_and_canonical_refs_prepare_without_modifying_source(recovery):
    request, asset, calls, root = recovery
    original = copy.deepcopy(asset)
    source, candidate = release.prepare_release(request, asset, calls, root)
    assert asset == original
    assert candidate["_generation_revision"] == 2
    assert candidate["_image_recovery_review"]["require_manual_resume"] is True
    assert candidate["_state_candidate"] == source["_state_candidate"]
    assert len(candidate["_reviewed_image_inputs"]["panels"]) == 6
    assert candidate["panels"][6:] == source["panels"][6:]


@pytest.mark.parametrize("change", ["narrative", "state_candidate", "revision", "artifact",
                                    "terminal_cost", "terminal_token", "unknown_call", "already_started"])
def test_source_or_ledger_drift_blocks_before_registration(recovery, change):
    request, asset, calls, root = recovery
    if change == "narrative":
        asset["script_json"]["panels"][0]["narration"] = "changed"
    elif change == "state_candidate":
        asset["script_json"]["_state_candidate"]["changed"] = True
    elif change == "revision":
        asset["script_json"]["_generation_revision"] = 2
    elif change == "artifact":
        asset["artifact_run_id"] = "other"
    elif change == "terminal_cost":
        calls[-1]["cost"] += .001
    elif change == "terminal_token":
        calls[-1]["token"] = "other"
    elif change == "unknown_call":
        calls[0]["state"] = "unknown"
    else:
        calls.append({"panel": 5, "revision": 2, "state": "success"})
    with pytest.raises(GenerationHold):
        release.prepare_release(request, asset, calls, root)


def test_wrong_png_bytes_and_changed_scene_pack_block(recovery):
    request, asset, calls, root = recovery
    path = root / "2026-10-21/panels/P2.png"
    path.write_bytes(png() + b"changed")
    with pytest.raises(GenerationHold, match="PNG_CHANGED"):
        release.prepare_release(request, asset, calls, root)
    path.write_bytes(png())
    request["scenes_sha256"] = "0" * 64
    with pytest.raises(GenerationHold, match="SCENES_CHANGED"):
        release.prepare_release(request, asset, calls, root)


@pytest.mark.parametrize("live", [False, True])
def test_registration_is_explicit_and_occurs_after_private_candidate_validation(
        recovery, monkeypatch, tmp_path, live):
    request, asset, calls, root = recovery
    monkeypatch.chdir(root.parent)
    # The release uses the repository-relative output/episodes tree.
    root.rename(tmp_path / "saved")
    (tmp_path / "output").mkdir()
    (tmp_path / "saved").rename(tmp_path / "output/episodes")
    request_file = tmp_path / "request.json"
    request_file.write_text(json.dumps(request))
    monkeypatch.setattr(release, "REQUEST_PATH", request_file)
    repo_scenes = Path(__file__).resolve().parents[1] / release.SCENES_PATH
    monkeypatch.setattr(release, "SCENES_PATH", repo_scenes)
    # Keep the approved relative request path while resolving scene bytes locally.
    monkeypatch.setattr(release, "prepare_release", lambda *args: (
        asset["script_json"], {"_generation_revision": 2}))
    def table(name):
        result = [asset] if name == "episode_assets" else calls if name == "image_generation_calls" else []
        value = Mock()
        for method in ("select", "eq", "limit"):
            getattr(value, method).return_value = value
        value.execute.return_value = SimpleNamespace(data=result)
        return value
    monkeypatch.setattr("engine.common.supabase_client.icg_table", table)
    client = Mock()
    client.schema.return_value = client
    def rpc(name, args):
        version = "image-outcome-3" if "outcome_v3" in name else "image-content-isolation-4"
        return SimpleNamespace(execute=lambda: SimpleNamespace(data={"version": version}))
    client.rpc.side_effect = rpc
    monkeypatch.setattr("engine.common.supabase_client.get_client", lambda: client)
    private = tmp_path / "private"
    def register(*args):
        assert (private / "source.json").is_file()
        assert (private / "candidate.json").stat().st_mode & 0o777 == 0o600
    registered = Mock(side_effect=register)
    monkeypatch.setattr(release, "register", registered)
    result = release.execute(private_dir=private, register_live=live)
    assert result["registered"] is live
    assert registered.call_count == int(live)


def test_one_shot_workflow_runs_only_after_approved_main_push_and_restoration():
    workflow = yaml.load(Path(".github/workflows/reviewed_image_recovery_20261021.yml").read_text(),
                         Loader=yaml.BaseLoader)
    assert workflow["on"]["push"]["branches"] == ["main"]
    assert workflow["on"]["push"]["paths"] == [".github/icg-image-recovery/2026-10-21.json"]
    assert "schedule" not in workflow["on"]
    job = workflow["jobs"]["recover"]
    assert "refs/heads/main" in job["if"]
    steps = job["steps"]
    register_idx = next(i for i, s in enumerate(steps) if "--register" in s.get("run", ""))
    restore_idx = next(i for i, s in enumerate(steps) if "restore_generation_artifact" in s.get("run", ""))
    image_idx = next(i for i, s in enumerate(steps)
                     if "--stage image" in s.get("run", "") and "--preflight-only" not in s["run"])
    assert restore_idx < register_idx < image_idx
    commands = "\n".join(s.get("run", "") for s in steps)
    assert "run_publish" not in commands and "run_resume" not in commands
    assert "--stage all" not in commands and "--stage recovery" not in commands
    uploads = [s["with"]["path"] for s in steps if s.get("uses", "").startswith("actions/upload-artifact")]
    assert uploads == ["output/episodes/", "output/run-market-preflight.json"]


def test_recovered_episode_requires_manual_resume_but_normal_schedule_is_unchanged(monkeypatch):
    from scripts import run_resume
    from tests.test_image_hold_monitoring import target_table

    row = {"status": "image_generated", "artifact_run_id": "123",
           "script_json": {"_image_recovery_review": {"require_manual_resume": True}}}
    target_table(monkeypatch, [row])
    result = run_resume.prepare_resume_target("ICG-2026-10-21-001", scheduled=True)
    assert result["ready"] is False
    assert result["reason"] == "reviewed_recovery_requires_manual_resume"
    assert run_resume.prepare_resume_target("ICG-2026-10-21-001")["ready"] is True
    row["script_json"]["_image_recovery_review"]["require_manual_resume"] = False
    assert run_resume.prepare_resume_target("ICG-2026-10-21-001", scheduled=True)["ready"] is True
