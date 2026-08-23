"""Compile legacy episode panels into deterministic performance specifications."""

from __future__ import annotations

import re
from typing import Any

from engine.image.performance_schema import (
    BodyMechanics,
    PanelPerformanceSpec,
    StagingSpec,
    VisualContinuityState,
)

_VERBS = (
    ("strike", ("punch", "kick", "slam", "strike", "smash"), "IMPACT", True),
    ("projectile", ("fire", "shoot", "launch", "beam"), "ACTION", True),
    ("defend", ("block", "shield", "parry", "brace"), "REACTION", False),
    ("move", ("leap", "dash", "charge", "dodge"), "ACTION", False),
    ("observe", ("scan", "watch", "analyze", "inspect"), "OBSERVATION", False),
    ("recover", ("kneel", "rise", "breathe", "retreat"), "RECOVERY", False),
)
_SHOT_MAP = {
    "WIDE": "WS",
    "MEDIUM": "MS",
    "CLOSE_UP": "CU",
    "DUTCH": "MWS",
    "LOW_ANGLE": "FS",
}


def _classify_action(action: str, panel_type: str) -> tuple[str, str, bool, bool]:
    lowered = action.lower()
    for family, words, phase, interaction in _VERBS:
        if any(re.search(rf"\b{re.escape(word)}\w*\b", lowered) for word in words):
            return family, phase, interaction, False
    defaults = {
        "COVER": ("confronts", "ANTICIPATION"),
        "TENSION": ("observes", "OBSERVATION"),
        "BATTLE": ("engages", "ACTION"),
        "CLIMAX": ("strikes", "IMPACT"),
        "AFTERMATH": ("recovers", "RECOVERY"),
        "TEXT_CARD": ("none", "NONE"),
        "DISCLAIMER": ("none", "NONE"),
    }
    verb, phase = defaults.get(panel_type, ("acts", "ACTION"))
    return verb, phase, panel_type in {"BATTLE", "CLIMAX"}, True


def _role_character(panel: dict, role: str) -> str | None:
    for character in panel.get("characters") or []:
        if character.get("role") == role and character.get("char_id"):
            return str(character["char_id"])
    return None


def _positions(panel: dict) -> dict[str, str]:
    return {
        str(character["char_id"]): str(character.get("position", "CENTER"))
        for character in panel.get("characters") or []
        if character.get("char_id")
    }


def compile_panel_performance(
    panel: dict[str, Any],
    *,
    previous_exit: VisualContinuityState | None = None,
) -> PanelPerformanceSpec:
    """Compile a panel without an additional model call."""
    panel_type = str(panel.get("panel_type", "BATTLE"))
    action = str(panel.get("action") or "")
    family, phase, interaction, generic = _classify_action(action, panel_type)
    subject = _role_character(panel, "hero") or _role_character(panel, "npc")
    target = _role_character(panel, "villain") if interaction else None
    interaction = bool(interaction and subject and target)
    character_ids = [
        str(character["char_id"])
        for character in panel.get("characters") or []
        if character.get("char_id")
    ]
    required = list(dict.fromkeys([item for item in (subject, target) if item]))
    optional = [item for item in character_ids if item not in required]
    location = str(panel.get("setting") or "")
    entering = previous_exit.model_copy(deep=True) if previous_exit else VisualContinuityState()
    entering.location = location or entering.location
    entering.character_positions.update(_positions(panel))
    exiting = entering.model_copy(deep=True)

    mechanics = BodyMechanics()
    full_body = False
    if family in {"strike", "strikes"}:
        mechanics.lead_limb = "named attacking limb"
        mechanics.support_limb = "opposite foot planted behind the hips"
        mechanics.weight_direction = "through the visible contact point"
        mechanics.torso = "visible hip-and-shoulder rotation"
        mechanics.secondary_motion = "clothing and debris trail opposite the force"
        full_body = "kick" in action.lower()
    elif family == "projectile":
        mechanics.lead_limb = "weapon or casting hand aimed at target"
        mechanics.support_limb = "stable counterbalance"
        mechanics.weight_direction = "braced against recoil"
        mechanics.torso = "aligned behind the projectile path"
    elif phase in {"ACTION", "IMPACT"}:
        mechanics.lead_limb = "the limb leading the named action"
        mechanics.support_limb = "opposite limb visibly supporting balance"
        mechanics.weight_direction = "clearly directed toward the focal point"
        mechanics.torso = "asymmetric rotation appropriate to the action"

    verb = action.strip() or family
    contact = "clearly visible subject-to-target contact" if phase == "IMPACT" and interaction else None
    must_show = list(required)
    if generic:
        must_show.append("a readable non-neutral action silhouette")
    pair = required[:2] if interaction else []
    return PanelPerformanceSpec(
        panel_idx=int(panel.get("idx", 1)),
        narrative_purpose=str(panel.get("key_text") or panel_type),
        subject_id=subject,
        action_verb=verb,
        target_id=target,
        intent=str(panel.get("narration") or "communicate the panel's narrative turn"),
        action_phase=phase,
        contact_point=contact,
        interaction_required=interaction,
        body_mechanics=mechanics,
        staging=StagingSpec(
            primary_interaction_pair=pair,
            shot_size=_SHOT_MAP.get(str(panel.get("camera", "MEDIUM")), "MS"),
            focal_point=contact or verb,
            full_body_required=full_body,
        ),
        entering_state=entering,
        exiting_state=exiting,
        must_show=must_show,
        required_character_ids=required,
        optional_character_ids=optional,
    )


def compile_episode_performance(episode_script: dict[str, Any]) -> list[PanelPerformanceSpec]:
    specs: list[PanelPerformanceSpec] = []
    previous: VisualContinuityState | None = None
    for panel in episode_script.get("panels") or []:
        spec = compile_panel_performance(panel, previous_exit=previous)
        specs.append(spec)
        if panel.get("panel_type") not in {"TEXT_CARD", "DISCLAIMER"}:
            previous = spec.exiting_state
    return specs
