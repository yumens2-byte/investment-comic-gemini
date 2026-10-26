"""Meaningful contracts for cinematic briefs, frozen inputs and protected retakes."""

import hashlib
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock

import pytest
from PIL import Image, ImageDraw

from engine.image.generation_guard import GenerationHold
from engine.image.scene_performance import (
    ScenePerformance,
    episode_specs,
    render_prompt,
    rhythm_report,
    text_hash,
    validate_positive_text,
    validate_scene,
)


def panel():
    return {
        "idx": 1,
        "panel_type": "CLIMAX",
        "action": "The heroine pivots toward the changing dial",
        "setting": "A deep financial vault",
        "camera": "CLOSE_UP",
        "characters": [
            {"char_id": "hero", "role": "hero"},
            {"char_id": "villain", "role": "villain"},
        ],
    }


def spec(p=None):
    p = p or panel()
    return {
        "version": "scene-performance-2",
        "panel_idx": p["idx"],
        "action_sha256": text_hash(p["action"]),
        "setting_sha256": text_hash(p["setting"]),
        "story_cast": ["hero", "villain"],
        "visible_cast": ["hero"],
        "offscreen_cast": ["villain"],
        "must_show_cast": ["hero"],
        "required_story_facts": ["The vault remains unresolved"],
        "state_before": "The dial remains dim",
        "state_after": "The dial turns golden",
        "visual_delta": "A new signal reveals the unresolved vault",
        "camera": {
            "shot_size": "CU",
            "view_angle": "THREE_QUARTER",
            "elevation": "EYE",
            "focal_subject": "The heroine face",
            "depth_layers": "face, glow, distant vault",
        },
        "motion": {
            "family": "TURN",
            "phase": "REACTION",
            "subject_id": "hero",
            "support": "planted left foot",
            "weight": "forward into the turn",
            "torso": "shoulders rotate right",
            "gaze": "the golden dial",
            "secondary_motion": "cape follows the turn",
            "target_kind": "DISPLAY",
            "target": "dial",
        },
        "prop_hands": {"hero": {"LEFT": "shield", "RIGHT": "lowered rifle"}},
        "physical_contact_between_actors": False,
        "weapon_discharge": False,
        "injury": "NONE",
        "review_evidence": "Reviewed cinematic reaction with the unchanged story and canon.",
    }


def test_noncontact_motion_and_closeup_do_not_require_all_cast_in_frame():
    s = validate_scene(panel(), spec())
    prompt = render_prompt(panel(), s, canon="red gold armor", style="bold ink")
    assert "CAMERA: CU;" in prompt
    assert "Exactly 1 figures in this crop" in prompt
    assert "OFFSCREEN, still present in story: villain" in prompt
    assert "stationary figures" not in prompt
    assert prompt.index("ONE ACTION") < prompt.index("STYLE:")
    assert "shoulders rotate right" in prompt


@pytest.mark.parametrize(
    "change",
    [
        lambda s: s.update(visible_cast=["hero", "villain"]),
        lambda s: s.update(offscreen_cast=["stranger"]),
        lambda s: s.update(must_show_cast=["villain"]),
        lambda s: s["camera"].update(full_body_required=True),
        lambda s: s["motion"].update(subject_id="villain"),
        lambda s: s["motion"].update(target_kind="ACTOR"),
        lambda s: s["motion"].update(phase="OBSERVATION"),
        lambda s: s.update(weapon_discharge=True),
        lambda s: s.update(extra_field="hidden instructions"),
        lambda s: s["prop_hands"].update(stranger={"LEFT": "shield"}),
    ],
)
def test_invalid_contracts_fail_before_any_call(change):
    s = spec()
    change(s)
    with pytest.raises(GenerationHold):
        validate_scene(panel(), s)


@pytest.mark.parametrize(
    "text",
    [
        "The heroine steps forward",
        "The heroine raises her shield",
        "The Titan has a fire crown",
        "The camera moves into a close-up",
    ],
)
def test_nonviolent_movement_and_canon_nouns_are_not_attacks(text):
    validate_positive_text(text, 1)


