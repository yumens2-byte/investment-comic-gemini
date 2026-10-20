"""One-shot reviewed image recovery; private source, exact receipts, no provider call."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from engine.image.gemini_client import _validate_png
from engine.image.generation_guard import GenerationHold
from engine.publish.manifest import script_hash
from scripts.prepare_image_recovery import prepare, register, validate_candidate

REQUEST_PATH = Path(".github/icg-image-recovery/2026-10-21.json")
SCENES_PATH = Path("docs/incidents/2026-10-21-reviewed-scenes.json")


def full_hash(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def validate_source(request: dict, asset: dict, calls: list, root: Path) -> dict:
    if (request.get("version") != "reviewed-image-release-1"
            or request.get("confirmation") != "RECOVER_REVIEWED_IMAGES_20261021"
            or request.get("episode_date") != "2026-10-21"
            or request.get("episode_id") != "ICG-2026-10-21-001"
            or request.get("episode_no") != 1
            or request.get("source_revision") != 1 or request.get("target_revision") != 2
            or request.get("source_artifact_run_id") != "39489073022"
            or request.get("scenes_path") != SCENES_PATH.as_posix()):
        raise GenerationHold("RELEASE_REQUEST_IDENTITY_CHANGED")
    source = asset.get("script_json")
    if (asset.get("status") != "narrative_done"
            or asset.get("artifact_run_id") != request["source_artifact_run_id"]
            or not isinstance(source, dict)
            or source.get("episode_id") != request["episode_id"]
            or source.get("date") != request["episode_date"]
            or type(source.get("_generation_revision")) is not int
            or source["_generation_revision"] != request["source_revision"]
            or full_hash(source) != request.get("source_script_sha256")
            or script_hash(source) != request.get("public_script_sha256")):
        raise GenerationHold("RELEASE_SOURCE_CHANGED")
    if (not isinstance(calls, list) or len(calls) != 4
            or any(not isinstance(c, dict) or c.get("revision") != 1 for c in calls)):
        raise GenerationHold("RELEASE_LEDGER_CHANGED")
    success = [c for c in calls if c.get("state") == "success"]
    terminal = [c for c in calls if c.get("state") == "terminal"]
    if (len(success) != 3 or {c.get("panel") for c in success} != {1, 2, 3}
            or len(terminal) != 1):
        raise GenerationHold("RELEASE_LEDGER_CHANGED")
    t = terminal[0]
    if (t.get("panel") != 4 or t.get("token") != request.get("terminal_token")
            or t.get("provider_reason") != request.get("terminal_reason")
            or t.get("provider_reason") != "PROHIBITED_CONTENT"
            or t.get("result_code") != "CONTENT_REVIEW_REQUIRED"
            or not t.get("settled_at") or t.get("cost") != request.get("terminal_cost_usd")
            or type(t.get("cost")) not in (float, int) or not 0 <= t["cost"] <= .10):
        raise GenerationHold("RELEASE_TERMINAL_CHANGED")
    if set(request.get("success_hashes", {})) != {"1", "2", "3"}:
        raise GenerationHold("RELEASE_SUCCESS_RECEIPTS_REQUIRED")
    for call in success:
        idx = call["panel"]
        expected = request["success_hashes"][str(idx)]
        data = (root / "2026-10-21" / "panels" / f"P{idx}.png").read_bytes()
        _validate_png(data)
        if call.get("output_hash") != expected or hashlib.sha256(data).hexdigest() != expected:
            raise GenerationHold("RELEASE_ORIGINAL_PNG_CHANGED")
    return source


def prepare_release(request: dict, asset: dict, calls: list, root: Path) -> tuple[dict, dict]:
    source = validate_source(request, asset, calls, root)
    scene_bytes = SCENES_PATH.read_bytes()
    if hashlib.sha256(scene_bytes).hexdigest() != request.get("scenes_sha256"):
        raise GenerationHold("RELEASE_SCENES_CHANGED")
    candidate = prepare(source, json.loads(scene_bytes), request["target_revision"],
                        actor=request["actor"], note=request["note"])
    candidate["_image_recovery_review"]["require_manual_resume"] = True
    validate_candidate(candidate)
    return source, candidate


def execute(*, private_dir: Path, register_live: bool = False) -> dict:
    from engine.common.supabase_client import get_client, get_schema, icg_table

    request = json.loads(REQUEST_PATH.read_text())
    private_dir = private_dir.resolve()
    public = Path("output").resolve()
    if private_dir == public or public in private_dir.parents:
        raise GenerationHold("RELEASE_PRIVATE_DIRECTORY_REQUIRED")
    private_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    for name, version in (("image_generation_outcome_v3_capability", "image-outcome-3"),
                          ("image_generation_content_isolation_v4_capability", "image-content-isolation-4")):
        receipt = get_client().schema(get_schema()).rpc(name, {}).execute().data
        if not isinstance(receipt, dict) or receipt.get("version") != version:
            raise GenerationHold("RELEASE_DATABASE_CONTRACT_MISSING")
    scope = "output/episodes/2026-10-21/panels"
    rows = icg_table("episode_assets").select("script_json,status,artifact_run_id").eq(
        "episode_date", request["episode_date"]).eq("episode_no", 1).limit(2).execute().data
    if not isinstance(rows, list) or len(rows) != 1:
        raise GenerationHold("RELEASE_EXACT_EPISODE_REQUIRED")
    calls = icg_table("image_generation_calls").select("*").eq("scope", scope).limit(31).execute().data
    receipts = icg_table("image_generation_recovery_receipts").select("target_revision").eq(
        "scope", scope).limit(1).execute().data
    if not isinstance(receipts, list) or receipts:
        raise GenerationHold("RELEASE_ALREADY_REGISTERED_OR_LEDGER_UNAVAILABLE")
    source, candidate = prepare_release(request, rows[0], calls, Path("output/episodes"))
    for name, payload in (("source.json", source), ("candidate.json", candidate)):
        path = private_dir / name
        with path.open("x", encoding="utf-8") as stream:
            path.chmod(0o600)
            json.dump(payload, stream, ensure_ascii=False, indent=2)
    if register_live:
        register(source, candidate, request["terminal_token"], request["terminal_cost_usd"])
    return {"prepared": True, "registered": register_live, "revision": 2,
            "source_images_verified": 3, "paid_calls": 0, "publishes": 0}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--private-dir", type=Path, required=True)
    parser.add_argument("--register", action="store_true")
    args = parser.parse_args()
    try:
        print(json.dumps(execute(private_dir=args.private_dir, register_live=args.register)))
    except Exception as exc:
        # Raw API errors can contain request data. Preserve the private files and emit type only.
        code = str(exc) if isinstance(exc, GenerationHold) else type(exc).__name__
        print(json.dumps({"prepared": False, "error_type": type(exc).__name__, "code": code}))
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
