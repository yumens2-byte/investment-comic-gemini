"""Bind an assembled artifact to its exact narrative and slide bytes."""
import hashlib
import json
from copy import deepcopy
from pathlib import Path


def script_hash(script: dict) -> str:
    public = {k: v for k, v in script.items() if not k.startswith("_")}
    return hashlib.sha256(json.dumps(public, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":")).encode()).hexdigest()


def build_manifest(script: dict, slides: list[Path]) -> dict:
    result = {"version": "assembly-manifest-1", "script_hash": script_hash(script),
            "generation_revision": script.get("_generation_revision", 1),
            "slides": [hashlib.sha256(p.read_bytes()).hexdigest() for p in slides]}
    if script.get("_image_quality_selection"):
        from engine.image.scene_performance import payload_hash
        result["quality_selection_hash"] = payload_hash(script["_image_quality_selection"])
    if '_visual_policy' in script or '_visual_policy_sha256' in script:
        from engine.image.scene_performance import payload_hash
        required = ('_visual_policy', '_visual_policy_sha256', '_effective_render_manifest', '_mobile_layout_report')
        if any(not script.get(key) for key in required):
            raise ValueError('visual assembly evidence missing')
        result.update(version='assembly-manifest-2',
            policy_sha256=script['_visual_policy_sha256'],
            policy_mirror_sha256=payload_hash(script['_visual_policy']),
            frozen_inputs_sha256=payload_hash(script['_reviewed_image_inputs']),
            scene_plan_sha256=payload_hash(script['_scene_performance_v2']),
            effective_render_manifest=script['_effective_render_manifest'],
            mobile_layout_sha256=payload_hash(script['_mobile_layout_report']),
            visual_contract={
                'policy': script['_visual_policy'], 'scene_plan': script['_scene_performance_v2'],
                'mobile_layout_report': script['_mobile_layout_report'],
                'public_script': {k: v for k, v in script.items() if not k.startswith('_')},
            })
    return deepcopy(result)


def validate_manifest(script: dict, slides: list[Path]) -> None:
    if script.get("_image_quality_selection"):
        from engine.image.quality_candidates import require_current_selection
        require_current_selection(script["_image_quality_selection"])
    if script.get("_assembly_manifest") != build_manifest(script, slides):
        raise ValueError("assembly manifest mismatch; reassemble the approved narrative")
