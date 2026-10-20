"""Common reviewed image recovery service; no incident-specific dates or dispatch triggers."""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import subprocess
import sys
from datetime import date
from pathlib import Path, PurePosixPath

from engine.image.gemini_client import _validate_png
from engine.image.generation_guard import GenerationHold
from engine.publish.manifest import script_hash
from scripts.prepare_image_recovery import prepare, register, validate_candidate

VERSION = "reviewed-image-recovery-2"
CONFIRMATION = "RECOVER_REVIEWED_IMAGES"
HEX = re.compile(r"^[0-9a-f]{64}$")
CONTENT_REASONS = {"PROHIBITED_CONTENT", "SAFETY", "IMAGE_SAFETY"}


def full_hash(value: dict) -> str:
    """Compute with the native Python DB response; preserve 100.0 versus 100."""
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def canonical_date(value: str) -> str:
    try:
        if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
            raise ValueError("invalid date")
    except ValueError as exc:
        raise GenerationHold("RECOVERY_DATE_INVALID") from exc
    return value


def _hex(value: object) -> bool:
    return isinstance(value, str) and bool(HEX.fullmatch(value))


def _repo_file(name: str, prefixes: tuple[str, ...]) -> Path:
    if (not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_./-]+", name)
            or PurePosixPath(name).is_absolute() or ".." in PurePosixPath(name).parts
            or not name.endswith(".json") or not name.startswith(prefixes)):
        raise GenerationHold("RECOVERY_REPOSITORY_PATH_INVALID")
    path = Path(name)
    root = Path.cwd().resolve()
    if not path.is_file() or root not in path.resolve().parents:
        raise GenerationHold("RECOVERY_REPOSITORY_PATH_INVALID")
    return path


def read_request(name: str, expected_hash: str = "") -> tuple[dict, str]:
    path = _repo_file(name, (".github/icg-image-recovery/", "config/image-recovery/requests/"))
    data = path.read_bytes()
    if len(data) > 262144:
        raise GenerationHold("RECOVERY_REQUEST_TOO_LARGE")
    digest = hashlib.sha256(data).hexdigest()
    if expected_hash and (not _hex(expected_hash) or digest != expected_hash):
        raise GenerationHold("RECOVERY_REQUEST_CHANGED")
    value = json.loads(data)
    validate_request(value)
    return value, digest


def validate_request(request: dict) -> None:
    if not isinstance(request, dict) or request.get("version") != VERSION:
        raise GenerationHold("RECOVERY_REQUEST_VERSION_INVALID")
    day = canonical_date(request.get("episode_date"))
    number = request.get("episode_no")
    source_rev, target_rev = request.get("source_revision"), request.get("target_revision")
    artifact = request.get("source_artifact_run_id")
    if (type(number) is not int or number != 1
            or request.get("episode_id") != f"ICG-{day}-{number:03d}"
            or type(source_rev) is not int or type(target_rev) is not int
            or not 1 <= source_rev < target_rev <= 100
            or not isinstance(artifact, str) or not artifact.isascii() or not artifact.isdigit()
            or int(artifact) <= 0
            or not _hex(request.get("source_script_sha256"))
            or not _hex(request.get("public_script_sha256"))
            or not _hex(request.get("scenes_sha256"))
            or not isinstance(request.get("terminal_token"), str)
            or not re.fullmatch(r"[0-9a-f-]{36}", request["terminal_token"])
            or request.get("terminal_reason") not in CONTENT_REASONS
            or type(request.get("terminal_cost_usd")) not in (int, float)
            or not math.isfinite(request["terminal_cost_usd"])
            or not 0 <= request["terminal_cost_usd"] <= .10
            or not isinstance(request.get("actor"), str) or not request["actor"].strip()
            or not isinstance(request.get("note"), str) or len(request["note"].strip()) < 20
            or not isinstance(request.get("success_hashes"), dict)
            or any(not re.fullmatch(r"[1-9][0-9]*", k) or not _hex(v)
                   for k, v in request["success_hashes"].items())):
        raise GenerationHold("RECOVERY_REQUEST_IDENTITY_INVALID")