@pytest.mark.parametrize(
    "text",
    [
        "The heroine fires the rifle",
        "The villain punches the heroine",
        "The titan crashes into a column",
        "No blood but then stab him",
        "No attacks. The heroine shoots at him",
        "The heroine hits the Titan",
    ],
)
def test_unsafe_and_mixed_negative_positive_instructions_hold(text):
    with pytest.raises(GenerationHold):
        validate_positive_text(text, 1)


def test_scene_hash_cast_and_coverage_are_bound():
    p = panel()
    s = spec()
    script = {"panels": [p], "_scene_performance_v2": {"1": s}}
    assert episode_specs(script)[1].motion.family == "TURN"
    script["panels"][0]["action"] = "changed"
    with pytest.raises(GenerationHold):
        episode_specs(script)
    script["panels"][0] = panel()
    script["_scene_contracts"] = {}
    with pytest.raises(GenerationHold):
        episode_specs(script)
    script.pop("_scene_contracts")
    script["_scene_performance_v2"] = {}
    with pytest.raises(GenerationHold):
        episode_specs(script)


def test_rhythm_report_is_not_an_image_quality_claim():
    report = rhythm_report([ScenePerformance.model_validate(spec())])
    assert report["image_quality_status"] == "UNKNOWN"
    assert report["kind"] == "DECLARED_STORYBOARD_ONLY"


def test_audit_evidence_is_bound_but_never_rendered_as_an_instruction():
    from engine.image.scene_performance import payload_hash
    original = spec()
    reviewed = deepcopy(original)
    reviewed['review_evidence'] = 'Reviewed non-contact movement with no injury.'
    s = validate_scene(panel(), reviewed)
    assert payload_hash(reviewed) != payload_hash(original)
    prompt = render_prompt(panel(), s, canon='red gold armor', style='bold ink')
    assert reviewed['review_evidence'] not in prompt
    reviewed['motion']['torso'] = 'The heroine makes contact with the villain'
    with pytest.raises(GenerationHold, match='TEXT_REVIEW_REQUIRED'):
        validate_scene(panel(), reviewed)


@pytest.mark.parametrize('role,block,code', [
    ('style', 'Bodies angled toward center contact point.', 'TEXT_REVIEW_REQUIRED'),
    ('canon', 'Shield surface includes ETF text.', 'SURFACE_TEXT_REVIEW_REQUIRED'),
    ('style', 'Both figures remain stationary.', 'MOTION_CONFLICT'),
    ('canon', 'Show every full character visible.', 'CROP_CONFLICT'),
    ('style', 'No attacks. The heroine shoots at him.', 'TEXT_REVIEW_REQUIRED'),
    ('canon', 'No text but paint the ETF letters.', 'SURFACE_TEXT_REVIEW_REQUIRED'),
])
def test_final_runtime_render_blocks_cannot_override_scene(role, block, code):
    blocks = {'canon': 'red gold armor', 'style': 'bold cel shading'}
    blocks[role] = block
    with pytest.raises(GenerationHold, match=code):
        render_prompt(panel(), validate_scene(panel(), spec()), **blocks)


def test_exact_surface_prohibition_does_not_trigger_typography_conflict():
    prompt = render_prompt(panel(), validate_scene(panel(), spec()),
                           canon='red armor. No readable text, letters or numbers.',
                           style='bold ink. Without logos.')
    assert 'red armor' in prompt


def test_new_quality_inputs_bind_reference_forms(frozen):
    inputs = frozen['candidate_script']['_reviewed_image_inputs']
    assert inputs['ref_binding_version'] == 'canon-form-1'
    assert [b['char_id'] for b in inputs['panels'][0]['ref_bindings']] == ['hero', 'villain']
    from engine.image.reviewed_inputs import reviewed_panel_prompts
    inputs['panels'][0]['ref_bindings'][0]['form'] = 'form999'
    with pytest.raises(GenerationHold, match='form binding changed'):
        reviewed_panel_prompts(frozen['candidate_script'])


