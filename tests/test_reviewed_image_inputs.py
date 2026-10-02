import hashlib
from copy import deepcopy
from pathlib import Path

import pytest

from engine.image import reviewed_inputs as module
from engine.image.generation_guard import GenerationHold, ProductionGenerationGuard
from engine.publish.manifest import script_hash


@pytest.fixture
def prepared(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('ICG_GENERATION_REVISION', '4')
    ref = Path('assets/characters/hero.png')
    ref.parent.mkdir(parents=True)
    ref.write_bytes(b'approved canon reference')
    monkeypatch.setattr(module, 'get_refs_for_panel', lambda ids: [ref] if ids else [])
    script = {'date': '2026-10-02', '_generation_revision': 4, 'panels': [
        {'idx': 1, 'panel_type': 'COVER', 'characters': [{'char_id': 'hero'}]},
        {'idx': 2, 'panel_type': 'TEXT_CARD'}, {'idx': 3, 'panel_type': 'DISCLAIMER'}]}
    prompt = 'Approved exact scene and style'
    g = ProductionGenerationGuard(scope='output/episodes/2026-10-02/panels', panel=1,
                                   prompt=prompt + '\n[model=gemini-2.5-flash-image;aspect=None]',
                                   refs=[ref])
    script['_reviewed_image_inputs'] = {
        'version': 'reviewed-image-inputs-1', 'script_hash': script_hash(script),
        'model': 'gemini-2.5-flash-image', 'aspect_ratio': None,
        'panels': [{'idx': 1, 'prompt_text': prompt, 'refs': [str(ref)],
                    'ref_sha256': [hashlib.sha256(ref.read_bytes()).hexdigest()],
                    'fingerprint': g.fingerprint}]}
    return script


def test_exact_inputs_and_compositor_slots_preserved(prepared):
    before = deepcopy(prepared)
    result = module.reviewed_panel_prompts(prepared)
    assert [p.panel_idx for p in result] == [1, 2, 3]
    assert result[0].prompt_text == 'Approved exact scene and style'
    assert result[1].prompt_text == result[2].prompt_text == ''
    assert prepared == before


def test_regular_narrative_keeps_live_compiler():
    assert module.reviewed_panel_prompts({'panels': []}) is None


@pytest.mark.parametrize('key,value', [('version', 'unknown'), ('script_hash', 'a' * 64),
                                      ('model', 'different'), ('aspect_ratio', '4:5'),
                                      ('panels', None)])
def test_changed_bundle_configuration_holds(prepared, key, value):
    prepared['_reviewed_image_inputs'][key] = value
    with pytest.raises(GenerationHold):
        module.reviewed_panel_prompts(prepared)


@pytest.mark.parametrize('key,value', [('prompt_text', 'changed prompt'), ('fingerprint', '0' * 64),
                                      ('ref_sha256', ['a' * 64]), ('refs', ['/etc/passwd']),
                                      ('refs', ['assets/characters/../other.png']),
                                      ('refs', ['assets/characters/other.png']),
                                      ('prompt_text', ''), ('ref_sha256', [])])
def test_changed_provider_inputs_hold(prepared, key, value):
    prepared['_reviewed_image_inputs']['panels'][0][key] = value
    with pytest.raises(GenerationHold):
        module.reviewed_panel_prompts(prepared)


def test_changed_reference_bytes_hold(prepared):
    Path('assets/characters/hero.png').write_bytes(b'changed')
    with pytest.raises(GenerationHold, match='bytes changed'):
        module.reviewed_panel_prompts(prepared)


def test_changed_revision_holds(prepared, monkeypatch):
    monkeypatch.setenv('ICG_GENERATION_REVISION', '3')
    with pytest.raises(GenerationHold):
        module.reviewed_panel_prompts(prepared)


def test_missing_scene_hold(prepared):
    prepared['_reviewed_image_inputs']['panels'] = []
    with pytest.raises(GenerationHold):
        module.reviewed_panel_prompts(prepared)


def test_duplicate_scene_hold(prepared):
    bundle = prepared['_reviewed_image_inputs']
    bundle['panels'].append(deepcopy(bundle['panels'][0]))
    with pytest.raises(GenerationHold):
        module.reviewed_panel_prompts(prepared)


def test_compositor_cannot_gain_provider_input(prepared):
    bundle = prepared['_reviewed_image_inputs']
    bundle['panels'].append(dict(bundle['panels'][0], idx=2))
    with pytest.raises(GenerationHold):
        module.reviewed_panel_prompts(prepared)


def test_narrative_edit_invalidates_review(prepared):
    prepared['panels'][0]['action'] = 'different scene'
    with pytest.raises(GenerationHold):
        module.reviewed_panel_prompts(prepared)


def test_performance_configuration_cannot_replace_review(prepared):
    with pytest.raises(GenerationHold):
        module.reviewed_panel_prompts(prepared, performance_specs=[])


def test_image_stage_uses_exact_review_and_never_live_compiler(prepared, monkeypatch):
    from unittest.mock import Mock

    from engine.image import gemini_client, prompt_builder
    from engine.persist import asset_writer
    from scripts import run_market

    monkeypatch.delenv('PERFORMANCE_SPEC_ENABLED', raising=False)
    live = Mock(side_effect=AssertionError('live Notion must not change reviewed inputs'))
    monkeypatch.setattr(prompt_builder, 'build_for_episode', live)
    generation = Mock(return_value=([Path('P1.png')], .04))
    monkeypatch.setattr(gemini_client, 'generate_episode', generation)
    monkeypatch.setattr(asset_writer, 'patch_by_episode', Mock())
    paths = run_market.step_image('2026-10-02', 'ICG-2026-10-02-001', {}, prepared, Mock())
    live.assert_not_called()
    assert paths == [Path('P1.png'), None, None]
    assert generation.call_args.args[0][0]['prompt_text'] == 'Approved exact scene and style'


def test_image_stage_rejects_drift_before_provider(prepared, monkeypatch):
    from unittest.mock import Mock

    from engine.image import gemini_client
    from scripts import run_market

    monkeypatch.delenv('PERFORMANCE_SPEC_ENABLED', raising=False)
    generation = Mock(side_effect=AssertionError('must stop before provider'))
    monkeypatch.setattr(gemini_client, 'generate_episode', generation)
    prepared['_reviewed_image_inputs']['panels'][0]['prompt_text'] = 'changed'
    with pytest.raises(GenerationHold):
        run_market.step_image('2026-10-02', 'ICG-2026-10-02-001', {}, prepared, Mock())
    generation.assert_not_called()