def snapshot(day: str) -> tuple[dict, list]:
    """Read only. Capabilities/records remain owned by existing production contracts."""
    from engine.common.supabase_client import get_client, get_schema, icg_table

    day = canonical_date(day)
    receipt = get_client().schema(get_schema()).rpc(
        "image_generation_outcome_v3_capability", {}).execute().data
    if not isinstance(receipt, dict) or receipt.get("version") != "image-outcome-3":
        raise GenerationHold("RECOVERY_DATABASE_CONTRACT_MISSING")
    rows = icg_table("episode_assets").select("script_json,status,artifact_run_id").eq(
        "episode_date", day).eq("episode_no", 1).limit(2).execute().data
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
        raise GenerationHold("RECOVERY_EXACT_EPISODE_REQUIRED")
    scope = f"output/episodes/{day}/panels"
    calls = icg_table("image_generation_calls").select("*").eq("scope", scope).limit(31).execute().data
    receipts = icg_table("image_generation_recovery_receipts").select("target_revision").eq(
        "scope", scope).limit(1).execute().data
    if not isinstance(receipts, list) or receipts:
        raise GenerationHold("RECOVERY_ALREADY_REGISTERED_OR_LEDGER_UNAVAILABLE")
    _eligible(rows[0], calls, day)
    return rows[0], calls


def _eligible(asset: dict, calls: list, day: str) -> tuple[dict, dict, dict]:
    source = asset.get("script_json")
    if (asset.get("status") != "narrative_done" or not isinstance(source, dict)
            or source.get("date") != day or source.get("episode_id") != f"ICG-{day}-001"
            or type(source.get("_generation_revision", 1)) is not int
            or not 1 <= source.get("_generation_revision", 1) < 100
            or (source.get("_state_candidate") or {}).get("version") != "state-candidate-1"):
        raise GenerationHold("RECOVERY_SOURCE_NOT_ELIGIBLE")
    artifact = asset.get("artifact_run_id")
    if not isinstance(artifact, str) or not artifact.isascii() or not artifact.isdigit() or int(artifact) <= 0:
        raise GenerationHold("RECOVERY_ARTIFACT_ID_REQUIRED")
    if source.get("_scene_performance_v2"):
        raise GenerationHold("RECOVERY_DYNAMIC_V2_REQUIRES_SPECIALIZED_PREPARATION")
    if (not isinstance(calls, list) or not calls or len(calls) > 30
            or any(not isinstance(c, dict) or type(c.get("panel")) is not int or c["panel"] <= 0
                   or type(c.get("revision")) is not int
                   or not 1 <= c["revision"] <= source.get("_generation_revision", 1)
                   or c.get("state") not in {"success", "failed", "terminal"}
                   or type(c.get("cost")) not in (int, float) or not math.isfinite(c["cost"])
                   or not 0 <= c["cost"] <= .10 for c in calls)):
        raise GenerationHold("RECOVERY_UNSETTLED_OR_INVALID_LEDGER")
    terminal = [c for c in calls if c["state"] == "terminal"]
    if len(terminal) != 1:
        raise GenerationHold("RECOVERY_SINGLE_TERMINAL_REQUIRED")
    rejected = terminal[0]
    cost = rejected.get("cost")
    if (rejected.get("provider_reason") not in CONTENT_REASONS
            or rejected.get("result_code") != "CONTENT_REVIEW_REQUIRED"
            or not rejected.get("settled_at") or type(cost) not in (int, float)
            or not math.isfinite(cost) or not 0 <= cost <= .10):
        raise GenerationHold("RECOVERY_TERMINAL_NOT_SETTLED")
    successes = {}
    for call in calls:
        if call["state"] == "success":
            key = str(call["panel"])
            if key in successes or not _hex(call.get("output_hash")):
                raise GenerationHold("RECOVERY_AMBIGUOUS_SUCCESS_HISTORY")
            successes[key] = call["output_hash"]
    return source, rejected, successes


def inspection(asset: dict, calls: list, day: str) -> dict:
    """Public request template carries hashes and receipts, never raw prompts/script."""
    source, terminal, successes = _eligible(asset, calls, canonical_date(day))
    rev = source.get("_generation_revision", 1)
    return {"version": VERSION, "episode_date": day, "episode_id": source["episode_id"],
            "episode_no": 1, "source_revision": rev, "target_revision": rev + 1,
            "source_artifact_run_id": asset["artifact_run_id"],
            "source_script_sha256": full_hash(source), "public_script_sha256": script_hash(source),
            "terminal_token": terminal["token"], "terminal_reason": terminal["provider_reason"],
            "terminal_cost_usd": terminal["cost"], "success_hashes": successes,
            "scenes_path": "", "scenes_sha256": "", "actor": "", "note": ""}


