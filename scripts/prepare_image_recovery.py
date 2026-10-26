"""Prepare reviewed fixed inputs offline; register only with an explicit CLI action.

The source must be the exact persisted episode script (including state candidate),
not the earlier narrative artifact. No image provider or publishing code is called.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path

from engine.image.generation_guard import GenerationHold
from engine.image.ref_loader import get_refs_for_panel
from engine.image.scene_contract import (
    CARD_TYPES,
    text_hash,
    validate_scene_contracts,
    validate_scene_text,
)
from engine.publish.manifest import script_hash


def prepare(source: dict, scenes: dict, revision: int, *, actor: str, note: str,
            preserved_inputs: dict | None = None) -> dict:
    if (type(revision) is not int or not 2 <= revision <= 100
            or not isinstance(source, dict) or not isinstance(scenes, dict)
            or not actor.strip() or len(note.strip()) < 20
            or type(source.get("_generation_revision", 1)) is not int
            or revision <= source.get("_generation_revision", 1)
            or (source.get("_state_candidate") or {}).get("version") != "state-candidate-1"):
        raise GenerationHold("Recovery requires exact persisted source and a new reviewed revision")
    panels = source.get("panels")
    if not isinstance(panels, list) or not panels:
        raise GenerationHold("Recovery source panels required")
    if any(not isinstance(p, dict) or type(p.get("idx")) is not int for p in panels):
        raise GenerationHold("Recovery source indices invalid")
    if [p["idx"] for p in panels] != list(range(1, len(panels) + 1)):
        raise GenerationHold("Recovery source indices must be contiguous")
    required = {str(p["idx"]) for p in panels if p.get("panel_type") not in CARD_TYPES}
    preserved_inputs = preserved_inputs or {}
    if set(scenes) & set(preserved_inputs) or set(scenes) | set(preserved_inputs) != required:
        raise GenerationHold("Reviewed scenes must cover every paid panel")
    candidate = copy.deepcopy(source)
    for key in ("_reviewed_image_retry_plans", "_reviewed_image_inputs", "_assembly_manifest"):
        candidate.pop(key, None)
    candidate["_generation_revision"] = revision
    candidate["_scene_contracts"] = {}
    items = []
    for panel in candidate["panels"]:
        idx = str(panel["idx"])
        if idx not in required:
            continue
        if idx in preserved_inputs:
            item = copy.deepcopy(preserved_inputs[idx])
            if item.get("idx") != panel["idx"] or item.get("reuse_only") is not True:
                raise GenerationHold("Invalid preserved image input")
            candidate["_scene_contracts"][idx] = {
                "version": "reuse-only-scene-1", "panel_idx": panel["idx"],
                "panel_sha256": text_hash(json.dumps(panel, ensure_ascii=False, sort_keys=True,
                                                     separators=(",", ":"))),
                "fingerprint": item["fingerprint"], "output_hash": item["output_hash"],
                "review_evidence": note,
            }
            items.append(item)
            continue
        scene = scenes[idx]
        if not isinstance(scene, dict):
            raise GenerationHold("Malformed reviewed scene")
        for field in ("action", "setting"):
            if not isinstance(scene.get(field), str) or not scene[field].strip():
                raise GenerationHold("Reviewed action and setting required")
            panel[field] = scene[field]
        contract = copy.deepcopy(scene.get("contract"))
        if not isinstance(contract, dict):
            raise GenerationHold("Reviewed scene contract required")
        contract.update(version="scene-contract-1", panel_idx=panel["idx"],
                        actor_ids=[c["char_id"] for c in panel.get("characters", [])],
                        action_sha256=text_hash(panel["action"]), setting_sha256=text_hash(panel["setting"]),
                        review_evidence=note)
        candidate["_scene_contracts"][idx] = contract
        prompt = scene.get("prompt_text")
        if (not isinstance(prompt, str) or panel["action"] not in prompt
                or panel["setting"] not in prompt):
            raise GenerationHold("Reviewed prompt must include the exact action and setting")
        validate_scene_text(prompt, panel["idx"])
        refs = get_refs_for_panel([c["char_id"] for c in panel.get("characters", [])])
        hashes = [hashlib.sha256(ref.read_bytes()).hexdigest() for ref in refs]
        fingerprint = hashlib.sha256(json.dumps(
            [prompt + "\n[model=gemini-2.5-flash-image;aspect=None]", hashes],
            ensure_ascii=False, separators=(",", ":")
        ).encode()).hexdigest()
        items.append({"idx": panel["idx"], "prompt_text": prompt,
                      "refs": [p.as_posix() for p in refs], "ref_sha256": hashes,
                      "fingerprint": fingerprint})
    candidate["_reviewed_image_inputs"] = {
        "version": "reviewed-image-inputs-1", "script_hash": script_hash(candidate),
        "model": "gemini-2.5-flash-image", "aspect_ratio": None, "panels": items,
    }
    validate_scene_contracts(candidate)
    candidate["_image_recovery_review"] = {"actor": actor, "note": note}
    return candidate


def validate_candidate(candidate: dict) -> None:
    from engine.image.reviewed_inputs import reviewed_panel_prompts
    previous = os.environ.get("ICG_GENERATION_REVISION")
    try:
        os.environ["ICG_GENERATION_REVISION"] = str(candidate.get("_generation_revision"))
        if reviewed_panel_prompts(candidate) is None:
            raise GenerationHold("Reviewed inputs missing")
    finally:
        if previous is None:
            os.environ.pop("ICG_GENERATION_REVISION", None)
        else:
            os.environ["ICG_GENERATION_REVISION"] = previous


def register(source: dict, candidate: dict, token: str, cost: float) -> dict:
    from engine.common.supabase_client import get_client, get_schema
    validate_candidate(candidate)
    review = candidate["_image_recovery_review"]
    receipt = get_client().schema(get_schema()).rpc("image_generation_register_recovery_v3", {
        "p_expected_script": source, "p_script": candidate, "p_token": token,
        "p_revision": candidate["_generation_revision"], "p_actual_cost": cost,
        "p_fingerprints": {str(p["idx"]): p["fingerprint"]
                           for p in candidate["_reviewed_image_inputs"]["panels"]},
        "p_actor": review["actor"], "p_note": review["note"],
    }).execute().data
    if not isinstance(receipt, dict) or receipt.get("registered") is not True or receipt.get("hold"):
        raise GenerationHold("Recovery registration rejected; preserve current episode")
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--scenes", type=Path, required=True)
    parser.add_argument("--revision", type=int, required=True)
    parser.add_argument("--actor", required=True)
    parser.add_argument("--note", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--register", action="store_true")
    parser.add_argument("--confirm")
    parser.add_argument("--terminal-token")
    parser.add_argument("--observed-cost", type=float)
    args = parser.parse_args()
    if args.register and (args.confirm != "REGISTER_REVIEWED_RECOVERY"
                          or not args.terminal_token or args.observed_cost is None):
        parser.error("Registration requires confirmation, terminal token and observed cost")
    source = json.loads(args.source.read_text())
    candidate = prepare(source, json.loads(args.scenes.read_text()), args.revision,
                        actor=args.actor, note=args.note)
    validate_candidate(candidate)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    # Private prompts never go to public episode artifacts, and existing files are preserved.
    output = args.output.resolve()
    public = Path("output").resolve()
    if output == public or public in output.parents:
        raise GenerationHold("Recovery candidates must be outside public artifacts")
    with args.output.open("x", encoding="utf-8") as handle:
        args.output.chmod(0o600)
        json.dump(candidate, handle, ensure_ascii=False, indent=2)
    if args.register:
        register(source, candidate, args.terminal_token, args.observed_cost)
    print(json.dumps({"prepared": True, "registered": args.register,
                      "revision": args.revision, "paid_calls": 0, "publishes": 0}))


if __name__ == "__main__":
    main()
