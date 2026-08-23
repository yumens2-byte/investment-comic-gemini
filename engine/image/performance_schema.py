"""Structured contracts for character performance and visual continuity."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

ActionPhase = Literal[
    "ANTICIPATION", "ACTION", "IMPACT", "REACTION", "RECOVERY", "OBSERVATION", "NONE"
]
ShotSize = Literal["ECU", "CU", "MS", "MWS", "FS", "WS"]


class BodyMechanics(BaseModel):
    lead_limb: str | None = None
    support_limb: str | None = None
    weight_direction: str | None = None
    torso: str | None = None
    gaze: str = "toward the focal point"
    expression: str = "intentional and readable"
    secondary_motion: str | None = None


class StagingSpec(BaseModel):
    primary_interaction_pair: list[str] = Field(default_factory=list, max_length=2)
    screen_axis_id: str = Field(default="AXIS_A", pattern=r"^AXIS_[A-Z0-9_]+$")
    screen_direction: Literal["L_TO_R", "R_TO_L", "FRONTAL", "NONE"] = "NONE"
    shot_size: ShotSize
    focal_point: str
    negative_space: Literal["LEFT", "RIGHT", "TOP", "BOTTOM", "NONE"] = "NONE"
    full_body_required: bool = False


class VisualContinuityState(BaseModel):
    location: str = ""
    character_positions: dict[str, Literal["LEFT", "RIGHT", "CENTER", "OFFSCREEN"]] = Field(
        default_factory=dict
    )
    prop_states: dict[str, str] = Field(default_factory=dict)
    injury_states: dict[str, str] = Field(default_factory=dict)
    environment_states: dict[str, str] = Field(default_factory=dict)


class PanelPerformanceSpec(BaseModel):
    version: Literal["performance-spec-1"] = "performance-spec-1"
    panel_idx: int = Field(ge=1, le=10)
    narrative_purpose: str
    subject_id: str | None = None
    action_verb: str
    target_id: str | None = None
    intent: str
    action_phase: ActionPhase
    contact_point: str | None = None
    interaction_required: bool = False
    body_mechanics: BodyMechanics
    staging: StagingSpec
    entering_state: VisualContinuityState
    exiting_state: VisualContinuityState
    must_show: list[str] = Field(default_factory=list, max_length=8)
    must_not_show: list[str] = Field(default_factory=list, max_length=8)
    required_character_ids: list[str] = Field(default_factory=list)
    optional_character_ids: list[str] = Field(default_factory=list)
    source: Literal["PLANNER_V2", "LEGACY_COMPILED"] = "LEGACY_COMPILED"

    @model_validator(mode="after")
    def validate_relationships(self) -> "PanelPerformanceSpec":
        if self.interaction_required and not self.target_id:
            raise ValueError("interaction_required performance needs target_id")
        if self.subject_id and self.subject_id == self.target_id:
            raise ValueError("subject_id and target_id must differ")
        overlap = set(self.required_character_ids) & set(self.optional_character_ids)
        if overlap:
            raise ValueError(f"required and optional characters overlap: {sorted(overlap)}")
        return self


class QualityIssue(BaseModel):
    code: str
    severity: Literal["INFO", "WARNING", "ERROR"]
    panel_idx: int | None = None
    field: str | None = None
    message: str
    repair_hint: str | None = None


class PerformanceValidationResult(BaseModel):
    status: Literal["PASS", "DEGRADED", "FAIL"]
    score: int = Field(ge=0, le=100)
    issues: list[QualityIssue] = Field(default_factory=list)
