from pathlib import Path

import yaml

WORKFLOW = Path(".github/workflows/run_market.yml")


def _workflow_text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_run_market_workflow_yaml_parses() -> None:
    assert yaml.safe_load(_workflow_text())


def test_run_market_workflow_has_rollout_version_check_after_dependencies() -> None:
    text = _workflow_text()

    assert "ICG_ROLLOUT_VERSION: narrative-context-story-quality-v2" in text
    assert "Rollout version check" in text
    assert "rollout modules import OK" in text
    assert text.index("Install dependencies") < text.index("Rollout version check")


def test_run_market_workflow_uses_normalized_inputs_not_event_inputs() -> None:
    text = _workflow_text()

    assert "github." + "event.inputs" not in text
    assert "RUN_STAGE: ${{ inputs.stage || 'all' }}" in text
    assert "TARGET_DATE: ${{ inputs.target_date || '' }}" in text
    assert "env.RUN_STAGE == 'all'" in text


def test_run_market_workflow_has_single_pilot_flag_definitions() -> None:
    text = _workflow_text()

    assert text.count("NARRATIVE_CONTEXT_ENABLED:") == 1
    assert text.count("STORY_PLANNER_ENABLED:") == 1
    assert text.count("python -m scripts.run_market --stage narrative") == 1
    assert "legacy workflow dispatch input reference remains" in text
    assert "github.event.inputs" not in text
    assert "RUN_STAGE: ${{ inputs.stage || 'all' }}" in text
    assert "TARGET_DATE: ${{ inputs.target_date || '' }}" in text
    assert "env.RUN_STAGE == 'all'" in text
