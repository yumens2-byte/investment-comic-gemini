"""Prompt contract regressions: no paid image API calls."""
from pathlib import Path

import pytest

from engine.common.exceptions import PipelineAborted
from engine.image import prompt_builder as pb


@pytest.fixture(autouse=True)
def runtime_blocks(monkeypatch):
    monkeypatch.setattr(pb, "_get_style_block", lambda: "COMIC STYLE")
    monkeypatch.setattr(pb, "_get_negative_block", lambda: "NEGATIVE No real people")
    monkeypatch.setattr(pb, "_get_char_designs", lambda ids: "DESIGNS" if ids else "")
    monkeypatch.setattr(pb, "_build_identity_lock", lambda *_: "IDENTITY")
    monkeypatch.setattr(pb, "_get_panel_visual_spec", lambda _: "one character dominant; decisive strike")


def panel(kind="CLIMAX"):
    return {"idx": 1, "panel_type": kind, "characters": [{"char_id": "CHAR_HERO_001", "role": "hero"}, {"char_id": "CHAR_VILLAIN_001", "role": "villain"}], "action": "The opposing forces collide"}


def test_draw_discards_incompatible_peak_spec():
    prompt = pb.build_panel_prompt(panel(), battle_outcome="DRAW")
    assert "one character dominant" not in prompt
    assert "decisive strike" not in prompt
    assert "Balanced stalemate" in prompt


def test_no_battle_removes_forced_battle_spec():
    data = panel()
    data["scenario_type"] = "NO_BATTLE"
    prompt = pb.build_panel_prompt(data)
    assert "one character dominant" not in prompt
    assert "No attacks or forced confrontation" in prompt


@pytest.mark.parametrize("kind", ["TEXT_CARD", "DISCLAIMER"])
def test_empty_card_does_not_force_human_pose(kind):
    prompt = pb.build_panel_prompt({"panel_type": kind, "characters": []})
    assert "No characters, limbs, faces" in prompt
    assert "one character dominant" not in prompt
    assert "mid-action limbs" not in prompt
    assert "Characters MUST be shown" not in prompt


@pytest.mark.parametrize("kind", ["TEXT_CARD", "DISCLAIMER"])
def test_card_rejects_character_cast(kind):
    with pytest.raises(PipelineAborted):
        pb.build_panel_prompt(panel(kind))


def test_chart_rule_does_not_load_runtime_numeric_instructions(monkeypatch):
    monkeypatch.setattr("engine.common.notion_loader.load_chart_direction_rule", lambda: {"SYSTEM_COLLAPSE": "ERROR screens everywhere; positive numbers"})
    prompt = pb.build_panel_prompt(panel(), battle_outcome="SYSTEM_COLLAPSE")
    assert "ERROR screens everywhere" not in prompt
    assert "Abstract warning lights" in prompt


@pytest.mark.parametrize("required", [[], ["CHAR_HERO_001"], ["CHAR_HERO_001", "CHAR_HERO_001"], ["CHAR_HERO_001", "CHAR_UNKNOWN"]])
def test_performance_cast_mismatch_rejected(required):
    with pytest.raises(PipelineAborted):
        pb.build_panel_prompt(panel(), performance_spec={"required_character_ids": required})


def test_species_rule_overrides_generic_mechanics():
    prompt = pb.build_panel_prompt(panel(), performance_spec={"required_character_ids": ["CHAR_HERO_001", "CHAR_VILLAIN_001"], "subject_id": "CHAR_HERO_001"})
    assert "SPECIES PRECEDENCE" in prompt
    assert "Never invent limbs, faces, eyes" in prompt


def test_invalid_performance_target_rejected():
    with pytest.raises(PipelineAborted):
        pb.build_panel_prompt(panel(), performance_spec={"required_character_ids": ["CHAR_HERO_001", "CHAR_VILLAIN_001"], "target_id": "OTHER"})


def test_partial_refs_fail_closed(monkeypatch, tmp_path):
    ref = tmp_path / "hero.png"
    ref.write_bytes(b"reference")
    monkeypatch.setattr("engine.image.ref_loader.get_refs_for_panel", lambda ids: [ref])
    with pytest.raises(PipelineAborted, match="Incomplete character references"):
        pb.build_for_episode({"panels": [panel()]})


def test_reference_paths_must_exist(monkeypatch):
    monkeypatch.setattr("engine.image.ref_loader.get_refs_for_panel", lambda ids: [Path("missing1.png"), Path("missing2.png")])
    with pytest.raises(PipelineAborted):
        pb.build_for_episode({"panels": [panel()]})


def test_episode_outcome_propagates(monkeypatch, tmp_path):
    refs = [tmp_path / "hero.png", tmp_path / "villain.png"]
    for ref in refs:
        ref.write_bytes(b"reference")
    monkeypatch.setattr("engine.image.ref_loader.get_refs_for_panel", lambda ids: refs)
    prompt = pb.build_for_episode({"panels": [panel()]}, battle_outcome="DRAW")[0].prompt_text
    assert "Balanced stalemate" in prompt


def test_partial_designs_use_fallback_per_character(monkeypatch):
    monkeypatch.undo()
    monkeypatch.setattr("engine.common.notion_loader.load_char_design_blocks", lambda ids: {"CHAR_HERO_001": {"name": "Hero"}})
    monkeypatch.setattr("engine.common.notion_loader.char_design_to_prompt_block", lambda char_id, spec: "PRIMARY HERO")
    monkeypatch.setattr(pb, "_get_local_canon_designs", lambda ids: f"LOCAL {ids[0]}")
    assert "LOCAL CHAR_VILLAIN_001" in pb._get_char_designs(["CHAR_HERO_001", "CHAR_VILLAIN_001"])


def test_missing_design_fails_closed(monkeypatch):
    monkeypatch.undo()
    monkeypatch.setattr("engine.common.notion_loader.load_char_design_blocks", lambda ids: {})
    monkeypatch.setattr(pb, "_get_local_canon_designs", lambda ids: "")
    with pytest.raises(PipelineAborted):
        pb._get_char_designs(["CHAR_HERO_001"])


def test_background_performance_does_not_add_human_body_mechanics():
    prompt = pb.build_panel_prompt({"panel_type": "DISCLAIMER", "characters": []}, performance_spec={"required_character_ids": []})
    assert "== BODY MECHANICS ==" not in prompt
    assert "anatomically plausible" not in prompt


@pytest.mark.parametrize("specs", [[{"panel_idx": 2}], [{"panel_idx": 1}, {"panel_idx": 1}]])
def test_incomplete_or_duplicate_episode_performance_rejected(specs):
    with pytest.raises(PipelineAborted, match="performance panel contracts"):
        pb.build_for_episode({"panels": [panel()]}, performance_specs=specs)


def test_runtime_single_character_composition_cannot_remove_cast(monkeypatch):
    monkeypatch.setattr(pb, "_get_panel_visual_spec", lambda _: "COMPOSITION: Single character, data screens background.")
    prompt = pb.build_panel_prompt(panel("TENSION"))
    assert "COMPOSITION: Single character" not in prompt
    assert "Exactly the approved cast (2 characters)" in prompt
