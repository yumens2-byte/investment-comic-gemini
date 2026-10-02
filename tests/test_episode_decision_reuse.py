from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from engine.narrative.episode_decision import resolve_episode_decision
from engine.narrative.episode_type_engine import EpisodeTypeResult
from scripts.run_market import (
    _load_recent_outcomes,
    _load_recent_scenarios,
    _load_reusable_analysis,
    step_analysis,
)


def test_published_history_query_contract(monkeypatch):
    import engine.common.supabase_client as sb

    table = MagicMock()
    for name in ["select", "eq", "lt", "order", "limit"]:
        getattr(table, name).return_value = table
    table.execute.return_value = SimpleNamespace(data=[dict(scenario_type="NO_BATTLE", battle_json={"outcome": "OBSERVATION"})])
    monkeypatch.setattr(sb, "icg_table", lambda _: table)
    assert _load_recent_scenarios("2026-10-03") == ["NO_BATTLE"]
    assert _load_recent_outcomes("2026-10-03") == ["OBSERVATION"]
    assert table.eq.call_args_list[0].args == ("status", "published")
    assert [call.args[0] for call in table.order.call_args_list] == ["episode_date", "episode_no"] * 2
    assert table.lt.call_args.args == ("episode_date", "2026-10-03")


@pytest.mark.parametrize("legacy", [False, True])
def test_saved_analysis_reused_without_reclassification(monkeypatch, legacy):
    import engine.common.supabase_client as sb
    import engine.persist.asset_writer as aw

    ctx = dict(scenario_type="NO_BATTLE", episode_type_v3="TACTICAL", form_bonus=0)
    if not legacy:
        ctx["episode_decision"] = resolve_episode_decision(
            EpisodeTypeResult("TACTICAL", "NO_BATTLE", "ACT_3", "STEP_3_4", "old"),
            risk_level="LOW", event_type="NORMAL", recent_scenarios=[], has_market_evidence=False)
    monkeypatch.setattr(aw, "load_analysis_ctx", lambda _: ctx)
    table = MagicMock()
    table.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [{"id": "existing"}]
    monkeypatch.setattr(sb, "icg_table", lambda _: table)
    log = MagicMock()
    assert step_analysis("2026-10-02", log) is ctx
    log.step_start.assert_not_called()
    assert ("episode_decision" in ctx) is not legacy


def test_legacy_episode_without_context_stops(monkeypatch):
    import engine.common.supabase_client as sb
    import engine.persist.asset_writer as aw

    monkeypatch.setattr(aw, "load_analysis_ctx", lambda _: None)
    table = MagicMock()
    table.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [{"id": "old"}]
    monkeypatch.setattr(sb, "icg_table", lambda _: table)
    with pytest.raises(ValueError, match="refusing reanalysis"):
        _load_reusable_analysis("2026-10-02")
