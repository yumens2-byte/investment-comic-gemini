"""Actual form resolution and byte checks; no provider or database adapters."""

import hashlib
import runpy
from pathlib import Path

import pytest

from engine.common.exceptions import CanonLockViolation, UnknownCharacterError
from engine.image import ref_loader


@pytest.fixture
def canon(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    forms = {}
    for name in ('form0', 'form1'):
        path = Path(f'assets/characters/hero_{name}.png')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(name.encode())
        forms[name] = {'ref': path.as_posix(),
                       'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    value = {'heroes': {'hero': {'default_form': 'form0', 'forms': forms}}}
    monkeypatch.setattr(ref_loader, '_load_canon', lambda: value)
    return value


def test_explicit_form_is_not_default_or_fallback(canon):
    bindings = ref_loader.get_ref_bindings_for_panel([{'char_id': 'hero', 'form': 'form1'}])
    assert bindings == [{'char_id': 'hero', 'form': 'form1',
                         **{'ref': canon['heroes']['hero']['forms']['form1']['ref'],
                            'sha256': canon['heroes']['hero']['forms']['form1']['sha256']}}]
    assert ref_loader.get_ref_bindings_for_panel([{'char_id': 'hero'}])[0]['form'] == 'form0'


@pytest.mark.parametrize('form', ['unknown', '', False, 1])
def test_unregistered_or_invalid_form_has_no_fallback(canon, form):
    with pytest.raises(UnknownCharacterError):
        ref_loader.get_ref_bindings_for_panel([{'char_id': 'hero', 'form': form}])


@pytest.mark.parametrize('case', ['missing', 'changed', 'pending', 'traversal', 'symlink'])
def test_invalid_reference_never_silently_disappears(canon, case, tmp_path):
    entry = canon['heroes']['hero']['forms']['form1']
    path = Path(entry['ref'])
    if case == 'missing':
        path.unlink()
    elif case == 'changed':
        path.write_bytes(b'not approved')
    elif case == 'pending':
        entry['sha256'] = '__PENDING__'
    elif case == 'traversal':
        entry['ref'] = 'assets/characters/../outside.png'
    else:
        outside = tmp_path / 'outside.png'
        outside.write_bytes(path.read_bytes())
        path.unlink()
        path.symlink_to(outside)
    with pytest.raises((UnknownCharacterError, CanonLockViolation, FileNotFoundError)):
        ref_loader.get_ref_bindings_for_panel([{'char_id': 'hero', 'form': 'form1'}])


def test_duplicate_cast_is_rejected(canon):
    with pytest.raises(UnknownCharacterError):
        ref_loader.get_ref_bindings_for_panel([{'char_id': 'hero'}, {'char_id': 'hero'}])


def test_dynamic_builder_uses_explicit_form_before_freezing(canon, monkeypatch):
    from engine.image import prompt_builder
    helpers = runpy.run_path(str(Path(__file__).with_name('test_dynamic_image_quality.py')))
    panel = helpers['panel']()
    panel['characters'] = [{'char_id': 'hero', 'form': 'form1'}]
    scene = helpers['spec'](panel)
    scene.update(story_cast=['hero'], offscreen_cast=[])
    script = {'panels': [panel], '_scene_performance_v2': {'1': scene}}
    monkeypatch.setattr(prompt_builder, '_get_char_designs', lambda ids: 'blue armor')
    monkeypatch.setattr(prompt_builder, '_get_style_block', lambda: 'bold ink')
    prompt = prompt_builder.build_for_episode(script)[0]
    assert prompt.ref_image_paths == [Path(canon['heroes']['hero']['forms']['form1']['ref'])]

    from engine.image.generation_guard import GenerationHold
    monkeypatch.setattr(prompt_builder, '_get_style_block', lambda: 'Both figures remain stationary.')
    with pytest.raises(GenerationHold, match='MOTION_CONFLICT'):
        prompt_builder.build_for_episode(script)
