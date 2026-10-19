"""Bind an assembled artifact to its exact narrative and slide bytes."""
import hashlib
import json
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
    return result


def validate_manifest(script: dict, slides: list[Path]) -> None:
    if script.get("_image_quality_selection"):
        from engine.image.quality_candidates import require_current_selection
        require_current_selection(script["_image_quality_selection"])
    if script.get("_assembly_manifest") != build_manifest(script, slides):
        raise ValueError("assembly manifest mismatch; reassemble the approved narrative")