@pytest.fixture
def frozen(monkeypatch, tmp_path):
    from engine.image import prompt_builder, ref_loader, reviewed_inputs
    from engine.image.quality_candidates import prepare

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ICG_GENERATION_REVISION", "3")
    refs = []
    for name in ("hero", "villain"):
        ref = Path(f"assets/characters/{name}.png")
        ref.parent.mkdir(parents=True, exist_ok=True)
        ref.write_bytes(name.encode())
        refs.append(ref)
    monkeypatch.setattr(ref_loader, "get_refs_for_panel", lambda ids: refs if ids else [])
    monkeypatch.setattr(ref_loader, "_load_canon", lambda: {"heroes": {
        name: {"ref": str(ref), "sha256": hashlib.sha256(ref.read_bytes()).hexdigest()}
        for name, ref in zip(("hero", "villain"), refs)
    }})
    monkeypatch.setattr(reviewed_inputs, "get_refs_for_panel", lambda ids: refs if ids else [])
    monkeypatch.setattr(prompt_builder, "_get_char_designs", lambda ids: "Approved red gold armor")
    monkeypatch.setattr(prompt_builder, "_get_style_block", lambda: "Bold cel shading")
    p = panel()
    source = {"date": "2026-10-20", "panels": [p]}
    candidate = deepcopy(source)
    candidate["_scene_performance_v2"] = {"1": spec(p)}
    base = [
        {
            "panel_idx": 1,
            "output_hash": "a" * 64,
            "artifact_run_id": "123",
            "artifact_name": "episode-123",
            "artifact_path": "2026-10-20/panels/P1.png",
        }
    ]
    bundle = prepare(
        source, candidate, base, revision=3, panels=[1], base_run_id="123", max_cost_usd=0.1
    )
    assert source == {"date": "2026-10-20", "panels": [p]}
    return bundle


def test_v2_frozen_prompt_binds_specs_and_aspect(frozen):
    from engine.image.reviewed_inputs import reviewed_panel_prompts

    s = frozen["candidate_script"]
    pp = reviewed_panel_prompts(s)
    assert pp[0].prompt_text == s["_reviewed_image_inputs"]["panels"][0]["prompt_text"]
    s["_scene_performance_v2"]["1"]["camera"]["shot_size"] = "MS"
    with pytest.raises(GenerationHold, match="performance changed"):
        reviewed_panel_prompts(s)


def test_v2_frozen_prompt_hash_drift_holds(frozen):
    from engine.image.reviewed_inputs import reviewed_panel_prompts

    s = frozen["candidate_script"]
    s["_reviewed_image_inputs"]["panels"][0]["prompt_text"] += " altered"
    with pytest.raises(GenerationHold, match="identity changed"):
        reviewed_panel_prompts(s)


def test_dynamic_image_stage_propagates_aspect_and_preserves_legacy_flag(frozen, monkeypatch):
    from engine.image import gemini_client
    from engine.persist import asset_writer
    from scripts.run_market import step_image

    monkeypatch.setenv("PERFORMANCE_SPEC_ENABLED", "true")
    generation = Mock(return_value=([Path("P1.png")], 0.04))
    monkeypatch.setattr(gemini_client, "generate_episode", generation)
    patch = Mock()
    monkeypatch.setattr(asset_writer, "patch_by_episode", patch)
    step_image("2026-10-20", "ICG-2026-10-20-001", {}, frozen["candidate_script"], Mock())
    assert generation.call_args.args[0][0]["aspect_ratio"] == "4:5"
    assert patch.call_args.args[2]["status"] == "image_generated"


