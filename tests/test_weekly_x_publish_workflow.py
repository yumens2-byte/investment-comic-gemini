"""Regression checks for weekly X hold-and-release wiring."""

from pathlib import Path

import yaml


def _steps(path: str, job: str) -> list[dict]:
    workflow = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return workflow["jobs"][job]["steps"]


def test_generation_workflow_does_not_publish_x_before_hold():
    steps = _steps(".github/workflows/run_weekly_shorts.yml", "weekly_digest")

    assert not any("weekly_publish_x" in step.get("run", "") for step in steps)


def test_release_workflow_publishes_only_weekly_episode_to_x():
    steps = _steps(".github/workflows/publish_shorts.yml", "publish")
    x_step = next(step for step in steps if "weekly_publish_x" in step.get("run", ""))

    assert "startsWith(needs.resolve.outputs.episode_id, 'icg-vw-')" in x_step["if"]
    assert steps.index(x_step) < next(
        index
        for index, step in enumerate(steps)
        if "--stage publish_shorts" in step.get("run", "")
    )


def test_release_workflow_passes_exact_episode_and_x_credentials():
    workflow = yaml.safe_load(
        Path(".github/workflows/publish_shorts.yml").read_text(encoding="utf-8")
    )
    env = workflow["jobs"]["publish"]["env"]

    assert env["TARGET_EPISODE_ID"] == "${{ needs.resolve.outputs.episode_id }}"
    assert {
        "X_API_KEY",
        "X_API_SECRET",
        "X_ACCESS_TOKEN",
        "X_ACCESS_TOKEN_SECRET",
    }.issubset(env)
