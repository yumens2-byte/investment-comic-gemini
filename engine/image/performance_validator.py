"""Deterministic preflight validation for panel performance specs."""

from __future__ import annotations

from engine.image.performance_schema import (
    PanelPerformanceSpec,
    PerformanceValidationResult,
    QualityIssue,
)


def _issue(spec: PanelPerformanceSpec, code: str, severity: str, message: str) -> QualityIssue:
    return QualityIssue(code=code, severity=severity, panel_idx=spec.panel_idx, message=message)


def validate_panel_performance(
    panel: dict, spec: PanelPerformanceSpec
) -> PerformanceValidationResult:
    issues: list[QualityIssue] = []
    panel_type = panel.get("panel_type", "BATTLE")
    character_ids = {
        character.get("char_id") for character in panel.get("characters") or []
    }
    if panel_type not in {"TEXT_CARD", "DISCLAIMER"} and character_ids and not spec.subject_id:
        issues.append(_issue(spec, "PERF_E_SUBJECT_MISSING", "ERROR", "subject is required"))
    if spec.interaction_required and not spec.target_id:
        issues.append(_issue(spec, "PERF_E_TARGET_MISSING", "ERROR", "target is required"))
    missing = set(spec.required_character_ids) - character_ids
    if missing:
        issues.append(
            _issue(spec, "PERF_E_REQUIRED_CHAR_MISSING", "ERROR", f"missing {sorted(missing)}")
        )
    if spec.action_phase == "IMPACT" and spec.interaction_required and not spec.contact_point:
        issues.append(_issue(spec, "PERF_E_CONTACT_MISSING", "ERROR", "contact is required"))
    mechanics = spec.body_mechanics
    if panel_type in {"BATTLE", "CLIMAX"} and spec.action_phase in {"ACTION", "IMPACT"}:
        required = (mechanics.lead_limb, mechanics.support_limb, mechanics.weight_direction, mechanics.torso)
        if not all(required):
            issues.append(
                _issue(
                    spec,
                    "PERF_E_BODY_MECHANICS_INCOMPLETE",
                    "ERROR",
                    "dynamic battle action needs complete body mechanics",
                )
            )
    if spec.staging.full_body_required and spec.staging.shot_size in {"ECU", "CU"}:
        issues.append(_issue(spec, "PERF_E_CAMERA_CROP", "ERROR", "full body action is cropped"))
    complexity = len(spec.required_character_ids) * 2 + len(spec.optional_character_ids)
    complexity += 2 if spec.interaction_required else 0
    if complexity >= 11:
        issues.append(_issue(spec, "PERF_E_COMPLEXITY_BUDGET", "ERROR", "complexity >= 11"))
    if any("readable non-neutral action silhouette" in item for item in spec.must_show):
        issues.append(
            _issue(spec, "PERF_W_ACTION_GENERIC", "WARNING", "legacy action was generic")
        )
    errors = sum(issue.severity == "ERROR" for issue in issues)
    warnings = sum(issue.severity == "WARNING" for issue in issues)
    score = max(0, 100 - errors * 25 - warnings * 5)
    status = "FAIL" if errors else ("PASS" if score >= 85 else "DEGRADED")
    return PerformanceValidationResult(status=status, score=score, issues=issues)


def validate_episode_performance(
    episode_script: dict, specs: list[PanelPerformanceSpec]
) -> PerformanceValidationResult:
    panels = {int(panel.get("idx", 0)): panel for panel in episode_script.get("panels") or []}
    issues: list[QualityIssue] = []
    for spec in specs:
        issues.extend(validate_panel_performance(panels.get(spec.panel_idx, {}), spec).issues)
    narrative_specs = [
        spec for spec in specs
        if panels.get(spec.panel_idx, {}).get("panel_type") not in {"TEXT_CARD", "DISCLAIMER"}
    ]
    for previous, current in zip(narrative_specs, narrative_specs[1:]):
        before = previous.exiting_state
        after = current.entering_state
        if before.location and after.location and before.location != after.location:
            issues.append(
                _issue(current, "PERF_W_LOCATION_DISCONTINUITY", "WARNING", "location changed between panels")
            )
        state_groups = (
            ("character_positions", "PERF_W_POSITION_DISCONTINUITY", "WARNING"),
            ("prop_states", "PERF_E_PROP_DISCONTINUITY", "ERROR"),
            ("injury_states", "PERF_E_INJURY_DISCONTINUITY", "ERROR"),
            ("environment_states", "PERF_E_ENVIRONMENT_DISCONTINUITY", "ERROR"),
        )
        for field, code, severity in state_groups:
            previous_values = getattr(before, field)
            current_values = getattr(after, field)
            changed = {
                key: (previous_values[key], current_values[key])
                for key in previous_values.keys() & current_values.keys()
                if previous_values[key] != current_values[key]
            }
            if changed:
                issues.append(_issue(current, code, severity, f"unexplained state change: {changed}"))
    errors = sum(issue.severity == "ERROR" for issue in issues)
    warnings = sum(issue.severity == "WARNING" for issue in issues)
    score = max(0, 100 - errors * 25 - warnings * 5)
    status = "FAIL" if errors else ("PASS" if score >= 85 else "DEGRADED")
    return PerformanceValidationResult(status=status, score=score, issues=issues)