def test_unknown_climax_does_not_invent_a_strike_and_shield_noun_is_not_defend():
    from engine.image.performance_compiler import compile_panel_performance

    p = panel()
    p["action"] = "A golden signal appears beside the shield"
    result = compile_panel_performance(p)
    assert result.action_phase != "IMPACT"
    assert result.interaction_required is False
    assert result.action_verb == p["action"]


def test_source_aspect_is_preserved_in_composed_slide(tmp_path):
    from engine.assembly.pil_composer import _compose_image_slide

    source = Image.new("RGB", (832, 1248), "white")
    draw = ImageDraw.Draw(source)
    draw.ellipse((300, 150, 500, 350), fill=(255, 0, 0))
    path = tmp_path / "source.png"
    source.save(path)
    out = tmp_path / "out.png"
    _compose_image_slide(out, path, "", "", "1", "", strict=True)
    im = Image.open(out).convert("RGB")
    # Circle remains circular; former nonuniform resize was 20% wider.
    points = [
        (x, y)
        for y in range(100, 500)
        for x in range(300, 800)
        if (lambda c: c[0] > 240 and c[1] < 30 and c[2] < 30)(im.getpixel((x, y)))
    ]
    xs, ys = zip(*points)
    assert abs((max(xs) - min(xs)) - (max(ys) - min(ys))) <= 2
    assert im.size == (1080, 1350)


def test_materialize_selection_validates_all_hashes_before_export(tmp_path):
    from engine.image.quality_candidates import materialize_selection

    p = tmp_path / "artifacts/123/episode-123/2026-10-20/panels/P1.png"
    p.parent.mkdir(parents=True)
    Image.new("RGB", (128, 160), "red").save(p)
    m = [
        {
            "panel_idx": 1,
            "output_hash": hashlib.sha256(p.read_bytes()).hexdigest(),
            "artifact_run_id": "123",
            "artifact_name": "episode-123",
            "artifact_path": "2026-10-20/panels/P1.png",
        }
    ]
    out = tmp_path / "export"
    assert materialize_selection(m, tmp_path / "artifacts", out)[0].read_bytes() == p.read_bytes()
    m[0]["output_hash"] = "a" * 64
    with pytest.raises(GenerationHold):
        materialize_selection(m, tmp_path / "artifacts", tmp_path / "bad-export")
    assert not (tmp_path / "bad-export").exists()


def test_unapproved_or_drifted_quality_candidate_cannot_reach_provider(frozen, monkeypatch):
    from engine.image import gemini_client
    from engine.image import quality_candidates as q

    client = Mock()
    client.schema.return_value.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [
        {"state": "DRAFT", "bundle": frozen}
    ]
    monkeypatch.setattr("engine.common.supabase_client.get_client", lambda: client)
    provider = Mock()
    monkeypatch.setattr(gemini_client, "generate_panel", provider)
    with pytest.raises(GenerationHold, match="Approved"):
        q.generate(frozen["id"], Path("out"))
    provider.assert_not_called()


def test_declared_canon_hands_cannot_be_swapped():
    p = panel()
    p["characters"][0]["char_id"] = "CHAR_HERO_002"
    s = spec(p)
    s["story_cast"][0] = "CHAR_HERO_002"
    s["visible_cast"] = ["CHAR_HERO_002"]
    s["must_show_cast"] = ["CHAR_HERO_002"]
    s["motion"]["subject_id"] = "CHAR_HERO_002"
    s["prop_hands"] = {"CHAR_HERO_002": {"LEFT": "rifle", "RIGHT": "shield"}}
    with pytest.raises(GenerationHold, match="HAND_OCCUPANCY"):
        validate_scene(p, s)
    s["prop_hands"]["CHAR_HERO_002"] = {"LEFT": "shield", "RIGHT": "rifle"}
    assert validate_scene(p, s).prop_hands["CHAR_HERO_002"]["LEFT"] == "shield"


