import re
from pathlib import Path

import yaml

WORKFLOW = Path(".github/workflows/run_market.yml")


def _workflow_text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def _workflow_yaml() -> dict:
    return yaml.safe_load(_workflow_text())


def _count_job_env_key(text: str, key: str) -> int:
    return len(re.findall(rf"^      {re.escape(key)}:", text, re.MULTILINE))


def test_run_market_workflow_yaml_parses() -> None:
    assert _workflow_yaml()


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
    env = _workflow_yaml()["jobs"]["pipeline"]["env"]

    assert _count_job_env_key(text, "NARRATIVE_CONTEXT_ENABLED") == 1
    assert _count_job_env_key(text, "STORY_PLANNER_ENABLED") == 1
    assert env["NARRATIVE_CONTEXT_ENABLED"].startswith("${{ (inputs.narrative_context")
    assert env["STORY_PLANNER_ENABLED"].startswith("${{ (inputs.story_planner")
    assert text.count("python -m scripts.run_market --stage narrative") == 1
    assert "legacy workflow dispatch input reference remains" in text
    assert text.count("NARRATIVE_CONTEXT_ENABLED:") == 1
    assert text.count("STORY_PLANNER_ENABLED:") == 1


def test_run_market_workflow_wires_arc_state_v3_flag() -> None:
    text = _workflow_text()
    env = _workflow_yaml()["jobs"]["pipeline"]["env"]

    assert _count_job_env_key(text, "ARC_STATE_V3_ENABLED") == 1
    assert env["ARC_STATE_V3_ENABLED"].startswith("${{ (inputs.arc_state_v3")
    workflow = _workflow_yaml()
    on_block = workflow.get("on") or workflow.get(True)
    assert "arc_state_v3" in on_block["workflow_dispatch"]["inputs"]
    assert "ARC_STATE_V3_ENABLED            =" in text


def test_run_market_workflow_warns_for_all_true_continuity_mode() -> None:
    text = _workflow_text()

    assert "CONTINUITY_STRICT_ENABLED=true: previous-hook payoff failures will stop STEP 4" in text
    assert "all-true continuity mode detected" in text


def test_run_market_workflow_surfaces_major_gate_diagnostics() -> None:
    text = _workflow_text()

    assert "STEP 3.6 — Major Gate Summary" in text
    assert "steps.major_gate.outputs.episode_type_v3" in text
    assert "steps.major_gate.outputs.gate_source" in text
    assert "Schedule cost-control skip expected" in text


def test_deployment_workflows_use_safe_inputs_context_and_env_keys() -> None:
    workflow_paths = sorted(Path(".github/workflows").glob("*.yml"))
    assert workflow_paths

    for path in workflow_paths:
        text = path.read_text(encoding="utf-8")
        parsed = yaml.safe_load(text)
        assert parsed, f"{path} must parse as YAML"
        assert "github." + "event.inputs" not in text, (
            f"{path} should use the schedule-safe inputs context, not github.event.inputs"
        )
        assert not re.search(r"^[ \t]*[A-Za-z_][A-Za-z0-9_]*\s+:", text, re.MULTILINE), (
            f"{path} contains an env/YAML key with whitespace before ':'"
        )
