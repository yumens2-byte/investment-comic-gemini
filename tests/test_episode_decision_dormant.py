"""DR-04: a dormant combat path is re-enabled only with recent evidence."""
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from engine.narrative import path_readiness
from engine.narrative.episode_decision import resolve_episode_decision, validate_saved_decision
from engine.narrative.episode_type_engine import EpisodeTypeResult


def candidate(kind="TACTICAL", scenario="NO_BATTLE", step="STEP_3_4"):
    return EpisodeTypeResult(kind, scenario, "ACT_3", step, "candidate")


def resolve(ready, **overrides):
    calls = []

    def probe():
        calls.append(1)
        return ready

    params = dict(risk_level="MEDIUM", event_type="BATTLE", recent_scenarios=["NO_BATTLE"] * 7,
                  has_market_evidence=True, combat_path_ready=probe)
    params.update(overrides)
    return resolve_episode_decision(candidate(), **params), calls


def test_verified_path_keeps_policy_battle():
    result, calls = resolve((True, "published:2026-10-03"))
    assert (result["scenario_type"], result["action_mode"]) == ("ONE_VS_ONE", "COMBAT")
    assert result["path_readiness"] == "published:2026-10-03" and calls == [1]


def test_dormant_path_falls_back_to_tactical_action():
    result, _ = resolve((False, "dormant"))
    assert (result["episode_type"], result["scenario_type"], result["action_mode"]) == (
        "TACTICAL", "NO_BATTLE", "TACTICAL_ACTION")
    assert result["reason"] == "dormant_path_unverified" and result["form_bonus"] == 0
    validate_saved_decision({"episode_decision": result, "scenario_type": "NO_BATTLE",
                             "episode_type_v3": "TACTICAL", "form_bonus": 0})


@pytest.mark.parametrize("overrides", [dict(risk_level="LOW"),
                                       dict(recent_scenarios=["NO_BATTLE"])])
def test_probe_not_called_when_policy_does_not_switch_to_combat(overrides):
    _, calls = resolve((False, "dormant"), **overrides)
    assert calls == []


def test_without_probe_behaviour_is_unchanged():
    result = resolve_episode_decision(candidate(), risk_level="MEDIUM", event_type="BATTLE",
                                      recent_scenarios=["NO_BATTLE"] * 7,
                                      has_market_evidence=True)
    assert result["scenario_type"] == "ONE_VS_ONE" and "path_readiness" not in result


class Table:
    def __init__(self, data, filters):
        self.data, self.filters = data, filters

    def select(self, *_):
        return self

    def eq(self, column, value):
        self.filters.append(("eq", column, value))
        return self

    def gte(self, column, value):
        self.filters.append(("gte", column, value))
        return self

    def lt(self, column, value):
        self.filters.append(("lt", column, value))
        return self

    def limit(self, *_):
        return self

    def execute(self):
        if isinstance(self.data, Exception):
            raise self.data
        return SimpleNamespace(data=self.data)


@pytest.fixture
def tables(monkeypatch):
    state = {"episode_assets": [], "path_canary_runs": [], "filters": []}
    from engine.common import supabase_client

    monkeypatch.setattr(supabase_client, "icg_table",
                        lambda name: Table(state[name], state["filters"]))
    return state


NOW = datetime(2026, 10, 3, 12, tzinfo=timezone.utc)


def test_recent_publication_verifies_path(tables):
    tables["episode_assets"] = [{"episode_date": "2026-10-03"}]
    assert path_readiness.combat_path_ready("2026-10-04", today=NOW) == (
        True, "published:2026-10-03")
    assert ("gte", "episode_date", "2026-09-04") in tables["filters"]
    assert ("eq", "scenario_type", "ONE_VS_ONE") in tables["filters"]


def test_recent_canary_verifies_path(tables):
    tables["path_canary_runs"] = [{"created_at": "2026-10-02T00:00:00+00:00"}]
    ready, evidence = path_readiness.combat_path_ready("2026-10-04", today=NOW)
    assert ready and evidence.startswith("canary:")
    assert ("eq", "status", "pass") in tables["filters"]
    assert ("gte", "created_at", "2026-09-26T12:00:00+00:00") in tables["filters"]


def test_no_evidence_is_dormant(tables):
    assert path_readiness.combat_path_ready("2026-10-04", today=NOW) == (False, "dormant")


@pytest.mark.parametrize("table,reason", [("episode_assets", "lookup_failed"),
                                          ("path_canary_runs", "canary_lookup_failed")])
def test_lookup_failure_is_not_ready(tables, table, reason):
    tables[table] = RuntimeError("relation does not exist")
    assert path_readiness.combat_path_ready("2026-10-04", today=NOW) == (False, reason)
