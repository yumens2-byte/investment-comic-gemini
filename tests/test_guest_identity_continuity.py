"""Regression for guest identity loss during Notion outages and visual drift."""
import pytest

from engine.common.exceptions import PipelineAborted
from engine.image.prompt_builder import _build_identity_lock, _get_char_designs


def cast():
    return [{"char_id": "CHAR_HERO_003", "role": "hero", "position": "LEFT"},
            {"char_id": "SENTINEL_YIELD", "role": "npc", "position": "RIGHT"}]


def test_guest_identity_survives_runtime_lookup_failure(monkeypatch):
    def unavailable(_):
        raise RuntimeError("Notion unavailable")
    monkeypatch.setattr("engine.common.notion_loader.load_char_design_blocks", unavailable)
    text = _build_identity_lock(cast(), "")
    assert "SENTINEL_YIELD" in text
    assert "adult male" in text
    assert "clean-shaven angular face" in text
    assert "Never change sex" in text
    assert "Never a curved saber" in text


def test_guest_local_contract_overrides_conflicting_runtime_design(monkeypatch):
    monkeypatch.setattr("engine.common.notion_loader.load_char_design_blocks",
                        lambda _: {"SENTINEL_YIELD": {"body": "female robot"}})
    for text in (_build_identity_lock(cast(), ""), _get_char_designs(["SENTINEL_YIELD"])):
        assert "female robot" not in text
        assert "adult male" in text
        assert "short swept-back dark hair" in text


def test_missing_guest_lock_is_fatal_even_during_runtime_outage(monkeypatch, tmp_path):
    from engine.character import guest_visuals
    monkeypatch.setattr(guest_visuals, "_PATH", tmp_path / "missing.yaml")
    monkeypatch.setattr("engine.common.notion_loader.load_char_design_blocks",
                        lambda _: (_ for _ in ()).throw(RuntimeError("offline")))
    with pytest.raises(PipelineAborted, match="Missing guest visual contract"):
        _build_identity_lock(cast(), "")


def test_guest_only_lock_does_not_depend_on_notion(monkeypatch):
    monkeypatch.setattr("engine.common.notion_loader.load_char_design_blocks",
                        lambda _: pytest.fail("Guest identity must be local"))
    assert "adult male" in _build_identity_lock(cast()[1:], "")
