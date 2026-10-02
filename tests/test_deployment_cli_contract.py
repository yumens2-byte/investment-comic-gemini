"""Check deployed workflow commands against the actual CLI without running stages."""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
COMMAND = re.compile(r"python(?:3)?\s+-m\s+(scripts\.[a-z_]+)([^\n]*)")


def workflow_commands():
    commands = []
    for path in sorted((ROOT / ".github/workflows").glob("*.yml")):
        workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
        for job in workflow["jobs"].values():
            for step in job.get("steps", []):
                # Join shell continuations without evaluating any shell expressions.
                script = step.get("run", "").replace("\\\n", " ")
                for match in COMMAND.finditer(script):
                    commands.append((path.name, match.group(1), match.group(2)))
    return commands


COMMANDS = workflow_commands()
MODULES_WITH_OPTIONS = sorted({module for _, module, args in COMMANDS if "--" in args})


@pytest.mark.parametrize("module", MODULES_WITH_OPTIONS)
def test_workflow_options_and_stages_exist_in_actual_cli(module):
    """--help exits before DB/API access, even for image and publishing modules."""
    env = {key: value for key, value in os.environ.items()
           if key in {"PATH", "PYTHONPATH", "LANG", "SYSTEMROOT"}}
    env.update(DRY_RUN="true", PYTHONIOENCODING="utf-8")
    result = subprocess.run(
        [sys.executable, "-m", module, "--help"], cwd=ROOT, env=env,
        capture_output=True, text=True, encoding="utf-8", timeout=30,
    )
    assert result.returncode == 0, f"{module}: {result.stderr}"
    supported = set(re.findall(r"--[a-z][a-z-]*", result.stdout))
    for workflow, command_module, args in COMMANDS:
        if command_module != module:
            continue
        requested = set(re.findall(r"--[a-z][a-z-]*", args))
        assert requested <= supported, f"{workflow}: unsupported {requested - supported}"
        for stage in re.findall(r"--stage\s+([a-z_]+)", args):
            assert re.search(rf"\b{re.escape(stage)}\b", result.stdout), (
                f"{workflow}: {module} does not support stage {stage}"
            )


def test_all_workflow_script_modules_exist():
    assert COMMANDS
    for workflow, module, _ in COMMANDS:
        assert (ROOT / (module.replace(".", "/") + ".py")).is_file(), (
            f"{workflow}: missing executable module {module}"
        )


def test_unit_ci_has_no_production_credentials():
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())
    job = workflow["jobs"]["lint-test"]
    assert job["env"]["DRY_RUN"] == "true"
    assert "secrets." not in str(job), "Unit tests must use mocks, not production credentials"
