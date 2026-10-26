"""Reviewed non-contact scene contracts; never rewrite rejected provider inputs."""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata

from engine.image.action_safety import check_action, check_observation_actions
from engine.image.generation_guard import GenerationHold

CARD_TYPES = {"TEXT_CARD", "DISCLAIMER"}
MODES = {"OBSERVATION", "SYMBOLIC_STANDOFF", "ENVIRONMENTAL_CHANGE", "AFTERMATH"}
INTERACTIONS = {"OBSERVE_SEPARATE_DISPLAY", "OBSERVE_ENVIRONMENT", "INSPECT_PROP"}
TARGETS = {"DISPLAY", "ENVIRONMENT", "PROP"}


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def validate_panel_contract(panel: dict, contract: dict) -> None:
    cast = [c.get("char_id") for c in panel.get("characters", [])]
    if (not isinstance(contract, dict) or contract.get("version") != "scene-contract-1"
            or type(contract.get("panel_idx")) is not int
            or contract["panel_idx"] != panel.get("idx")
            or contract.get("visual_mode") not in MODES
            or contract.get("interaction") not in INTERACTIONS
            or contract.get("target_kind") not in TARGETS
            or contract.get("actor_ids") != cast or len(set(cast)) != len(cast)
            or contract.get("physical_contact") is not False
            or contract.get("weapon_discharge") is not False
            or contract.get("injury") != "NONE"
            or not isinstance(contract.get("required_story_facts"), list)
            or not contract["required_story_facts"]
            or any(not isinstance(v, str) or not v.strip() for v in contract["required_story_facts"])
            or not isinstance(contract.get("review_evidence"), str)
            or len(contract["review_evidence"].strip()) < 20):
        raise GenerationHold("SCENE_CONTRACT_INVALID")
    if {"OBSERVE_SEPARATE_DISPLAY": "DISPLAY", "OBSERVE_ENVIRONMENT": "ENVIRONMENT",
            "INSPECT_PROP": "PROP"}[contract["interaction"]] != contract["target_kind"]:
        raise GenerationHold("SCENE_CONTRACT_TARGET_MISMATCH")
    for field in ("action", "setting"):
        value = panel.get(field)
        if (not isinstance(value, str) or not value.strip()
                or contract.get(field + "_sha256") != text_hash(value)):
            raise GenerationHold("SCENE_CONTRACT_TEXT_CHANGED")
        validate_scene_text(value, panel["idx"])


def validate_scene_text(text: str, panel_idx: int) -> None:
    """Conservative review of positive instructions, including runtime additions.

    This is a local eligibility check, not a prediction of provider approval.
    Explicit negative instructions are ignored; mixed clauses stay reviewable.
    """
    normalized = unicodedata.normalize("NFKC", text)
    if len(normalized) > 65536:
        raise GenerationHold("SCENE_TEXT_REVIEW_REQUIRED")
    for line in normalized.splitlines():
        for clause in re.split(r"[.;!?\n]", line):
            clause = clause.strip()
            if not clause:
                continue
            if re.match(r"^(?:no|never|do not|without)\b", clause, re.I):
                # A mixed negative/positive sentence cannot bless the latter.
                if re.search(r"\b(?:but|however|then)\b", clause, re.I):
                    raise GenerationHold("SCENE_TEXT_REVIEW_REQUIRED")
                continue
            physical = check_observation_actions({
                "_episode_decision": {"scenario_type": "NO_BATTLE", "action_mode": "OBSERVATION"},
                "panels": [{"idx": panel_idx, "action": clause}],
            })
            if check_action(clause, panel_idx) or physical or re.search(
                r"\b(?:attacks?|punch\w*|kick\w*|stab\w*|slash\w*|hurl\w*|slam\w*|"
                r"shoot\w*|fir(?:e|es|ed|ing)|collid\w*|crash\w*|blood\w*|gore|"
                r"shockwave\w*|combatants?|clashing)\b", clause, re.I
            ):
                raise GenerationHold("SCENE_TEXT_REVIEW_REQUIRED")


def validate_scene_contracts(script: dict) -> dict:
    contracts = script.get("_scene_contracts")
    if contracts is None:
        return {}
    scenes = script.get("panels")
    if not isinstance(contracts, dict) or not isinstance(scenes, list):
        raise GenerationHold("SCENE_CONTRACT_INVALID")
    if any(not isinstance(p, dict) or type(p.get("idx")) is not int for p in scenes):
        raise GenerationHold("SCENE_CONTRACT_INVALID")
    if len({p["idx"] for p in scenes}) != len(scenes):
        raise GenerationHold("SCENE_CONTRACT_INVALID")
    required = {str(p["idx"]) for p in scenes if p.get("panel_type") not in CARD_TYPES}
    if not required or set(contracts) != required:
        raise GenerationHold("SCENE_CONTRACT_COVERAGE_REQUIRED")
    for panel in scenes:
        if str(panel["idx"]) in required:
            contract = contracts[str(panel["idx"])]
            if isinstance(contract, dict) and contract.get("version") == "reuse-only-scene-1":
                items = (script.get("_reviewed_image_inputs") or {}).get("panels", [])
                matches = [p for p in items if p.get("idx") == panel["idx"]]
                if (contract.get("panel_idx") != panel["idx"] or len(matches) != 1
                        or matches[0].get("reuse_only") is not True
                        or contract.get("panel_sha256") != text_hash(json.dumps(
                            panel, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
                        or any(not isinstance(contract.get(k), str)
                               or not re.fullmatch(r"[0-9a-f]{64}", contract[k])
                               or contract[k] != matches[0].get(k)
                               for k in ("fingerprint", "output_hash"))):
                    raise GenerationHold("PRESERVED_SCENE_CHANGED")
            else:
                validate_panel_contract(panel, contract)
    return contracts
