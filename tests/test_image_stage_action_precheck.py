"""DR-03: the image stage refuses unsafe combat briefs before any reservation."""
from unittest.mock import MagicMock

import pytest

from engine.image.generation_guard import GenerationHold
from tests.test_action_safety import ACCEPTED_P3, REFUSED_P3


def run_image(monkeypatch, tmp_path, action):
    import engine.image.gemini_client as client
    import engine.image.prompt_builder as builder
    from scripts import run_market

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("PERFORMANCE_SPEC_ENABLED", raising=False)
    paid = MagicMock(side_effect=AssertionError("paid call reached"))
    monkeypatch.setattr(client, "generate_episode", paid)
    built = MagicMock(side_effect=RuntimeError("prompt build reached"))
    monkeypatch.setattr(builder, "build_for_episode", built)
    script = {"panels": [{"idx": 1, "panel_type": "BATTLE", "action": action}]}
    logger = MagicMock()
    with pytest.raises(Exception) as raised:
        run_market.step_image("2026-10-03", "ICG-2026-10-03-001", {}, script, logger)
    return raised.value, paid, built


def test_unsafe_action_blocks_before_prompt_and_paid_call(monkeypatch, tmp_path):
    error, paid, built = run_image(monkeypatch, tmp_path, REFUSED_P3)
    assert isinstance(error, GenerationHold)
    assert "P1 ACTION_ATTACK_ON_CHARACTER" in str(error)
    paid.assert_not_called()
    built.assert_not_called()


def test_safe_action_proceeds_to_prompt_building(monkeypatch, tmp_path):
    error, paid, built = run_image(monkeypatch, tmp_path, ACCEPTED_P3)
    assert "prompt build reached" in str(error)
    built.assert_called_once()
    paid.assert_not_called()
