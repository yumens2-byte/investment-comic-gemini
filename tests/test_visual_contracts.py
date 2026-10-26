"""New policy contracts: real input identities and pixels, mocked DB/provider IO."""
import runpy
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock

import pytest
from PIL import Image

from engine.image.generation_guard import GenerationHold
from engine.image.scene_performance import normalize_drafts, payload_hash
from engine.quality import visual

_helpers = runpy.run_path(str(Path(__file__).with_name("test_dynamic_image_quality.py")))
frozen, panel, spec = (_helpers[name] for name in ("frozen", "panel", "spec"))


def test_normalization_computes_hashes_without_inventing_actions():
    p = panel()
    s = spec(p)
    draft = {k: v for k, v in s.items() if k not in
             {'version', 'panel_idx', 'action_sha256', 'setting_sha256', 'review_evidence'}}
    script = {'panels': [p], 'scene_performance': {'1': draft}}
    before = deepcopy(script)
    normalized = normalize_drafts(script)
    assert script == before
    assert normalized['panels'][0]['action'] == p['action']
    assert 'scene_performance' not in normalized
    assert normalized['_scene_performance_v2']['1']['action_sha256'] == s['action_sha256']
    assert 'UNKNOWN' in normalized['_scene_performance_v2']['1']['review_evidence']
    draft['action_sha256'] = 'a'*64
    with pytest.raises(GenerationHold, match='DRAFT_INVALID'):
        normalize_drafts(script)


@pytest.mark.parametrize('mode', ['off', 'shadow'])
def test_shadow_and_off_do_not_create_an_enforce_policy(monkeypatch, mode):
    monkeypatch.setenv('ICG_VISUAL_QUALITY_MODE', mode)
    assert visual.policy_for_new_episode() is None


def test_new_initial_inputs_require_db_receipt_and_exact_revision_one(frozen, monkeypatch):
    from engine.image.reviewed_inputs import reviewed_panel_prompts
    source = deepcopy(frozen['candidate_script'])
    source.pop('_reviewed_image_inputs')
    source['_generation_revision'] = 1
    source['_state_candidate'] = {'version': 'state-candidate-1'}
    monkeypatch.setenv('ICG_GENERATION_REVISION', '1')
    monkeypatch.setenv('ICG_VISUAL_QUALITY_MODE', 'enforce')
    saved = {}

    def rpc(name, params):
        if name == 'visual_quality_capability':
            return {'version': visual.CAPABILITY}
        if name == 'visual_quality_freeze_inputs':
            saved.update(params)
            return {'registered': True, 'script': dict(params['p_script'],
                _visual_policy=params['p_policy'], _visual_policy_sha256='d'*64)}
        assert name == 'visual_quality_require_inputs'
        return {'authorized': True}

    monkeypatch.setattr(visual, 'rpc', rpc)
    result = visual.freeze_initial_inputs(source, actor='operator', note='Freeze exact new inputs before generation')
    assert saved['p_expected_script'] == source
    assert result['_generation_revision'] == 1
    assert result['_reviewed_image_inputs']['origin'] == 'INITIAL_GENERATION'
    assert len(reviewed_panel_prompts(result)) == 1
    monkeypatch.setattr(visual, 'rpc', Mock(side_effect=GenerationHold('DB registration missing')))
    with pytest.raises(GenerationHold, match='registration missing'):
        reviewed_panel_prompts(result)


def test_old_v2_revision_one_still_rejected_without_initial_origin(frozen, monkeypatch):
    from engine.image.reviewed_inputs import reviewed_panel_prompts
    script = deepcopy(frozen['candidate_script'])
    script['_generation_revision'] = 1
    monkeypatch.setenv('ICG_GENERATION_REVISION', '1')
    with pytest.raises(GenerationHold, match='configuration changed'):
        reviewed_panel_prompts(script)


def test_db_policy_detects_deleted_mirror_even_if_global_mode_is_off(monkeypatch):
    monkeypatch.setenv('ICG_VISUAL_QUALITY_MODE', 'off')
    with pytest.raises(GenerationHold, match='MIRROR_CHANGED'):
        visual.policy_present({}, {'visual_policy_json': {'mode': 'enforce'}, 'visual_policy_sha256': 'a'*64})


