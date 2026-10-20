"""Offline common recovery contracts; no production credentials or paid provider calls."""
import copy
import hashlib
import json
from pathlib import Path
from unittest.mock import Mock

import pytest
import yaml

from engine.image import recovery_service as service
from engine.image.generation_guard import GenerationHold
from tests.test_image_adapter_guard_v2 import png


@pytest.fixture
def recovery(tmp_path):
    day = "2027-03-04"
    source = {"episode_id": f"ICG-{day}-001", "date": day, "_generation_revision": 1,
              "_state_candidate": {"version": "state-candidate-1"},
              "_scores": {"quality": 100.0}, "panels": []}
    for idx in range(1, 9):
        cast = [] if idx > 6 else [{"char_id": "CHAR_HERO_002", "role": "hero", "form": "form1"}]
        if idx <= 6 and idx != 2:
            cast.append({"char_id": "CHAR_VILLAIN_001", "role": "villain", "form": None})
        source["panels"].append({"idx": idx, "panel_type": "BATTLE" if idx <= 6 else
                                  "TEXT_CARD" if idx == 7 else "DISCLAIMER",
                                  "action": "original action", "setting": "original setting",
                                  "narration": "PRIVATE_SOURCE_STORY", "characters": cast})
    asset = {"script_json": source, "status": "narrative_done", "artifact_run_id": "12345"}
    digest = hashlib.sha256(png()).hexdigest()
    calls = [{"panel": i, "revision": 1, "state": "success", "output_hash": digest, "cost": .04}
             for i in (1, 2, 3)]
    calls.append({"panel": 4, "revision": 1, "state": "terminal",
                  "token": "3eec942a-43ae-4298-922c-c0beaf80b07b", "cost": .001,
                  "provider_reason": "PROHIBITED_CONTENT", "result_code": "CONTENT_REVIEW_REQUIRED",
                  "settled_at": "2027-03-04T00:00:00Z"})
    request = service.inspection(asset, calls, day)
    scenes = Path("docs/incidents/2026-10-21-reviewed-scenes.json")
    request.update(scenes_path=scenes.as_posix(),
                   scenes_sha256=hashlib.sha256(scenes.read_bytes()).hexdigest(),
                   actor="reviewer", note="Reviewed dynamic-safe scenes and preserved story evidence.")
    root = tmp_path / "episodes"
    panels = root / day / "panels"
    panels.mkdir(parents=True)
    for idx in (1, 2, 3):
        (panels / f"P{idx}.png").write_bytes(png())
    return request, asset, calls, root


def test_inspection_uses_native_python_float_representation_without_private_story(recovery):
    request, asset, calls, _ = recovery
    assert request["source_script_sha256"] == service.full_hash(asset["script_json"])
    integral = copy.deepcopy(asset["script_json"])
    integral["_scores"]["quality"] = 100
    assert service.full_hash(integral) != request["source_script_sha256"]
    report = service.inspection(asset, calls, request["episode_date"])
    assert "PRIVATE_SOURCE_STORY" not in json.dumps(report)
    assert "request_template" not in report
    assert report["episode_date"] == "2027-03-04"


def test_common_candidate_preserves_source_cast_story_cards_and_manual_resume_gate(recovery):
    request, asset, calls, root = recovery
    old = copy.deepcopy(asset)
    source, candidate = service.prepare_request(request, asset, calls, root)
    assert asset == old
    assert candidate["_generation_revision"] == 2
    assert candidate["_state_candidate"] == source["_state_candidate"]
    assert candidate["_image_recovery_review"]["require_manual_resume"] is True
    assert candidate["panels"][6:] == source["panels"][6:]
    assert [p["characters"] for p in candidate["panels"]] == [p["characters"] for p in source["panels"]]
    assert [len(p["refs"]) for p in candidate["_reviewed_image_inputs"]["panels"]] == [2, 1, 2, 2, 2, 2]