def test_approved_quality_generation_produces_review_preview_and_reuses_success(
    frozen, monkeypatch, tmp_path
):
    import io

    from engine.image import gemini_client
    from engine.image import quality_candidates as q

    client = Mock()
    client.schema.return_value.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [
        {"state": "APPROVED", "bundle": frozen}
    ]
    monkeypatch.setattr("engine.common.supabase_client.get_client", lambda: client)
    monkeypatch.setenv("ICG_IMAGE_OUTCOME_V3_ENABLED", "true")
    monkeypatch.setenv("GITHUB_RUN_ID", "456")
    state = {}

    def receipt(name, params):
        if name == "image_quality_inspect":
            return {"output_hash": state["hash"]} if state.get("hash") else {}
        assert name == "image_quality_reserve"
        assert not state.get("reserved")
        state["reserved"] = True
        return {"token": "reservation"}

    monkeypatch.setattr(q, "rpc", receipt)
    monkeypatch.setattr(q.QualityGuard, "store_attempt_diagnostic", lambda *a, **kw: None)

    def finish(self, token, **kw):
        assert kw["state"] == "success"
        state["hash"] = kw["output_hash"]

    monkeypatch.setattr(q.QualityGuard, "finish_outcome", finish)
    buffer = io.BytesIO()
    Image.new("RGB", (128, 160), "red").save(buffer, format="PNG")
    provider = Mock(return_value=(buffer.getvalue(), 100, 1290))
    monkeypatch.setattr(gemini_client, "_get_client", lambda: object())
    monkeypatch.setattr(gemini_client, "_generate_one", provider)
    root = tmp_path / "quality"
    result = q.generate(frozen["id"], root)
    assert result["quality_status"] == "UNKNOWN"
    assert (root / frozen["id"] / "previews/P1-slide.png").is_file()
    assert provider.call_count == 1
    q.generate(frozen["id"], root)
    assert provider.call_count == 1
    assert provider.call_args.kwargs["aspect_ratio"] == "4:5"


def test_quality_failure_cannot_make_second_provider_call(frozen, monkeypatch, tmp_path):
    from engine.image import gemini_client
    from engine.image import quality_candidates as q

    client = Mock()
    client.schema.return_value.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [
        {"state": "APPROVED", "bundle": frozen}
    ]
    monkeypatch.setattr("engine.common.supabase_client.get_client", lambda: client)
    monkeypatch.setenv("ICG_IMAGE_OUTCOME_V3_ENABLED", "true")
    state = {}

    def receipt(name, params):
        if name == "image_quality_inspect":
            return {}
        if state.get("reserved"):
            raise GenerationHold("quality attempt requires review")
        state["reserved"] = True
        return {"token": "reservation"}

    monkeypatch.setattr(q, "rpc", receipt)
    monkeypatch.setattr(q.QualityGuard, "store_attempt_diagnostic", lambda *a, **kw: None)
    monkeypatch.setattr(q.QualityGuard, "finish_outcome", lambda *a, **kw: None)
    provider = Mock(return_value=(b"invalid PNG", 100, 5))
    monkeypatch.setattr(gemini_client, "_get_client", lambda: object())
    monkeypatch.setattr(gemini_client, "_generate_one", provider)
    with pytest.raises(GenerationHold, match="requires review"):
        q.generate(frozen["id"], tmp_path / "quality")
    assert provider.call_count == 1


def test_selection_binding_rejects_rollback_before_publish(monkeypatch, tmp_path):
    from engine.image import quality_candidates as q
    from engine.publish.manifest import build_manifest, validate_manifest

    slide = tmp_path / "slide.png"
    Image.new("RGB", (128, 160), "red").save(slide)
    marker = {"scope": "output/episodes/2026-10-20/panels", "version": 1, "manifest": []}
    s = {"date": "2026-10-20", "_image_quality_selection": marker}
    s["_assembly_manifest"] = build_manifest(s, [slide])
    monkeypatch.setattr(q, "load_selection", lambda *a: marker)
    validate_manifest(s, [slide])
    monkeypatch.setattr(q, "load_selection", lambda *a: dict(marker, version=2))
    with pytest.raises(GenerationHold, match="changed"):
        validate_manifest(s, [slide])