def test_pending_registration_stops_before_compiler_and_provider_even_when_off(monkeypatch, tmp_path):
    from engine.image import gemini_client, performance_compiler
    from scripts import run_market
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('ICG_VISUAL_QUALITY_MODE', 'off')
    monkeypatch.setenv('PERFORMANCE_SPEC_ENABLED', 'true')
    monkeypatch.setattr(visual, 'require_inputs', Mock(side_effect=GenerationHold('registration pending')))
    compiler, provider = Mock(), Mock()
    monkeypatch.setattr(performance_compiler, 'compile_episode_performance', compiler)
    monkeypatch.setattr(gemini_client, 'generate_episode', provider)
    with pytest.raises(GenerationHold, match='registration pending'):
        run_market.step_image('2026-10-26', 'ICG-2026-10-26-001', {},
            {'_visual_policy_intent': {'mode': 'enforce'}, 'panels': []}, Mock())
    compiler.assert_not_called()
    provider.assert_not_called()


@pytest.mark.parametrize('changed', ['policy', 'scene', 'input', 'layout', 'effective', 'slide'])
def test_manifest_two_invalidates_every_material_render_change(tmp_path, changed):
    from engine.publish.manifest import build_manifest, validate_manifest
    path = tmp_path/'slide.png'
    Image.new('RGB', (1080, 1350), 'blue').save(path)
    script = {'date': '2026-10-26', '_visual_policy': {'mode': 'enforce'}, '_visual_policy_sha256': 'a'*64,
              '_scene_performance_v2': {'1': {'motion': 'turn'}}, '_reviewed_image_inputs': {'frozen': 1},
              '_effective_render_manifest': [{'panel_idx': 1, 'output_hash': 'b'*64}],
              '_mobile_layout_report': {'font_sha256': 'c'*64}}
    script['_assembly_manifest'] = build_manifest(script, [path])
    assert script['_assembly_manifest']['version'] == 'assembly-manifest-2'
    validate_manifest(script, [path])
    if changed == 'slide':
        Image.new('RGB', (1080, 1350), 'red').save(path)
    else:
        key = {'policy': '_visual_policy', 'scene': '_scene_performance_v2', 'input': '_reviewed_image_inputs',
               'layout': '_mobile_layout_report', 'effective': '_effective_render_manifest'}[changed]
        script[key] = {'changed': True}
    with pytest.raises(ValueError, match='manifest mismatch'):
        validate_manifest(script, [path])


def test_selected_panel_uses_candidate_plan_while_retained_panel_keeps_source(frozen, monkeypatch, tmp_path):
    from engine.common import supabase_client
    original = deepcopy(frozen['candidate_script'])
    original['panels'].append(dict(original['panels'][0], idx=2))
    original['_scene_performance_v2']['2'] = spec(original['panels'][1])
    item2 = dict(original['_reviewed_image_inputs']['panels'][0], idx=2, fingerprint='2'*64)
    original['_reviewed_image_inputs']['panels'].append(item2)
    candidate = deepcopy(original)
    candidate['_scene_performance_v2']['1']['camera']['shot_size'] = 'MS'
    candidate['_reviewed_image_inputs']['panels'][0]['fingerprint'] = '3'*64
    cid = '11111111-1111-4111-8111-111111111111'
    paths = [tmp_path/'P1.png', tmp_path/'P2.png']
    for p in paths:
        Image.new('RGB', (128, 160), 'blue').save(p)
    import hashlib
    digest = hashlib.sha256(paths[0].read_bytes()).hexdigest()
    original['_image_quality_selection'] = {'manifest': [{'panel_idx': 1, 'artifact_name': 'image-quality-'+cid, 'output_hash': digest}]}
    calls = [{'panel': 1, 'output_hash': digest, 'fingerprint': '3'*64, 'token': 'token1', 'revision': 4, 'quality_candidate_id': cid},
             {'panel': 2, 'output_hash': digest, 'fingerprint': '2'*64, 'token': 'token2', 'revision': 3}]
    def table(name):
        q = Mock()
        q.select.return_value = q.eq.return_value = q
        q.execute.return_value.data = calls if name == 'image_generation_calls' else [{'bundle': {'candidate_script': candidate}}]
        return q
    monkeypatch.setattr(supabase_client, 'icg_table', table)
    result = visual.source_manifest(original, paths)
    assert result[0]['scene']['camera']['shot_size'] == 'MS'
    assert result[1]['scene']['camera']['shot_size'] == 'CU'
    assert result[0]['candidate_id'] == cid and result[1]['candidate_id'] is None


