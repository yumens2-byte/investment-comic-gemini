from unittest.mock import MagicMock

import pytest

from engine.common.exceptions import PipelineAborted
from engine.image.prompt_builder import build_for_episode
from scripts.run_market import step_image


def script():
    return {"panels": [{"idx": 1, "panel_type": "TENSION", "action": "Operate a barrier", "characters": []}],
            "_episode_decision": {"scenario_type": "NO_BATTLE", "action_mode": "TACTICAL_ACTION"}}


def test_final_action_reaches_image_prompt_and_cards_remain_background(monkeypatch):
    monkeypatch.delenv("NOTION_REF_PROMPTS_ID", raising=False)
    data = script()
    data["panels"].append({"idx": 2, "panel_type": "TEXT_CARD", "characters": []})
    prompts = build_for_episode(data)
    assert "Urgent non-combat tactical action" in prompts[0].prompt_text
    assert "quiet non-combat" not in prompts[0].prompt_text
    assert "Abstract environment only" in prompts[1].prompt_text


def test_contradictory_panel_scenario_is_rejected():
    data = script()
    data["panels"][0]["scenario_type"] = "ONE_VS_ONE"
    with pytest.raises(PipelineAborted, match="contradicts"):
        build_for_episode(data)


def test_same_process_image_stage_injects_final_decision(monkeypatch, tmp_path):
    import engine.image.gemini_client as gc
    import engine.image.prompt_builder as pb
    import engine.image.reviewed_inputs as ri
    import engine.persist.asset_writer as aw

    monkeypatch.chdir(tmp_path)
    received = []
    def build(data, **kwargs):
        received.append(data)
        raise RuntimeError("stop before paid generation")
    monkeypatch.setattr(pb, "build_for_episode", build)
    monkeypatch.setattr(ri, "reviewed_panel_prompts", lambda *a, **k: None)
    paid = MagicMock()
    monkeypatch.setattr(gc, "generate_episode", paid)
    monkeypatch.setattr(aw, "patch_by_episode", MagicMock())
    monkeypatch.setenv("PERFORMANCE_SPEC_ENABLED", "false")
    data = script()
    decision = data.pop("_episode_decision")
    with pytest.raises(RuntimeError, match="stop before paid"):
        step_image("2026-10-03", "test", {"episode_decision": decision}, data, MagicMock())
    assert received[0]["_episode_decision"] == decision
    assert "_episode_decision" not in data
    paid.assert_not_called()