def prepare_request(request: dict, asset: dict, calls: list, root: Path) -> tuple[dict, dict]:
    validate_request(request)
    day = request["episode_date"]
    source, terminal, successes = _eligible(asset, calls, day)
    if (asset.get("artifact_run_id") != request["source_artifact_run_id"]
            or source.get("_generation_revision", 1) != request["source_revision"]
            or full_hash(source) != request["source_script_sha256"]
            or script_hash(source) != request["public_script_sha256"]
            or terminal["token"] != request["terminal_token"]
            or terminal["provider_reason"] != request["terminal_reason"]
            or terminal["cost"] != request["terminal_cost_usd"]
            or successes != request["success_hashes"]):
        raise GenerationHold("RECOVERY_SOURCE_OR_RECEIPT_CHANGED")
    for key, digest in successes.items():
        data = (root / day / "panels" / f"P{key}.png").read_bytes()
        _validate_png(data)
        if hashlib.sha256(data).hexdigest() != digest:
            raise GenerationHold("RECOVERY_ORIGINAL_PNG_CHANGED")
    scenes = _repo_file(request.get("scenes_path"),
                       ("docs/incidents/", "config/image-recovery/scenes/"))
    data = scenes.read_bytes()
    if len(data) > 262144 or hashlib.sha256(data).hexdigest() != request["scenes_sha256"]:
        raise GenerationHold("RECOVERY_SCENES_CHANGED")
    candidate = prepare(source, json.loads(data), request["target_revision"],
                        actor=request["actor"], note=request["note"])
    candidate["_image_recovery_review"]["require_manual_resume"] = True
    validate_candidate(candidate)
    return source, candidate


def write_private(directory: Path, name: str, value: dict) -> None:
    directory = directory.resolve()
    public = Path("output").resolve()
    if directory == public or public in directory.parents:
        raise GenerationHold("RECOVERY_PRIVATE_DIRECTORY_REQUIRED")
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (directory / name).open("x", encoding="utf-8") as stream:
        (directory / name).chmod(0o600)
        json.dump(value, stream, ensure_ascii=False, indent=2)


def run_images(request: dict) -> None:
    """Existing stage=image owns reservations, costs, PNG validation and asset status."""
    env = dict(os.environ, DRY_RUN="false",
               ICG_GENERATION_REVISION=str(request["target_revision"]),
               ICG_IMAGE_RETRY_V2_ENABLED="false", ICG_IMAGE_OUTCOME_V3_ENABLED="true")
    command = [sys.executable, "-m", "scripts.run_market", "--stage", "image",
               "--date", request["episode_date"]]
    subprocess.run(command + ["--preflight-only"], check=True, env=env)
    report = json.loads(Path("output/run-market-preflight.json").read_text())
    if report.get("allowed") is not True:
        raise GenerationHold("RECOVERY_IMAGE_PREFLIGHT_BLOCKED")
    subprocess.run(command, check=True, env=env)


def operate(mode: str, *, day: str = "", request_path: str = "", request_sha256: str = "",
            candidate_sha256: str = "", confirm: str = "", private_dir: Path) -> dict:
    if mode not in {"inspect", "prepare", "execute"}:
        raise GenerationHold("RECOVERY_OPERATION_INVALID")
    if mode == "inspect":
        asset, calls = snapshot(canonical_date(day))
        template = inspection(asset, calls, day)
        write_private(private_dir, "source.json", asset["script_json"])
        return {"mode": mode, "database_writes": 0, "paid_calls": 0,
                "request_template": template}
    request, request_digest = read_request(request_path, request_sha256)
    if mode == "execute" and (confirm != CONFIRMATION or not _hex(request_sha256)
                              or not _hex(candidate_sha256)):
        raise GenerationHold("RECOVERY_EXPLICIT_EXECUTION_CONFIRMATION_REQUIRED")
    asset, calls = snapshot(request["episode_date"])
    source, candidate = prepare_request(request, asset, calls, Path("output/episodes"))
    digest = full_hash(candidate)
    if mode == "execute" and digest != candidate_sha256:
        raise GenerationHold("RECOVERY_CANDIDATE_CHANGED")
    write_private(private_dir, "source.json", source)
    write_private(private_dir, "candidate.json", candidate)
    report = {"mode": mode, "episode_id": request["episode_id"],
              "request_sha256": request_digest, "candidate_sha256": digest,
              "target_revision": request["target_revision"], "registered": False,
              "manual_resume": True, "source_images_verified": len(request["success_hashes"])}
    if mode == "execute":
        register(source, candidate, request["terminal_token"], request["terminal_cost_usd"])
        report["registered"] = True
        run_images(request)
        report["image_stage_completed"] = True
    else:
        report.update(database_writes=0, paid_calls=0)
    return report


def resolve(mode: str, day: str, request_path: str, request_sha256: str = "") -> dict:
    """Validate dispatch identities before interpolating outputs or downloading artifacts."""
    if mode == "inspect":
        return {"episode_date": canonical_date(day), "source_artifact_run_id": ""}
    if mode not in {"prepare", "execute"}:
        raise GenerationHold("RECOVERY_OPERATION_INVALID")
    request, _ = read_request(request_path, request_sha256)
    return {"episode_date": request["episode_date"],
            "source_artifact_run_id": request["source_artifact_run_id"]}