@pytest.mark.parametrize('size,padding', [((864, 1080), 0), ((832, 1248), 1/6)])
def test_mobile_geometry_preserves_source_and_measures_real_padding(tmp_path, size, padding):
    from engine.assembly.mobile_layout import compose_mobile
    source, output = tmp_path/'source.png', tmp_path/'slide.png'
    Image.new('RGB', size, 'blue').save(source)
    before = source.read_bytes()
    report = compose_mobile({'idx': 1, 'key_text': 'Balance', 'narration': 'A visible change', 'market_ref': 'VIX 18.44'}, source, output)
    assert report['horizontal_padding_ratio'] == pytest.approx(padding)
    assert report['actual_image_status'] == report['mobile_assembly_status'] == 'UNKNOWN'
    assert source.read_bytes() == before
    assert Image.open(output).size == (1080, 1350)
    assert Image.open(tmp_path/'slide-360px.png').size == (360, 450)
    assert Image.open(tmp_path/'slide-430px.png').width == 430
    assert all(1050 <= b['bbox'][1] < b['bbox'][3] <= 1350 for b in report['text_boxes'])


def test_mobile_overflow_never_truncates_or_regenerates(tmp_path):
    from engine.assembly.mobile_layout import compose_mobile
    source, output = tmp_path/'source.png', tmp_path/'slide.png'
    Image.new('RGB', (864, 1080), 'blue').save(source)
    before = source.read_bytes()
    with pytest.raises(GenerationHold, match='TEXT_EDIT_REQUIRED'):
        compose_mobile({'idx': 1, 'key_text': 'X'*3000}, source, output)
    assert source.read_bytes() == before and not output.exists()


def test_visual_assembly_keeps_source_bytes_and_returns_a_new_bound_subject(frozen, monkeypatch, tmp_path):
    from engine.assembly.mobile_layout import PROFILE
    from engine.publish.manifest import build_manifest
    source = tmp_path/'source.png'
    Image.new('RGB', (864, 1080), 'blue').save(source)
    script = deepcopy(frozen['candidate_script'])
    script['_visual_policy'] = {'layout_sha256': payload_hash(PROFILE)}
    script['_visual_policy_sha256'] = 'd'*64
    before = deepcopy(script)
    monkeypatch.setattr(visual, 'require_inputs', lambda script: None)
    monkeypatch.setattr(visual, 'source_manifest', lambda script, images: [{'panel_idx': 1, 'output_hash': 'e'*64}])
    slides, prepared = visual.prepare_assembly(script, [source], tmp_path/'slides')
    assert script == before
    assert len(slides) == 1 and slides[0].exists()
    assert prepared['_mobile_layout_report']['panels'][0]['actual_image_status'] == 'UNKNOWN'
    assert build_manifest(prepared, slides)['version'] == 'assembly-manifest-2'


def test_v2_recovery_preserves_exact_success_and_cannot_downgrade_its_spec(frozen, monkeypatch):
    from scripts.prepare_image_recovery import prepare, validate_candidate
    monkeypatch.setenv('ICG_GENERATION_REVISION', '4')
    source = deepcopy(frozen['candidate_script'])
    source['_state_candidate'] = {'version': 'state-candidate-1'}
    p2 = dict(source['panels'][0], idx=2)
    source['panels'].append(p2)
    source['_scene_performance_v2']['2'] = spec(p2)
    original_item = source['_reviewed_image_inputs']['panels'][0]
    preserved = {'1': dict(original_item, output_hash='e'*64, reuse_only=True)}
    scenes = {'2': {'action': p2['action'], 'setting': p2['setting'], 'performance': spec(p2)}}
    candidate = prepare(source, scenes, 4, actor='operator', note='Reviewed only the failed scene without replacing successful images', preserved_inputs=preserved)
    validate_candidate(candidate)
    assert candidate['_reviewed_image_inputs']['panels'][0] == preserved['1']
    assert candidate['panels'][0] == source['panels'][0]
    assert candidate['_scene_performance_v2']['1'] == source['_scene_performance_v2']['1']
    proof = candidate['_preserved_performance_inputs']['1']
    assert proof['panel_sha256'] == payload_hash(source['panels'][0])
    candidate['_scene_performance_v2']['1']['review_evidence'] = 'Changed the protected scene evidence without approval'
    with pytest.raises(GenerationHold):
        validate_candidate(candidate)