@pytest.mark.parametrize("change", ["source", "revision", "artifact", "unknown", "reserved",
                                    "missing_cost", "over_cost", "extra_terminal", "terminal_token",
                                    "success_hash", "bad_scene_hash", "dynamic"])
def test_source_ledger_or_review_drift_stops_before_registration(recovery, change):
    request, asset, calls, root = recovery
    if change == "source":
        asset["script_json"]["panels"][0]["narration"] = "changed"
    elif change == "revision":
        asset["script_json"]["_generation_revision"] = 2
    elif change == "artifact":
        asset["artifact_run_id"] = "other"
    elif change in {"unknown", "reserved"}:
        calls[0]["state"] = change
    elif change == "missing_cost":
        calls[0]["cost"] = None
    elif change == "over_cost":
        calls[-1]["cost"] = .11
    elif change == "extra_terminal":
        calls.append(dict(calls[-1], panel=5))
    elif change == "terminal_token":
        calls[-1]["token"] = "changed"
    elif change == "success_hash":
        calls[0]["output_hash"] = "0" * 64
    elif change == "dynamic":
        asset["script_json"]["_scene_performance_v2"] = {"version": "future"}
    else:
        request["scenes_sha256"] = "0" * 64
    with pytest.raises(GenerationHold):
        service.prepare_request(request, asset, calls, root)


def test_corrupt_original_png_blocks_registration(recovery):
    request, asset, calls, root = recovery
    (root / request["episode_date"] / "panels/P2.png").write_bytes(png() + b"changed")
    with pytest.raises(GenerationHold, match="ORIGINAL_PNG_CHANGED"):
        service.prepare_request(request, asset, calls, root)


@pytest.mark.parametrize("name", ["../request.json", "/tmp/request.json",
                                   "config/image-recovery/requests/../../secret.json",
                                   ".github/icg-image-recovery/request.json\nready=true"])
def test_request_paths_cannot_escape_repository_or_inject_outputs(name):
    with pytest.raises(GenerationHold, match="PATH_INVALID"):
        service.read_request(name)


@pytest.mark.parametrize("mode", ["inspect", "prepare", "execute"])
def test_only_confirmed_execute_registers_then_calls_existing_image_stage(
        recovery, monkeypatch, tmp_path, mode):
    request, asset, calls, root = recovery
    monkeypatch.setattr(service, "snapshot", lambda day: (asset, calls))
    monkeypatch.setattr(service, "read_request", lambda *args: (request, "a" * 64))
    actual_prepare = service.prepare_request
    monkeypatch.setattr(service, "prepare_request",
                        lambda req, row, rows, ignored: actual_prepare(req, row, rows, root))
    _, candidate = actual_prepare(request, asset, calls, root)
    events = []
    registered = Mock(side_effect=lambda *args: events.append("register"))
    generated = Mock(side_effect=lambda *args: events.append("image"))
    monkeypatch.setattr(service, "register", registered)
    monkeypatch.setattr(service, "run_images", generated)
    report = service.operate(mode, day=request["episode_date"], request_path="request.json",
                             request_sha256="a" * 64, candidate_sha256=service.full_hash(candidate),
                             confirm=service.CONFIRMATION, private_dir=tmp_path / "private")
    assert events == (["register", "image"] if mode == "execute" else [])
    assert "PRIVATE_SOURCE_STORY" not in json.dumps(report)
    assert (tmp_path / "private/source.json").stat().st_mode & 0o777 == 0o600
    if mode != "execute":
        assert report["database_writes"] == 0 and report["paid_calls"] == 0


