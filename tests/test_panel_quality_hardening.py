"""Reproduce the paid pilot's font and prop-continuity failures without paid calls."""

import hashlib
from copy import deepcopy
from unittest.mock import Mock

import pytest
from PIL import Image, ImageFont

from engine.assembly import pil_composer as composer
from engine.image.generation_guard import GenerationHold
from engine.image.quality_candidates import rebuild_previews
from engine.image.scene_performance import episode_specs, render_prompt
from engine.image.vault_retake import _FACTS, repair_vault_brief
from tests.test_dynamic_image_quality import frozen as original_frozen
from tests.test_dynamic_image_quality import panel, spec


@pytest.fixture
def frozen(monkeypatch, tmp_path):
    return original_frozen.__wrapped__(monkeypatch, tmp_path)


def vault_script():
    script = {"date": "2026-10-20", "panels": [], "_scene_performance_v2": {}}
    for idx in range(1, 7):
        p = panel()
        p.update(idx=idx, narration=f"변경 금지 내레이션 {idx}", key_text="균형 유지")
        p["characters"][0]["char_id"] = "CHAR_HERO_002"
        s = spec(p)
        s.update(
            panel_idx=idx,
            story_cast=["CHAR_HERO_002", "villain"],
            visible_cast=["CHAR_HERO_002"],
            must_show_cast=["CHAR_HERO_002"],
            prop_hands={"CHAR_HERO_002": {"LEFT": "shield", "RIGHT": "rifle"}},
            required_story_facts=[_FACTS.get(idx, "unchanged_opening")],
        )
        s["motion"]["subject_id"] = "CHAR_HERO_002"
        script["panels"].append(p)
        script["_scene_performance_v2"][str(idx)] = s
    return script


def test_retake_covers_p3_through_p6_and_preserves_story_and_opening():
    source = vault_script()
    source["_reviewed_image_inputs"] = {"immutable": True}
    source["_generation_revision"] = 3
    original = deepcopy(source)
    fixed = repair_vault_brief(source)
    assert source == original
    assert fixed["panels"][:2] == source["panels"][:2]
    assert "_reviewed_image_inputs" not in fixed
    assert "_generation_revision" not in fixed
    for old, new in zip(source["panels"], fixed["panels"]):
        assert {k: v for k, v in old.items() if k not in {"action", "setting"}} == {
            k: v for k, v in new.items() if k not in {"action", "setting"}
        }
    specs = episode_specs(fixed)
    assert [specs[i].camera.shot_size for i in range(3, 7)] == ["FS", "MWS", "CU", "ECU"]
    assert "shield and rifle stay entirely below the crop" in fixed["panels"][4]["action"]
    for idx in range(3, 7):
        assert specs[idx].required_story_facts == episode_specs(source)[idx].required_story_facts
        prompt = render_prompt(
            fixed["panels"][idx - 1], specs[idx], canon="red gold armor", style="bold ink"
        )
        assert "PROP IDENTITY LOCK" in prompt
        assert "REFERENCE SURFACE OVERRIDE" in prompt
    p5 = render_prompt(fixed["panels"][4], specs[5], canon="red gold armor", style="bold ink")
    assert "DISPLAY SEPARATION LOCK" in p5
    assert "visible background gap" in p5
    assert "DETAIL LOCK" in render_prompt(fixed["panels"][5], specs[6], canon="armor", style="ink")


def test_unrelated_story_cannot_receive_vault_retake():
    source = vault_script()
    source["_scene_performance_v2"]["4"]["required_story_facts"] = ["a different ending"]
    with pytest.raises(GenerationHold, match="matching story facts"):
        repair_vault_brief(source)


def test_source_assembly_provenance_cannot_approve_changed_brief(tmp_path):
    from engine.publish.manifest import build_manifest, validate_manifest

    source = vault_script()
    slide = tmp_path / "old.png"
    Image.new("RGB", (1080, 1350), "blue").save(slide)
    source["_assembly_manifest"] = build_manifest(source, [slide])
    fixed = repair_vault_brief(source)
    assert fixed["_assembly_manifest"] == source["_assembly_manifest"]
    with pytest.raises(ValueError, match="manifest mismatch"):
        validate_manifest(fixed, [slide])


