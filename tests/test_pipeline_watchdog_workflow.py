from pathlib import Path

import yaml

WORKFLOWS = Path(".github/workflows")
WATCHDOG = WORKFLOWS / "notify_watchdog.yml"
MONITORED_FILES = (
    "run_market.yml",
    "publish_sns.yml",
    "resume_episode.yml",
    "publish_shorts.yml",
    "run_weekly_shorts.yml",
)


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_watchdog_filters_match_workflow_names_exactly() -> None:
    """workflow_run silently ignores display-name mismatches, including whitespace."""
    watchdog = _load(WATCHDOG)
    monitored_names = watchdog["on"]["workflow_run"]["workflows"]
    actual_names = [_load(WORKFLOWS / filename)["name"] for filename in MONITORED_FILES]

    assert monitored_names == actual_names
    assert len(monitored_names) == len(set(monitored_names))


def test_watchdog_is_manually_testable_and_has_no_repository_permissions() -> None:
    watchdog = _load(WATCHDOG)

    assert "workflow_dispatch" in watchdog["on"]
    assert watchdog["permissions"] == {}


def test_watchdog_does_not_silently_skip_missing_alert_credentials() -> None:
    source = WATCHDOG.read_text(encoding="utf-8")
    credential_guard = source.split('if [ -z "${BOT_TOKEN}" ]', maxsplit=1)[1].split(
        "fi", maxsplit=1
    )[0]

    assert "exit 1" in credential_guard
    assert "exit 0" not in credential_guard
    assert 'response.get("ok") is not True' in source