def test_review_template_is_unknown_and_binds_actual_hashes():
    from scripts.visual_quality import review_template
    script = {'_assembly_manifest': {'version': 'assembly-manifest-2', 'slides': ['s1']},
              '_effective_render_manifest': [{'panel_idx': 1, 'output_hash': 'p1'}]}
    template = review_template(script)
    assert template['episode_continuity'] == 'UNKNOWN'
    assert template['panels'][0]['output_hash'] == 'p1'
    assert template['panels'][0]['slide_hash'] == 's1'
    assert all(c['status'] == 'UNKNOWN' for c in template['panels'][0]['checks'].values())


def test_named_render_roles_are_projected_without_changing_the_original_source():
    from engine.image.render_sources import project_sources
    canon = 'Body: red gold armor\nSignature Action: punches the enemy\nIdentifier — MANDATORY: ETF letters'
    style = 'Bold cel shading\nCAMERA: all characters full body\nBodies angled toward center contact point.'
    appearance, technique, report = project_sources(canon, style)
    assert appearance == 'Body: red gold armor'
    assert technique == 'Bold cel shading'
    assert len(report['exclusions']) == 4
    assert 'punches' in canon and 'contact point' in style


def test_x_stops_after_first_receipt_if_snapshot_is_lost(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from engine.publish import x_publisher as xp
    paths = [tmp_path/f'S{i}.png' for i in range(8)]
    for path in paths:
        Image.new('RGB', (128, 160), 'blue').save(path)
    api, client = Mock(), Mock()
    api.media_upload.return_value = SimpleNamespace(media_id=123)
    client.create_tweet.return_value = SimpleNamespace(data={'id': 'first-post'})
    monkeypatch.setattr(xp, '_make_clients', lambda: (api, client))
    monkeypatch.setattr(xp.time, 'sleep', lambda seconds: None)
    before = Mock(side_effect=[None, None, GenerationHold('snapshot lost')])
    receipt = Mock()
    script = {'_visual_policy': {'mode': 'enforce'}, 'caption_x_final': xp.DISCLAIMER_REQUIRED}
    with pytest.raises(GenerationHold, match='snapshot lost'):
        xp.publish_episode_x(script, paths, dry_run=False, before_send=before, receipt_callback=receipt)
    assert client.create_tweet.call_count == 1
    receipt.assert_called_once_with(['first-post'])


def test_telegram_stops_second_batch_and_keeps_first_receipt(tmp_path, monkeypatch):
    from engine.publish import telegram_publisher as tg
    paths = [tmp_path/f'S{i}.png' for i in range(11)]
    for path in paths:
        Image.new('RGB', (128, 160), 'blue').save(path)
    monkeypatch.setattr(tg, '_get_bot_token', lambda: 'fake')
    monkeypatch.setattr(tg.time, 'sleep', lambda seconds: None)
    send = Mock(return_value={'ok': True, 'result': [{'message_id': i+1} for i in range(10)]})
    monkeypatch.setattr(tg, '_send_media_group', send)
    receipts = {}
    result = tg.publish_episode_telegram({'_visual_policy': {'mode': 'enforce'}}, paths, ['test'],
        dry_run=False, receipts=receipts, before_send=Mock(side_effect=[None, GenerationHold('snapshot lost')]))
    assert result == {'test': False}
    assert send.call_count == 1 and receipts['test'] == list(range(1, 11))