def test_missing_korean_font_stops_before_slide_is_written(monkeypatch, tmp_path):
    monkeypatch.setattr(composer, "_get_font", lambda size: ImageFont.load_default())
    source = tmp_path / "P3.png"
    Image.new("RGB", (896, 1152), "blue").save(source)
    output = tmp_path / "slide.png"
    with pytest.raises(ValueError, match="Korean glyphs unavailable"):
        composer._compose_image_slide(
            output, source, "균형", "방패의 균열을 확인한다", 3, None, strict=True
        )
    assert not output.exists()


def test_missing_korean_font_stops_before_reservation_or_provider(frozen, monkeypatch, tmp_path):
    from engine.image import gemini_client
    from engine.image import quality_candidates as q

    bundle = deepcopy(frozen)
    bundle["candidate_script"]["panels"][0]["narration"] = "실제 한글 내레이션"
    client = Mock()
    client.schema.return_value.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [
        {"state": "APPROVED", "bundle": bundle}
    ]
    monkeypatch.setattr("engine.common.supabase_client.get_client", lambda: client)
    monkeypatch.setattr(composer, "_get_font", lambda size: ImageFont.load_default())
    reservation, provider = Mock(), Mock()
    monkeypatch.setattr(q, "rpc", reservation)
    monkeypatch.setattr(gemini_client, "generate_panel", provider)
    with pytest.raises(ValueError, match="Korean glyphs unavailable"):
        q.generate(bundle["id"], tmp_path)
    reservation.assert_not_called()
    provider.assert_not_called()


def test_real_korean_glyphs_are_available():
    # Required in CI, never silently skip the reproduction of the paid pilot defect.
    composer.require_korean_font(["한글 제목 방패 균열 금고 내레이션"])
    font = composer._get_font(34)
    assert bytes(font.getmask("한")) != bytes(font.getmask("글"))
    assert font.getbbox("한글")[2] > 40


def test_old_frozen_prompt_is_not_rebuilt_after_renderer_changes(frozen, monkeypatch):
    from engine.image import reviewed_inputs, scene_performance

    before = deepcopy(frozen["candidate_script"])
    monkeypatch.setattr(
        scene_performance, "render_prompt", Mock(side_effect=AssertionError("must not rebuild"))
    )
    prompts = reviewed_inputs.reviewed_panel_prompts(before)
    assert prompts[0].prompt_text == before["_reviewed_image_inputs"]["panels"][0]["prompt_text"]
    assert before == frozen["candidate_script"]


def preview_fixture(tmp_path):
    source = tmp_path / "art"
    source.mkdir()
    panels, receipts = [], []
    for idx in (3, 5, 6):
        path = source / f"P{idx}.png"
        Image.new("RGB", (896, 1152), "blue").save(path)
        panels.append(
            dict(
                idx=idx,
                key_text="균형 유지",
                narration="금고 앞 방패의 균열",
                market_ref="VIX 18.44",
            )
        )
        receipts.append(
            dict(panel_idx=idx, output_hash=hashlib.sha256(path.read_bytes()).hexdigest())
        )
    return {"panels": panels}, {"panels": receipts}, source


def test_offline_recomposition_uses_same_pngs_and_never_calls_provider(tmp_path, monkeypatch):
    from engine.image import gemini_client
    from engine.image import quality_candidates as q

    script, receipt, root = preview_fixture(tmp_path)
    hashes = [hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.glob("*.png"))]
    provider, db = (
        Mock(side_effect=AssertionError("paid call")),
        Mock(side_effect=AssertionError("db write")),
    )
    monkeypatch.setattr(gemini_client, "generate_panel", provider)
    monkeypatch.setattr(q, "rpc", db)
    outputs = rebuild_previews(script, receipt, root, tmp_path / "fixed")
    assert len(outputs) == 3
    assert all(Image.open(path).size == (1080, 1350) for path in outputs)
    assert hashes == [
        hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.glob("*.png"))
    ]
    provider.assert_not_called()
    db.assert_not_called()


@pytest.mark.parametrize("defect", ["last_hash", "duplicate", "unknown_panel"])
def test_bad_receipt_writes_no_partial_preview(tmp_path, defect):
    script, receipt, root = preview_fixture(tmp_path)
    if defect == "last_hash":
        receipt["panels"][-1]["output_hash"] = "0" * 64
    elif defect == "duplicate":
        receipt["panels"].append(receipt["panels"][0])
    else:
        receipt["panels"][-1]["panel_idx"] = 99
    output = tmp_path / "fixed"
    with pytest.raises(GenerationHold):
        rebuild_previews(script, receipt, root, output)
    assert not output.exists()
