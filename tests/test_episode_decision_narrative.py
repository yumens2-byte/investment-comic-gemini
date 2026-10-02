from engine.narrative.episode_decision import narrative_action_contract


def test_tactical_action_has_no_combat_or_market_fabrication():
    contract = narrative_action_contract({"action_mode": "TACTICAL_ACTION"})
    assert "evacuation, rescue, tracking" in contract
    assert "No new enemy, attacks" in contract
    assert "Keep supplied market facts" in contract


def test_protected_observation_has_no_contract_and_combat_has_no_tactical_override():
    assert narrative_action_contract(None) == ""
    assert narrative_action_contract({"action_mode": "OBSERVATION"}) == ""
    combat = narrative_action_contract({"action_mode": "COMBAT"})
    assert "evacuation, rescue, tracking" not in combat


def test_combat_contract_requires_image_safe_clash_and_keeps_outcome():
    from engine.narrative.episode_decision import COMBAT_ACTION_CONTRACT

    combat = narrative_action_contract({"action_mode": "COMBAT"})
    assert combat == COMBAT_ACTION_CONTRACT
    assert "never fired at" in combat and "No wounds, blood" in combat
    assert "battle outcome" in combat and "canon appearance" in combat


def test_actual_narrative_request_contains_action_contract(monkeypatch):
    from types import SimpleNamespace

    import pytest

    import engine.narrative.claude_client as cc

    class Captured(BaseException):
        pass

    requests = []
    def create(**kwargs):
        requests.append(kwargs)
        raise Captured()
    monkeypatch.setattr(cc, "Anthropic", lambda: SimpleNamespace(messages=SimpleNamespace(create=create)))
    monkeypatch.setattr(cc, "load_system_prompt", lambda: "canon")
    monkeypatch.setattr(cc, "render_user_prompt", lambda **kwargs: "market evidence")
    with pytest.raises(Captured):
        cc.generate_episode(date="2026-10-03", episode_id="test", event_type="NORMAL", delta={},
                            arc_context={}, battle_result={"outcome": "OBSERVATION"}, hero_id="hero", villain_id="",
                            scenario_type="NO_BATTLE", episode_decision={"action_mode": "TACTICAL_ACTION"})
    assert "FINAL ACTION CONTRACT" in requests[0]["messages"][0]["content"]
    assert "market evidence" in requests[0]["messages"][0]["content"]