@pytest.mark.parametrize("bad", ["confirm", "request_hash", "candidate_hash"])
def test_execute_requires_matching_review_hashes_and_explicit_confirmation(
        recovery, monkeypatch, tmp_path, bad):
    request, asset, calls, root = recovery
    monkeypatch.setattr(service, "snapshot", lambda day: (asset, calls))
    monkeypatch.setattr(service, "read_request", lambda *args: (request, "a" * 64))
    actual_prepare = service.prepare_request
    monkeypatch.setattr(service, "prepare_request",
                        lambda req, row, rows, ignored: actual_prepare(req, row, rows, root))
    _, candidate = actual_prepare(request, asset, calls, root)
    registered = Mock()
    generated = Mock()
    monkeypatch.setattr(service, "register", registered)
    monkeypatch.setattr(service, "run_images", generated)
    kwargs = {"request_sha256": "a" * 64, "candidate_sha256": service.full_hash(candidate),
              "confirm": service.CONFIRMATION}
    kwargs[{"confirm": "confirm", "request_hash": "request_sha256",
            "candidate_hash": "candidate_sha256"}[bad]] = "" if bad != "candidate_hash" else "0" * 64
    with pytest.raises(GenerationHold):
        service.operate("execute", request_path="request.json", private_dir=tmp_path / "private", **kwargs)
    registered.assert_not_called()
    generated.assert_not_called()


def test_registration_failure_never_calls_provider(recovery, monkeypatch, tmp_path):
    request, asset, calls, root = recovery
    monkeypatch.setattr(service, "snapshot", lambda day: (asset, calls))
    monkeypatch.setattr(service, "read_request", lambda *args: (request, "a" * 64))
    actual_prepare = service.prepare_request
    monkeypatch.setattr(service, "prepare_request",
                        lambda req, row, rows, ignored: actual_prepare(req, row, rows, root))
    _, candidate = actual_prepare(request, asset, calls, root)
    monkeypatch.setattr(service, "register", Mock(side_effect=GenerationHold("CAS_REJECTED")))
    generated = Mock()
    monkeypatch.setattr(service, "run_images", generated)
    with pytest.raises(service.RecoveryProgressHold, match="REGISTRATION_UNCONFIRMED") as held:
        service.operate("execute", request_path="request.json", request_sha256="a" * 64,
                        candidate_sha256=service.full_hash(candidate), confirm=service.CONFIRMATION,
                        private_dir=tmp_path / "private")
    generated.assert_not_called()
    assert held.value.report["registered"] == "unconfirmed"
    assert held.value.report["phase"] == "registration"


