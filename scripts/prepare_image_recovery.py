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
    if source.get('_scene_performance_v2'):
        return _prepare_performance(source, scenes, revision, actor=actor, note=note,
                                    preserved_inputs=preserved_inputs)
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


def _prepare_performance(source: dict, scenes: dict, revision: int, *, actor: str, note: str,
                         preserved_inputs: dict) -> dict:
    from engine.image.prompt_builder import _get_char_designs, _get_style_block
    from engine.image.ref_loader import get_ref_bindings_for_panel
    from engine.image.scene_performance import (
        episode_specs,
        payload_hash,
        render_prompt,
        validate_scene,
    )
    source_specs = episode_specs(source)
    original = source.get('_reviewed_image_inputs') or {}
    if original.get('version') != 'reviewed-image-inputs-2':
        raise GenerationHold('RECOVERY_V2_FROZEN_SOURCE_REQUIRED')
    candidate = copy.deepcopy(source)
    for field in ('_reviewed_image_retry_plans', '_assembly_manifest', '_effective_render_manifest',
                  '_mobile_layout_report', '_image_quality_selection'):
        candidate.pop(field, None)
    candidate['_generation_revision'] = revision
    candidate['_preserved_performance_inputs'] = {}
    items = []
    for panel in candidate['panels']:
        idx = str(panel['idx'])
        if panel['idx'] not in source_specs:
            continue
        if idx in preserved_inputs:
            item = copy.deepcopy(preserved_inputs[idx])
            if (item.get('idx') != panel['idx'] or item.get('reuse_only') is not True
                    or item.get('scene_sha256') != payload_hash(source_specs[panel['idx']].model_dump())):
                raise GenerationHold('RECOVERY_V2_SUCCESS_SPEC_CHANGED')
            proof = {k: item.get(k) for k in ('fingerprint', 'output_hash', 'scene_sha256')}
            candidate['_preserved_performance_inputs'][idx] = dict(proof, panel_sha256=payload_hash(panel))
            items.append(item)
            continue
        scene = scenes[idx]
        if not isinstance(scene, dict) or not isinstance(scene.get('performance'), dict):
            raise GenerationHold('RECOVERY_V2_REVIEWED_PERFORMANCE_REQUIRED')
        for field in ('action', 'setting'):
            if not isinstance(scene.get(field), str) or not scene[field].strip():
                raise GenerationHold('RECOVERY_V2_ACTION_REQUIRED')
            panel[field] = scene[field]
        performance = copy.deepcopy(scene['performance'])
        performance.update(panel_idx=panel['idx'], action_sha256=text_hash(panel['action']),
                           setting_sha256=text_hash(panel['setting']), review_evidence=note)
        spec = validate_scene(panel, performance)
        if spec.required_story_facts != source_specs[panel['idx']].required_story_facts:
            raise GenerationHold('RECOVERY_V2_STORY_FACTS_CHANGED')
        candidate['_scene_performance_v2'][idx] = spec.model_dump()
        bindings = get_ref_bindings_for_panel(panel.get('characters', []))
        refs = [Path(b['ref']) for b in bindings]
        from engine.image.render_sources import project_sources
        canon, style, projection = project_sources(_get_char_designs(spec.visible_cast), _get_style_block())
        prompt = render_prompt(panel, spec, canon=canon, style=style)
        hashes = [b['sha256'] for b in bindings]
        fingerprint = hashlib.sha256(json.dumps([prompt+'\n[model=gemini-2.5-flash-image;aspect=4:5]', hashes],
            ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()
        items.append({'idx': panel['idx'], 'prompt_text': prompt, 'refs': [str(p) for p in refs],
            'ref_sha256': hashes, 'ref_bindings': bindings,
            'render_sources_report': projection,
            'scene_sha256': payload_hash(spec.model_dump()), 'fingerprint': fingerprint})
    candidate['_reviewed_image_inputs'] = dict(original, origin='RECOVERY', panels=items,
                                              script_hash=script_hash(candidate))
    # Older v2 inputs without binding metadata retain their frozen reference contract.
    if original.get('ref_binding_version') is None:
        for item in items:
            if item.get('reuse_only'):
                continue
            panel = candidate['panels'][item['idx']-1]
            if [str(p) for p in get_refs_for_panel([c['char_id'] for c in panel.get('characters', [])])] != item['refs']:
                raise GenerationHold('RECOVERY_LEGACY_V2_FORM_REQUIRES_EXPLICIT_MIGRATION')
    candidate['_image_recovery_review'] = {'actor': actor, 'note': note}
    return candidate


def validate_candidate(candidate: dict) -> None:
    from engine.image.reviewed_inputs import reviewed_panel_prompts
    previous = os.environ.get("ICG_GENERATION_REVISION")
    try:
        os.environ["ICG_GENERATION_REVISION"] = str(candidate.get("_generation_revision"))
        # Offline structural validation cannot authorize a not-yet-registered DB
        # revision. Registration RPC validates policy/CAS; execution rechecks DB.
        offline = copy.deepcopy(candidate)
        offline.pop('_visual_policy', None)
        offline.pop('_visual_policy_sha256', None)
        if reviewed_panel_prompts(offline) is None:
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
