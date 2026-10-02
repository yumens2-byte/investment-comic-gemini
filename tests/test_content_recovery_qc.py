"""Recovery regressions must block sending and avoid extra paid card generation."""
import copy
import hashlib
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PIL import Image

from engine.assembly.pil_composer import compose_episode
from engine.character.guest_visuals import guest_visual_spec
from engine.character.prompt_builder import build_guest_character_prompt
from engine.common.exceptions import PipelineAborted
from engine.image.prompt_builder import _get_char_designs
from engine.publish.claim_guard import claim_publication
from engine.publish.manifest import script_hash
from engine.quality.content_qc import require_content_ready, require_reviewed_sources
from engine.quality.contracts import QualityHold


def reviewed_script(tmp_path):
    source = tmp_path / "P1.png"
    Image.new("RGB", (20, 20), "red").save(source)
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    script = {"_generation_revision": 3,
              "panels": [{"idx": 1, "panel_type": "TENSION", "key_text": "ok"}]}
    script["_recovery_qc"] = {"version": "content-qc-1", "status": "PASS",
                              "script_hash": script_hash(script), "generation_revision": 3,
                              "panel_hashes": {"1": digest}}
    row = {"script_json": script, "error_message": None,
           "panels_json": [{"panel_idx": 1, "path": str(source), "sha256": digest}]}
    return script, row, source


@pytest.mark.parametrize("qc", [None, {}, False, {"status": "HOLD"},
                                 {"version": "content-qc-1", "status": "PASS"}])
def test_incomplete_review_cannot_acquire_publication_claim(monkeypatch, qc):
    from engine.common import supabase_client

    db = Mock(side_effect=AssertionError("claim attempted before content gate"))
    monkeypatch.setattr(supabase_client, "icg_table", db)
    with pytest.raises(QualityHold, match="content QC"):
        claim_publication({"status": "assembled", "script_json": {"_recovery_qc": qc}},
                          "2026-10-02", 1)
    db.assert_not_called()


def test_content_prefix_alone_blocks_claim():
    with pytest.raises(QualityHold):
        require_content_ready({}, {"error_message": "CONTENT_QC_HOLD:visual mismatch"})


def test_review_binds_narrative_revision_and_source_bytes(tmp_path):
    script, row, source = reviewed_script(tmp_path)
    require_content_ready(script, row)
    require_reviewed_sources(script, [source])
    Image.new("RGB", (20, 20), "blue").save(source)
    with pytest.raises(QualityHold, match="bytes changed"):
        require_reviewed_sources(script, [source])
    with pytest.raises(QualityHold):
        require_content_ready({**script, "title": "changed"}, row)
    with pytest.raises(QualityHold):
        require_content_ready({**script, "_generation_revision": 4}, row)
    row["panels_json"][0]["sha256"] = "0" * 64
    with pytest.raises(QualityHold):
        require_content_ready(script, row)


def test_claim_fences_script_changed_after_inspection(tmp_path, monkeypatch):
    from engine.common import supabase_client
    from tests.test_publish_claim_review import AtomicFakeTable

    script, _, _ = reviewed_script(tmp_path)
    table = AtomicFakeTable()
    table.row["script_json"] = {}  # Legacy episode, read before another worker's HOLD.
    before = copy.deepcopy(table.row)
    table.row["script_json"] = script
    monkeypatch.setattr(supabase_client, "icg_table", lambda _: table)
    with pytest.raises(QualityHold, match="claim not acquired"):
        claim_publication(before, "2026-09-25", 2)
    assert table.row["error_message"] is None


def test_resume_force_and_narrative_flag_cannot_bypass_hold(monkeypatch, tmp_path):
    from engine.common import logger, supabase_client
    from scripts import run_resume

    row = {"status": "narrative_done", "script_json": {"_recovery_qc": {"status": "HOLD"}}}
    table = Mock()
    for name in ("select", "eq", "limit"):
        getattr(table, name).return_value = table
    table.execute.return_value = SimpleNamespace(data=[row])
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(supabase_client, "icg_table", lambda _: table)
    monkeypatch.setattr(logger, "StepLogger", Mock())
    monkeypatch.setattr(sys, "argv", ["run_resume", "--episode", "ICG-2026-10-02-001",
                                     "--force", "--allow-narrative-only"])
    with pytest.raises(QualityHold):
        run_resume.main()
    assert not Path("output/episodes/2026-10-02/slides").exists()


def test_text_card_discards_old_chart_and_is_publishable(tmp_path):
    from engine.publish.telegram_publisher import _validate_slides as validate_tg
    from engine.publish.x_publisher import _validate_slides as validate_x

    old = tmp_path / "P1.png"
    Image.new("RGB", (1080, 1350), "red").save(old)
    panels = [{"idx": 1, "panel_type": "TEXT_CARD", "characters": [],
               "market_ref": "WTI +2.13% | VIX -1.15% | BTC +0.96%"}]
    with_old = compose_episode(panels, [old], tmp_path / "old", strict=True)
    without = compose_episode(panels, [], tmp_path / "new", strict=True)
    assert with_old[0].read_bytes() == without[0].read_bytes()
    with Image.open(without[0]) as image:
        assert image.info["icg_render_kind"] == "text_card"
        assert image.getpixel((0, 0)) != (255, 0, 0)
    validate_tg(without)
    validate_x(without)