def test_pending_gate_skips_scheduled_resume_but_not_ordinary_episodes(monkeypatch):
    from engine.image import quality_candidates as q
    from scripts import run_resume

    client = Mock()
    client.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
        {"status": "image_generated", "artifact_run_id": "123"}
    ]
    monkeypatch.setattr("engine.common.supabase_client.icg_table", lambda name: client)
    monkeypatch.setattr(q, "pending_human_gate", lambda date: True)
    r = run_resume.prepare_resume_target("ICG-2026-10-20-001", scheduled=True)
    assert r["ready"] is False and r["reason"] == "quality_human_gate_pending"
    with pytest.raises(RuntimeError, match="human gate"):
        run_resume.prepare_resume_target("ICG-2026-10-20-001")
    monkeypatch.setattr(q, "pending_human_gate", lambda date: False)
    assert run_resume.prepare_resume_target("ICG-2026-10-20-001")["run_id"] == "123"


def test_download_selection_uses_validated_argv_and_never_shell(monkeypatch, tmp_path):
    from scripts import download_quality_selection as d

    marker = {"manifest": [{"artifact_run_id": "123", "artifact_name": "episode-123"}]}
    monkeypatch.setattr(d, "load_selection", lambda *a: marker)
    monkeypatch.setenv("GITHUB_REPOSITORY", "yumens2-byte/investment-comic-gemini")
    call = Mock()
    monkeypatch.setattr(d.subprocess, "run", call)
    d.download("2026-10-20", 1, tmp_path / "download")
    assert call.call_args.args[0][:4] == ["gh", "run", "download", "123"]
    assert "shell" not in call.call_args.kwargs
    marker["manifest"][0]["artifact_name"] = "episode-123/../../secret"
    with pytest.raises(GenerationHold):
        d.download("2026-10-20", 1, tmp_path / "unsafe")


def test_workflow_is_manual_and_does_not_upload_prompts_or_private_receipts():
    import yaml

    workflow = yaml.load(
        Path(".github/workflows/image_quality.yml").read_text(), Loader=yaml.BaseLoader
    )
    assert set(workflow["on"]) == {"workflow_dispatch"}
    steps = workflow["jobs"]["gate"]["steps"]
    artifact = next(
        s["with"] for s in steps if s.get("uses", "").startswith("actions/upload-artifact")
    )
    assert "generation.log" not in artifact["path"]
    assert "receipt.json" not in artifact["path"]
    assert "*.png" in artifact["path"]


def test_panel_action_safety_is_checked_even_when_hash_is_reviewed():
    p = panel()
    p["action"] = "The heroine fires the rifle"
    s = spec(p)
    with pytest.raises(GenerationHold, match="TEXT_REVIEW_REQUIRED"):
        validate_scene(p, s)


def test_declared_motion_cannot_hide_a_stationary_action():
    p = panel()
    p["action"] = "The heroine stands still beside the dial"
    with pytest.raises(GenerationHold, match="CONTRADICTS_STATIONARY"):
        validate_scene(p, spec(p))


def test_pending_quality_gate_prevents_publishing_old_assembled_slides(monkeypatch):
    from engine.image import quality_candidates as q

    monkeypatch.setattr(q, "pending_human_gate", lambda d: True)
    with pytest.raises(GenerationHold, match="selected assembly"):
        q.require_publication_gate({"date": "2026-10-20"})
    client = Mock()
    client.schema.return_value.table.return_value.select.return_value.eq.return_value.in_.return_value.limit.return_value.execute.return_value.data = [
        {"id": "new-draft"}
    ]
    monkeypatch.setattr("engine.common.supabase_client.get_client", lambda: client)
    with pytest.raises(GenerationHold, match="still requires"):
        q.require_publication_gate(
            {
                "date": "2026-10-20",
                "_image_quality_selection": {"scope": "output/episodes/2026-10-20/panels"},
            }
        )
