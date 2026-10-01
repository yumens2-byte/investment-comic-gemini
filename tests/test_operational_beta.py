from types import SimpleNamespace

import pytest

from scripts.run_operational_beta import REQUIRED_ENV, inspect_production


def fake_database(rows, *, fail=False):
    class ReadOnlyQuery:
        def select(self, _):
            return self

        def order(self, *args, **kwargs):
            return self

        def limit(self, _):
            return self

        def execute(self):
            if fail:
                raise RuntimeError("secret-bearing provider error")
            return SimpleNamespace(data=rows)

    return lambda _: ReadOnlyQuery()


@pytest.mark.parametrize("hold", [False, True])
def test_beta_uses_only_reads_and_separates_hold(hold):
    rows = [dict(episode_date="2026-10-01", episode_no=1, status="published",
                 error_message="PUBLISH_HOLD:test" if hold else None,
                 script_json={}, slides_json=[{}])]
    result = inspect_production(fake_database(rows), dict.fromkeys(REQUIRED_ENV, "hidden"))
    assert result["status"] == ("hold" if hold else "pass")
    assert result["database_read"] == "pass"
    assert "hidden" not in str(result)
    assert "database_claim_write" in result["unverified"]


def test_missing_config_prevents_database_access():
    def unexpected(_):
        raise AssertionError("no database request expected")

    assert inspect_production(unexpected, {})["status"] == "failed"


def test_provider_failure_does_not_leak_error_text():
    result = inspect_production(fake_database([], fail=True), dict.fromkeys(REQUIRED_ENV, "hidden"))
    assert result["status"] == "failed"
    assert result["error_type"] == "RuntimeError"
    assert "secret-bearing" not in str(result)


def test_duplicate_episode_identity_fails_beta():
    row = dict(episode_date="2026-10-01", episode_no=1, script_json={})
    result = inspect_production(fake_database([row, row]), dict.fromkeys(REQUIRED_ENV, "hidden"))
    assert result["status"] == "failed"
