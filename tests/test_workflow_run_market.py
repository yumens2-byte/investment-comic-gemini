import re
from pathlib import Path

import pytest
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


@pytest.mark.parametrize("requested_date", ["", "2026-09-14"])
def test_recovery_uses_resolved_preflight_date(tmp_path, monkeypatch, requested_date):
    """Run the workflow's real date export and restore the selected day's panels."""
    import json
    import textwrap

    from scripts.restore_generation_artifact import restore

    step = next(s for s in _workflow_yaml()["jobs"]["pipeline"]["steps"]
                if s.get("id") == "preflight")
    code = step["run"].split("<<'PYCODE'\n", 1)[1].rsplit("PYCODE", 1)[0]
    selected = requested_date or "2026-10-02"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TARGET_DATE", requested_date)
    for key in ("GITHUB_ENV", "GITHUB_OUTPUT", "GITHUB_STEP_SUMMARY"):
        monkeypatch.setenv(key, str(tmp_path / key))
    output = tmp_path / "output"
    output.mkdir()
    (output / "run-market-preflight.json").write_text(json.dumps({
        "episode_date": selected, "allowed": True,
        "mode": "live_preflight", "status": "pass",
    }))
    exec(textwrap.dedent(code), {})
    exported = (tmp_path / "GITHUB_ENV").read_text().strip()
    assert exported == f"TARGET_DATE={selected}"
    source = tmp_path / "source" / selected / "panels"
    source.mkdir(parents=True)
    (source / "P1.png").write_bytes(b"original panel")
    assert restore(exported.split("=", 1)[1], tmp_path / "source", tmp_path / "target") == 1
    assert (tmp_path / "target" / selected / "panels" / "P1.png").read_bytes() == b"original panel"


def test_recovery_requires_allowed_image_stage():
    steps = _workflow_yaml()["jobs"]["pipeline"]["steps"]
    for name in ("Restore original panel artifact", "Restore selected date panels only"):
        condition = next(s for s in steps if s.get("name") == name)["if"]
        assert "steps.preflight.outputs.allowed == 'true'" in condition
        assert "env.DRY_RUN == 'false'" in condition
        assert "(env.RUN_STAGE == 'image' || env.RUN_STAGE == 'all' || env.RUN_STAGE == 'recovery')" in condition


def test_recovery_validates_request_and_runs_only_narrative_persist_image():
    steps = _workflow_yaml()["jobs"]["pipeline"]["steps"]
    validate = next(s for s in steps if s.get("name") == "Validate recovery request")
    assert "generation_revision() < 2" in validate["run"]
    assert 'source.isdigit()' in validate["run"]
    names = [s.get("name") for s in steps]
    assert names.index("Validate recovery request") < names.index("STEP 4 — Narrative (Claude)")
    assert names.index("STEP 5 — Persist") < names.index("Restore selected date panels only")
    assert names.index("Restore selected date panels only") < names.index("STEP 6 — Image Generation (Gemini)")
    for name in ("STEP 4 — Narrative (Claude)", "STEP 5 — Persist", "STEP 6 — Image Generation (Gemini)"):
        assert "env.RUN_STAGE == 'recovery'" in next(s for s in steps if s.get("name") == name)["if"]
    for name in ("STEP 2 — Data Ingest", "STEP 3 — Analysis"):
        assert "env.RUN_STAGE == 'recovery'" not in next(s for s in steps if s.get("name") == name)["if"]


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
    assert _count_job_env_key(text, "SERIAL_NARRATIVE_P0_ENABLED") == 1
    assert env["SERIAL_NARRATIVE_P0_ENABLED"] == "${{ vars.SERIAL_NARRATIVE_P0_ENABLED || 'false' }}"
    assert "SERIAL_NARRATIVE_P0_ENABLED     =" in text


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