def test_text_card_with_character_cast_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="cannot contain characters"):
        compose_episode([{"idx": 1, "panel_type": "TEXT_CARD", "characters": [{}]}],
                        [], tmp_path / "slides", strict=True)
    assert not (tmp_path / "slides").exists()


@pytest.mark.parametrize("char_id", ["SENTINEL_YIELD", "CRYPTO_SHADE",
                                     "SECTOR_PHANTOM", "MOMENTUM_RIDER"])
def test_guest_contract_shared_by_narrative_and_image(monkeypatch, char_id):
    monkeypatch.setattr("engine.common.notion_loader.load_char_design_blocks", lambda _: {})
    visual = guest_visual_spec(char_id)
    image_prompt = _get_char_designs([char_id])
    narrative = build_guest_character_prompt({}, {}, [(char_id, "OBSERVER")])
    for text in (image_prompt, narrative):
        assert visual["body"] in text
        assert visual["strict"] in text


def test_missing_guest_contract_stops_before_generation(monkeypatch, tmp_path):
    from engine.character import guest_visuals

    monkeypatch.setattr(guest_visuals, "_PATH", tmp_path / "missing.yaml")
    monkeypatch.setattr("engine.common.notion_loader.load_char_design_blocks", lambda _: {})
    with pytest.raises(PipelineAborted, match="Missing guest visual contract"):
        _get_char_designs(["SENTINEL_YIELD"])


def test_runtime_style_cannot_disable_canon_cel_shading(monkeypatch):
    from engine.image.prompt_builder import _get_style_block

    monkeypatch.setattr("engine.common.notion_loader.load_image_prompt_blocks", lambda: {
        "GLOBAL_STYLE_BLOCK": "hero faces RIGHT.\nNEGATIVE: no flat cel-shading.\nBold ink."})
    style = _get_style_block()
    assert "no flat cel-shading" not in style.lower()
    assert "hero faces RIGHT" in style
    assert "2D cinematic comic illustration" in style


def test_compositor_only_episode_does_not_call_paid_provider(monkeypatch, tmp_path):
    from engine.image import gemini_client, prompt_builder
    from engine.persist import asset_writer
    from scripts import run_market

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("PERFORMANCE_SPEC_ENABLED", raising=False)
    panels = [{"idx": 1, "panel_type": "TEXT_CARD"}]
    monkeypatch.setattr(prompt_builder, "build_for_episode", lambda *_a, **_k: [
        SimpleNamespace(panel_idx=1, prompt_text="card", ref_image_paths=[])])
    paid = Mock(side_effect=AssertionError("must not generate a compositor card"))
    monkeypatch.setattr(gemini_client, "generate_episode", paid)
    monkeypatch.setattr(asset_writer, "patch_by_episode", Mock())
    assert run_market.step_image("2026-10-02", "ICG-2026-10-02-001", {},
                                 {"panels": panels}, Mock()) == [None]
    paid.assert_not_called()


def test_image_stage_generates_only_scene_panels_with_stable_indices(monkeypatch, tmp_path):
    from engine.image import gemini_client, prompt_builder
    from engine.persist import asset_writer
    from scripts import run_market

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("PERFORMANCE_SPEC_ENABLED", raising=False)
    panels = [{"idx": i, "panel_type": kind} for i, kind in enumerate(
        ["TENSION", "TEXT_CARD", "AFTERMATH", "DISCLAIMER"], 1)]
    prompts = [SimpleNamespace(panel_idx=i, prompt_text="scene", ref_image_paths=[])
               for i in range(1, 5)]
    monkeypatch.setattr(prompt_builder, "build_for_episode", lambda *_a, **_k: prompts)
    generation = Mock(return_value=([Path("P1.png"), Path("P3.png")], .08))
    monkeypatch.setattr(gemini_client, "generate_episode", generation)
    patch = Mock()
    monkeypatch.setattr(asset_writer, "patch_by_episode", patch)
    paths = run_market.step_image("2026-10-02", "ICG-2026-10-02-001", {},
                                  {"panels": panels}, Mock())
    assert [p["panel_idx"] for p in generation.call_args.args[0]] == [1, 3]
    assert paths == [Path("P1.png"), None, Path("P3.png"), None]
    saved = patch.call_args.args[2]["panels_json"]
    assert saved == [{"panel_idx": 1, "path": "P1.png"}, {"panel_idx": 2, "path": None},
                     {"panel_idx": 3, "path": "P3.png"}, {"panel_idx": 4, "path": None}]