def test_private_candidates_cannot_be_written_under_artifact_output(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(GenerationHold, match="PRIVATE_DIRECTORY_REQUIRED"):
        service.write_private(tmp_path / "output/private", "candidate.json", {})


def test_common_workflow_is_manual_and_never_uploads_private_candidates():
    workflow = yaml.load(Path(".github/workflows/image_recovery.yml").read_text(), Loader=yaml.BaseLoader)
    assert set(workflow["on"]) == {"workflow_dispatch"}
    assert workflow["on"]["workflow_dispatch"]["inputs"]["mode"]["default"] == "inspect"
    job = workflow["jobs"]["recovery"]
    assert "refs/heads/main" in job["if"]
    assert job["env"]["DRY_RUN"] == "true"
    uploads = [s["with"]["path"] for s in job["steps"]
               if s.get("uses", "").startswith("actions/upload-artifact")]
    assert uploads == ["output/image-recovery-report.json", "output/episodes/"]
    commands = "\n".join(s.get("run", "") for s in job["steps"])
    assert "run_publish" not in commands and "run_resume" not in commands
    assert "$REQUEST_PATH" in commands and "2026-10-21" not in commands


def test_image_execution_requires_allowlisted_read_only_preflight(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    calls = []
    def run(command, **kwargs):
        calls.append(command)
        Path("output").mkdir(exist_ok=True)
        Path("output/run-market-preflight.json").write_text('{"allowed": false}')
        assert kwargs["env"]["ICG_GENERATION_REVISION"] == "3"
    monkeypatch.setattr(service.subprocess, "run", run)
    with pytest.raises(GenerationHold, match="PREFLIGHT_BLOCKED"):
        service.run_images({"target_revision": 3, "episode_date": "2027-03-04"})
    assert len(calls) == 1 and "--preflight-only" in calls[0]


def test_post_registration_image_failure_reports_committed_phase(recovery, monkeypatch, tmp_path):
    request, asset, calls, root = recovery
    monkeypatch.setattr(service, "snapshot", lambda day: (asset, calls))
    monkeypatch.setattr(service, "read_request", lambda *args: (request, "a" * 64))
    actual_prepare = service.prepare_request
    monkeypatch.setattr(service, "prepare_request",
                        lambda req, row, rows, ignored: actual_prepare(req, row, rows, root))
    _, candidate = actual_prepare(request, asset, calls, root)
    monkeypatch.setattr(service, "register", Mock())
    monkeypatch.setattr(service, "run_images", Mock(side_effect=TimeoutError("PRIVATE_REQUEST_DATA")))
    with pytest.raises(service.RecoveryProgressHold, match="IMAGE_STAGE_HELD") as held:
        service.operate("execute", request_path="request.json", request_sha256="a" * 64,
                        candidate_sha256=service.full_hash(candidate), confirm=service.CONFIRMATION,
                        private_dir=tmp_path / "private")
    assert held.value.report["registered"] is True
    assert held.value.report["phase"] == "image"
    assert "PRIVATE_REQUEST_DATA" not in json.dumps(held.value.report)


def test_missing_canonical_ref_is_not_silently_accepted(recovery, monkeypatch):
    request, asset, calls, root = recovery
    monkeypatch.setattr("scripts.prepare_image_recovery.get_refs_for_panel", lambda ids: [])
    monkeypatch.setattr("engine.image.reviewed_inputs.get_refs_for_panel", lambda ids: [])
    with pytest.raises(GenerationHold, match="CANON_REFERENCES_INCOMPLETE"):
        service.prepare_request(request, asset, calls, root)


def test_lifetime_panel_budget_stops_prepare_before_any_registration(recovery, monkeypatch):
    request, asset, calls, root = recovery
    calls.extend([dict(calls[-1], state="failed", result_code="TRANSIENT") for _ in range(2)])
    registered = Mock()
    monkeypatch.setattr(service, "register", registered)
    with pytest.raises(GenerationHold, match="RECOVERY_PANEL_BUDGET_EXHAUSTED"):
        service.prepare_request(request, asset, calls, root)
    registered.assert_not_called()


def test_success_reuse_requires_same_candidate_fingerprint_even_at_lifetime_limit():
    candidate = {"_reviewed_image_inputs": {"panels": [{"idx": 1, "fingerprint": "a" * 64}]}}
    calls = [{"panel": 1, "state": "failed", "cost": .01} for _ in range(2)]
    calls.append({"panel": 1, "state": "success", "cost": .04, "fingerprint": "a" * 64})
    service._check_remaining_budget(candidate, calls)
    calls[-1]["fingerprint"] = "b" * 64
    with pytest.raises(GenerationHold, match="RECOVERY_PANEL_BUDGET_EXHAUSTED"):
        service._check_remaining_budget(candidate, calls)


@pytest.mark.parametrize("count,cost,expected", [
    (29, .01, "RECOVERY_SCOPE_CALL_BUDGET_EXHAUSTED"),
    (28, .10, ""),
    (29, .10, "RECOVERY_SCOPE_COST_BUDGET_EXHAUSTED"),
])
def test_scope_headroom_includes_every_needed_new_image(count, cost, expected):
    candidate = {"_reviewed_image_inputs": {"panels": [
        {"idx": 1, "fingerprint": "a" * 64}, {"idx": 2, "fingerprint": "b" * 64}]}}
    calls = [{"panel": 99, "state": "failed", "cost": cost} for _ in range(count)]
    if expected == "RECOVERY_SCOPE_COST_BUDGET_EXHAUSTED":
        # Exactly one image still needed: calls fit, conservative cost does not.
        candidate["_reviewed_image_inputs"]["panels"].pop()
        calls[0]["cost"] = .1000000000000001
    if expected:
        with pytest.raises(GenerationHold, match=expected):
            service._check_remaining_budget(candidate, calls)
    else:
        # Decimal arithmetic accepts exactly 30 calls / $3.00.
        service._check_remaining_budget(candidate, calls)
