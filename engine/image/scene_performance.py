"""Versioned non-contact performance briefs. Legacy reviewed inputs remain immutable."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from engine.image.action_safety import check_action
from engine.image.generation_guard import GenerationHold


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Camera(StrictModel):
    shot_size: Literal["ECU", "CU", "MS", "MWS", "FS", "WS"]
    view_angle: Literal["FRONT", "THREE_QUARTER", "SIDE", "OVER_SHOULDER", "DETAIL"]
    elevation: Literal["LOW", "EYE", "HIGH", "PROP"]
    roll_degrees: int = Field(default=0, ge=-30, le=30)
    focal_subject: str = Field(min_length=3, max_length=300)
    depth_layers: str = Field(min_length=3, max_length=500)
    full_body_required: bool = False


class Motion(StrictModel):
    family: Literal["ENTER", "TURN", "BRACE", "PIVOT", "OBSERVE", "AFTERMATH_DETAIL"]
    phase: Literal["ANTICIPATION", "ACTION", "REACTION", "RECOVERY", "OBSERVATION"]
    subject_id: str
    support: str = Field(min_length=3, max_length=300)
    weight: str = Field(min_length=3, max_length=300)
    torso: str = Field(min_length=3, max_length=300)
    gaze: str = Field(min_length=3, max_length=300)
    secondary_motion: str = Field(min_length=3, max_length=300)
    target_kind: Literal["ENVIRONMENT", "PROP", "DISPLAY", "NONE"]
    target: str = Field(min_length=1, max_length=300)


class ScenePerformance(StrictModel):
    version: Literal["scene-performance-2"] = "scene-performance-2"
    panel_idx: int = Field(ge=1, le=10)
    action_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    setting_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    story_cast: list[str] = Field(min_length=1, max_length=6)
    visible_cast: list[str] = Field(min_length=1, max_length=6)
    offscreen_cast: list[str] = Field(default_factory=list, max_length=6)
    must_show_cast: list[str] = Field(default_factory=list, max_length=6)
    required_story_facts: list[str] = Field(min_length=1, max_length=8)
    state_before: str = Field(min_length=3, max_length=500)
    state_after: str = Field(min_length=3, max_length=500)
    visual_delta: str = Field(min_length=3, max_length=500)
    camera: Camera
    motion: Motion
    prop_hands: dict[str, dict[Literal["LEFT", "RIGHT"], str]]
    physical_contact_between_actors: Literal[False] = False
    weapon_discharge: Literal[False] = False
    injury: Literal["NONE"] = "NONE"
    review_evidence: str = Field(min_length=20, max_length=2000)

    @model_validator(mode="after")
    def coherent(self):
        for values in (
            self.story_cast,
            self.visible_cast,
            self.offscreen_cast,
            self.must_show_cast,
        ):
            if len(values) != len(set(values)):
                raise ValueError("duplicate cast")
        visible, offscreen, story = map(
            set, (self.visible_cast, self.offscreen_cast, self.story_cast)
        )
        if visible & offscreen or visible | offscreen != story:
            raise ValueError("visible and offscreen cast must partition story cast")
        if not set(self.must_show_cast) <= visible or self.motion.subject_id not in visible:
            raise ValueError("required subject must be visible")
        if set(self.prop_hands) - story:
            raise ValueError("prop owner outside story cast")
        if self.camera.full_body_required and self.camera.shot_size in {"CU", "ECU"}:
            raise ValueError("full body conflicts with close-up")
        if (
            self.motion.family in {"ENTER", "TURN", "BRACE", "PIVOT"}
            and self.motion.phase == "OBSERVATION"
        ):
            raise ValueError("motion cannot be declared stationary observation")
        if self.motion.family == "AFTERMATH_DETAIL" and self.camera.shot_size not in {"CU", "ECU"}:
            raise ValueError("detail requires CU or ECU")
        return self


def text_hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def payload_hash(value: dict) -> str:
    return text_hash(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")))


def validate_positive_text(text: str, idx: int) -> None:
    """Conservative semantic preflight; not a prediction of provider acceptance.

    Negative constraints are emitted by this module, never accepted as an exemption
    for arbitrary supplied text. The exact canon noun 'fire crown' is not a discharge.
    """
    for clause in re.split(r"[.;!?\n]", text):
        clause = clause.strip()
        if not clause:
            continue
        normalized = re.sub(r"\bfire crown\b", "flame crown", clause, flags=re.I)
        if check_action(normalized, idx) or re.search(
            r"\b(?:attack\w*|punch\w*|kick\w*|stab\w*|slash\w*|slam\w*|shoot\w*|"
            r"fir(?:e|es|ed|ing)|blood\w*|gore|injur\w*|collid\w*|crash\w*|"
            r"shockwave\w*|hit|hits|hitting|strik\w*|struck|smash\w*|hurl\w*|"
            r"blast\w*|discharg\w*|recoil\w*|destroy\w*|contact|shatter\w*)\b",
            normalized,
            re.I,
        ):
            raise GenerationHold(f"P{idx} SCENE_TEXT_REVIEW_REQUIRED")


def validate_scene(panel: dict, value: dict) -> ScenePerformance:
    try:
        spec = ScenePerformance.model_validate(value)
    except (ValueError, TypeError) as exc:
        raise GenerationHold("SCENE_PERFORMANCE_INVALID") from exc
    ids = [c.get("char_id") for c in panel.get("characters", [])]
    if (
        spec.panel_idx != panel.get("idx")
        or spec.story_cast != ids
        or spec.action_sha256 != text_hash(panel.get("action", ""))
        or spec.setting_sha256 != text_hash(panel.get("setting", ""))
    ):
        raise GenerationHold("SCENE_PERFORMANCE_BINDING_CHANGED")

    from pathlib import Path

    import yaml

    locks = yaml.safe_load(
        (Path(__file__).resolve().parents[2] / "config/image_performance_hands.yaml").read_text()
    )
    for char_id in spec.story_cast:
        if char_id in locks and spec.prop_hands.get(char_id) != locks[char_id]:
            raise GenerationHold("CANON_HAND_OCCUPANCY_CHANGED")

    validate_positive_text(panel.get("action", ""), spec.panel_idx)
    validate_positive_text(panel.get("setting", ""), spec.panel_idx)
    if spec.motion.family in {"ENTER", "TURN", "BRACE", "PIVOT"} and re.search(
        r"\b(?:stationary|stand(?:s)? still|remain(?:s)? still)\b", panel.get("action", ""), re.I
    ):
        raise GenerationHold("DYNAMIC_ACTION_CONTRADICTS_STATIONARY_TEXT")

    # All supplied positive strings are inspected, including props, facts and review
    # fields. Unknown instructions do not inherit an observation-only exemption.
    def strings(item):
        if isinstance(item, str):
            yield item
        elif isinstance(item, dict):
            for child in item.values():
                yield from strings(child)
        elif isinstance(item, list):
            for child in item:
                yield from strings(child)

    for text in strings(value):
        validate_positive_text(text, spec.panel_idx)
    return spec


def episode_specs(script: dict) -> dict[int, ScenePerformance]:
    raw = script.get("_scene_performance_v2")
    if raw is None:
        return {}
    if script.get("_scene_contracts") is not None or not isinstance(raw, dict):
        raise GenerationHold("Mixed or malformed scene contract versions")
    panels = script.get("panels", [])
    paid = [p for p in panels if p.get("panel_type") not in {"TEXT_CARD", "DISCLAIMER"}]
    if not paid or set(raw) != {str(p["idx"]) for p in paid}:
        raise GenerationHold("SCENE_PERFORMANCE_COVERAGE_REQUIRED")
    return {p["idx"]: validate_scene(p, raw[str(p["idx"])]) for p in paid}


def render_prompt(panel: dict, spec: ScenePerformance, *, canon: str, style: str) -> str:
    # Revalidate bound inputs at the last point before freezing the prompt.
    validate_scene(panel, spec.model_dump())
    c, m = spec.camera, spec.motion
    hands = json.dumps(spec.prop_hands, ensure_ascii=False, sort_keys=True)
    return "\n".join(
        [
            "PURE VISUAL SCENE. Original fictional adult financial-fantasy characters.",
            f"STORY CHANGE: {spec.visual_delta}",
            f"BEFORE: {spec.state_before}",
            f"AFTER: {spec.state_after}",
            f"ONE ACTION: {panel['action']}",
            f"PHASE: {m.phase}; family={m.family}; subject={m.subject_id}",
            f"SUPPORT: {m.support}; WEIGHT: {m.weight}; TORSO: {m.torso}",
            f"GAZE: {m.gaze}; SECONDARY MOTION: {m.secondary_motion}",
            f"TARGET: {m.target_kind}: {m.target}",
            f"CAMERA: {c.shot_size}; view={c.view_angle}; elevation={c.elevation}; roll={c.roll_degrees} degrees",
            f"FOCAL SUBJECT: {c.focal_subject}; DEPTH: {c.depth_layers}",
            f"VISIBLE CAST ONLY: {', '.join(spec.visible_cast)}. Exactly {len(spec.visible_cast)} figures in this crop.",
            f"OFFSCREEN, still present in story: {', '.join(spec.offscreen_cast) or 'none'}.",
            "Do not widen a close-up to fit offscreen figures or entire bodies. Offscreen props remain in continuity.",
            "POSITION LOCK: "
            + "; ".join(
                f"{ch['char_id']}={ch.get('position', 'CENTER')}"
                for ch in panel["characters"]
                if ch["char_id"] in spec.visible_cast
            ),
            f"CANON HAND OCCUPANCY: {hands}. Render visible portions exactly; never add a free hand.",
            *visual_continuity_locks(spec),
            "CANON AND REFS DEFINE APPEARANCE, NOT POSE: " + canon,
            f"SETTING: {panel['setting']}",
            "REQUIRED STORY FACTS: " + "; ".join(spec.required_story_facts),
            "STYLE: " + style,
            "Keep actors apart. No character-directed attack, weapon discharge, bodily impact, blood or injury.",
            "No additional cast, extra limbs, altered handedness, readable text, letters, numbers, tickers, logos or watermarks.",
            "Preserve reference anatomy and props, bold ink lines, 2D cel shading and detailed backgrounds.",
            "REFERENCE SURFACE OVERRIDE: references supply anatomy, costume and prop silhouette only. "
            "Replace all reference lettering, abbreviations and labels with uninterrupted material. "
            "Every visible shield, signal and background surface is unlabelled; no readable glyphs.",
        ]
    )


def visual_continuity_locks(spec: ScenePerformance) -> list[str]:
    """Additional instructions for newly built prompts; never rewrite frozen inputs."""
    locks = [
        "SHOT LOCK: use the requested crop and perspective; props outside the crop stay offscreen. "
        "Leave the lower caption area free of the focal face and essential surface detail.",
    ]
    if "CHAR_HERO_002" not in spec.visible_cast:
        return locks
    locks.append(
        "PROP IDENTITY LOCK: the heroine has one amber-gold polygonal shield attached to her LEFT forearm "
        "and one lowered black rifle in her RIGHT hand. Preserve the same shield outline and material "
        "throughout the episode; lighting and perspective never turn the shield into a circular disc. "
        "The shield surface has no letters, abbreviations or labels, including those present in references."
    )
    if spec.motion.target_kind == "DISPLAY":
        locks.append(
            "DISPLAY SEPARATION LOCK: the environmental signal is a separate object beyond the heroine, "
            "with a visible background gap from her body and shield. Its light may reflect on her face; "
            "its circular outline never overlays, surrounds or replaces the forearm shield. "
            "In CU framing keep both weapons below the crop; do not expand to a waist-up portrait."
        )
    if spec.motion.family == "AFTERMATH_DETAIL":
        locks.append(
            "DETAIL LOCK: fine surface cracks are the highest-contrast focal detail in the upper image area. "
            "The intact shield outline remains recognizable; the face and rifle stay outside this crop. "
            "Use grazing light and material detail rather than symbols or lettering to reveal the weakness."
        )
    return locks


def rhythm_report(specs: list[ScenePerformance]) -> dict:
    """Declared storyboard checks only; never present them as image observations."""
    dynamic = {"ENTER", "TURN", "BRACE", "PIVOT"}
    warnings = []
    for before, after in zip(specs, specs[1:]):
        if before.motion.family == after.motion.family == "OBSERVE":
            warnings.append(f"P{before.panel_idx}/P{after.panel_idx}: consecutive observation")
    if specs and len({s.camera.shot_size for s in specs}) < min(3, len(specs)):
        warnings.append("insufficient declared shot variation")
    if len(specs) >= 6 and sum(s.motion.family in dynamic for s in specs) < 4:
        warnings.append("fewer than four declared motion/reaction panels")
    if specs and not any(s.camera.shot_size in {"CU", "ECU"} for s in specs):
        warnings.append("no declared close-up")
    return {
        "kind": "DECLARED_STORYBOARD_ONLY",
        "status": "REVIEW" if warnings else "PASS",
        "warnings": warnings,
        "image_quality_status": "UNKNOWN",
    }
