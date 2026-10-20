"""Review materially revised scenes before bounded provider retries.

The module never edits a rejected prompt automatically or changes safety settings.
Each alternative is a complete new visual brief with source-bound story evidence.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
import unicodedata
from pathlib import Path

from engine.image.generation_guard import GenerationHold
from engine.image.scene_contract import validate_scene_text

VERSION = "image-retry-plan-2"
MOTIONS = {
    "TURN": r"\b(?:turns?|turning|pivots?|pivoting)\b",
    "LEAN": r"\b(?:leans?|leaning)\b",
    "REACH": r"\b(?:reaches?|reaching)\b",
    "PROP_INSPECTION": r"\b(?:tilts?|tilting|rotates?|rotating|inspects?|inspecting)\b",
    "CROUCH": r"\b(?:crouches?|crouching|kneels?|kneeling)\b",
    "ENVIRONMENT": r"\b(?:unfolds?|unfolding|ripples?|rippling|rotates?|rotating)\b",
}
CAMERAS = {"WIDE", "MEDIUM", "CLOSE_UP", "LOW_ANGLE", "OVER_SHOULDER", "DETAIL"}
SAFE_TARGETS = {"DISPLAY", "PROP", "ENVIRONMENT"}


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def normalized(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def source_identity(panel: dict) -> dict:
    cast = panel.get("characters")
    if (type(panel.get("idx")) is not int or panel["idx"] < 1
            or not isinstance(cast, list) or not cast
            or any(not isinstance(c, dict) or not isinstance(c.get("char_id"), str)
                   or not c["char_id"] for c in cast)):
        raise GenerationHold("REPAIR_SOURCE_CAST_REQUIRED")
    ids = [c["char_id"] for c in cast]
    if len(set(ids)) != len(ids):
        raise GenerationHold("REPAIR_SOURCE_CAST_CHANGED")
    return {"panel_idx": panel["idx"], "cast": copy.deepcopy(cast),
            "action": panel.get("action", ""), "setting": panel.get("setting", ""),
            "narration": panel.get("narration", ""), "key_text": panel.get("key_text", "")}


def validate_review(body: dict) -> None:
    source, variants, facts = body.get("source"), body.get("repairs"), body.get("story_facts")
    if (not isinstance(source, dict) or not isinstance(variants, list)
            or not 1 <= len(variants) <= 2 or not isinstance(facts, list) or not facts
            or any(not isinstance(f, str) or not f.strip() for f in facts)
            or not isinstance(body.get("review_note"), str) or len(body["review_note"].strip()) < 20
            or not isinstance(body.get("actor"), str) or not body["actor"].strip()
            or body.get("source_sha256") != digest(source)):
        raise GenerationHold("REPAIR_REVIEW_REQUIRED")
    if (type(source.get("panel_idx")) is not int or not isinstance(source.get("cast"), list)
            or not source["cast"] or not isinstance(source.get("action"), str)):
        raise GenerationHold("REPAIR_SOURCE_INVALID")
    cast = source["cast"]
    actions = {normalized(source["action"])}
    motions = set()
    for repair in variants:
        if not isinstance(repair, dict):
            raise GenerationHold("REPAIR_VARIANT_INVALID")
        action, setting, prompt = (repair.get("action"), repair.get("setting"),
                                   repair.get("prompt_text"))
        if (not all(isinstance(t, str) and t.strip() for t in (action, setting, prompt))
                or repair.get("cast") != cast or repair.get("story_facts") != facts
                or repair.get("camera") not in CAMERAS
                or repair.get("target_kind") not in SAFE_TARGETS
                or repair.get("physical_contact") is not False
                or repair.get("weapon_discharge") is not False or repair.get("injury") != "NONE"
                or not isinstance(repair.get("change_note"), str)
                or len(repair["change_note"].strip()) < 20):
            raise GenerationHold("REPAIR_VARIANT_INVALID")
        if normalized(action) in actions:
            raise GenerationHold("REPAIR_ACTION_MUST_CHANGE")
        motion = repair.get("motion")
        if motion not in MOTIONS or motion in motions or not re.search(MOTIONS[motion], action, re.I):
            raise GenerationHold("REPAIR_DYNAMIC_ACTION_REQUIRED")
        if action not in prompt or setting not in prompt or any(f not in prompt for f in facts):
            raise GenerationHold("REPAIR_STORY_OR_SCENE_MISSING")
        # Review the positive scene itself; a disclaimer cannot bless a harmful action.
        for value in (action, setting, prompt):
            validate_scene_text(value, source["panel_idx"])
        actions.add(normalized(action))
        motions.add(motion)


def validate_bundle(bundle: dict, original: str, refs: list[Path]) -> None:
    expected_keys = {"version", "plan_id", "prompts", "ref_sha256", "review"}
    if set(bundle) != expected_keys or bundle.get("version") != VERSION:
        raise GenerationHold("REPAIR_BUNDLE_INVALID")
    review = bundle.get("review")
    if not isinstance(review, dict):
        raise GenerationHold("REPAIR_REVIEW_REQUIRED")
    validate_review(review)
    prompts = [original] + [r["prompt_text"] for r in review["repairs"]]
    if bundle.get("prompts") != prompts or len(set(prompts)) != len(prompts):
        raise GenerationHold("REPAIR_PROMPTS_CHANGED")
    hashes = [hashlib.sha256(Path(ref).read_bytes()).hexdigest() for ref in refs]
    if not refs or bundle.get("ref_sha256") != hashes:
        raise GenerationHold("REPAIR_REFERENCES_CHANGED")
    content = {k: v for k, v in bundle.items() if k != "plan_id"}
    if bundle.get("plan_id") != digest(content):
        raise GenerationHold("REPAIR_PLAN_HASH_CHANGED")


def make_bundle(panel: dict, original: str, refs: list[Path], repairs: list[dict],
                *, story_facts: list[str], actor: str, note: str) -> dict:
    if (not isinstance(original, str) or not original.strip()
            or not isinstance(repairs, list) or not 1 <= len(repairs) <= 2
            or any(not isinstance(r, dict) or not isinstance(r.get("prompt_text"), str)
                   for r in repairs)):
        raise GenerationHold("REPAIR_VARIANT_INVALID")
    source = source_identity(panel)
    review = {"source": source, "source_sha256": digest(source),
              "repairs": copy.deepcopy(repairs), "story_facts": story_facts,
              "actor": actor, "review_note": note}
    body = {"version": VERSION, "prompts": [original] + [r["prompt_text"] for r in repairs],
            "ref_sha256": [hashlib.sha256(Path(ref).read_bytes()).hexdigest() for ref in refs],
            "review": review}
    bundle = dict(body, plan_id=digest(body))
    validate_bundle(bundle, original, refs)
    return bundle


def prepare(source: dict, base_prompts: dict, repair_specs: dict) -> tuple[dict, dict]:
    """Prepare all paid panels offline; no narrative edits or paid/provider calls."""
    from engine.image.ref_loader import get_refs_for_panel

    if (not isinstance(source, dict) or not isinstance(base_prompts, dict)
            or not isinstance(repair_specs, dict)
            or type(source.get("_generation_revision")) is not int
            or not 1 <= source["_generation_revision"] <= 100
            or source.get("_scene_performance_v2")):
        raise GenerationHold("REPAIR_EPISODE_CONFIGURATION_UNSUPPORTED")
    panels = source.get("panels")
    if (not isinstance(panels, list) or not panels
            or any(not isinstance(p, dict) or type(p.get("idx")) is not int for p in panels)
            or len({p["idx"] for p in panels}) != len(panels)):
        raise GenerationHold("REPAIR_EPISODE_INVALID")
    paid = [p for p in panels if p.get("panel_type") not in {"TEXT_CARD", "DISCLAIMER"}]
    expected = {str(p["idx"]) for p in paid}
    if not expected or set(base_prompts) != expected or set(repair_specs) != expected:
        raise GenerationHold("REPAIR_ALL_PAID_PANELS_REQUIRED")
    candidate = copy.deepcopy(source)
    candidate["_reviewed_image_retry_plans"] = {}
    fingerprints = {}
    for panel in paid:
        key = str(panel["idx"])
        spec = repair_specs[key]
        if not isinstance(spec, dict):
            raise GenerationHold("REPAIR_SPEC_INVALID")
        refs = get_refs_for_panel([c["char_id"] for c in panel["characters"]])
        bundle = make_bundle(panel, base_prompts[key], refs, spec["repairs"],
                             story_facts=spec["story_facts"], actor=spec["actor"], note=spec["note"])
        candidate["_reviewed_image_retry_plans"][key] = bundle
        hashes = bundle["ref_sha256"]
        fingerprints[key] = [hashlib.sha256(json.dumps(
            [prompt + "\n[model=gemini-2.5-flash-image;aspect=None]", hashes],
            ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
            for prompt in bundle["prompts"]]
    return candidate, fingerprints


def register(source: dict, candidate: dict, fingerprints: dict) -> dict:
    from engine.common.supabase_client import get_client, get_schema

    receipt = get_client().schema(get_schema()).rpc("image_generation_register_repair_plans_v2", {
        "p_expected_script": source, "p_script": candidate, "p_fingerprints": fingerprints,
    }).execute().data
    if not isinstance(receipt, dict) or receipt.get("registered") is not True or receipt.get("hold"):
        raise GenerationHold("REPAIR_REGISTRATION_REJECTED")
    return receipt
