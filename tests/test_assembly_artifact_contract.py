from pathlib import Path

import pytest
import yaml
from PIL import Image

from engine.assembly.pil_composer import compose_episode, compose_slide
from engine.publish.telegram_publisher import _validate_slides as validate_tg
from engine.publish.x_publisher import _validate_slides as validate_x
from scripts.run_resume import restore_panel_source


def panel():
    return {'idx': 1, 'panel_type': 'NORMAL', 'key_text': 'Hello', 'narration': 'Test'}


def test_legacy_artifact_restored_and_image_assembled(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    source = Path('output/episodes/episodes/2026-10-02/panels/P1.png')
    source.parent.mkdir(parents=True)
    Image.new('RGB', (1080, 1350), 'red').save(source)
    target = restore_panel_source('output/episodes/2026-10-02/panels/P1.png', '2026-10-02')
    assert target.read_bytes() == source.read_bytes()
    slides = compose_episode([panel()], [target], tmp_path / 'slides', strict=True)
    with Image.open(slides[0]) as image:
        assert image.getpixel((0, 0)) == (255, 0, 0)
    validate_tg(slides)
    validate_x(slides)


@pytest.mark.parametrize('kind', ['missing', 'corrupt', 'empty', 'duplicate'])
def test_strict_assembly_fails_before_output(tmp_path, kind):
    source = tmp_path / 'P1.png'
    panels = [panel()]
    if kind == 'corrupt':
        source.write_text('not png')
    elif kind == 'empty':
        panels = []
    elif kind == 'duplicate':
        panels = [panel(), panel()]
    with pytest.raises(ValueError):
        compose_episode(panels, [source], tmp_path / 'slides', strict=True)
    assert not (tmp_path / 'slides').exists()


@pytest.mark.parametrize('path', ['../P1.png', 'output/episodes/2026-10-01/panels/P1.png',
                                  '/tmp/P1.png', 'output/episodes/2026-10-02/panels/../P1.png'])
def test_restore_rejects_wrong_scope(path):
    with pytest.raises(ValueError):
        restore_panel_source(path, '2026-10-02')


def test_text_preview_cannot_be_published(tmp_path):
    result = compose_slide(None, 'Hello', 'Text', 1, 'NORMAL', output_path=tmp_path / 'S1.png')
    for validate in [validate_tg, validate_x]:
        with pytest.raises(ValueError, match='fallback'):
            validate([result])


def test_disclaimer_without_art_is_allowed(tmp_path):
    panels = [dict(panel(), panel_type='DISCLAIMER')]
    slides = compose_episode(panels, [], tmp_path / 'slides', strict=True)
    validate_tg(slides)


def test_episode_artifact_root_independent_of_preflight():
    workflow = yaml.safe_load(Path('.github/workflows/run_market.yml').read_text())
    steps = workflow['jobs']['run-market']['steps'] if 'run-market' in workflow['jobs'] else next(iter(workflow['jobs'].values()))['steps']
    episode = next(s for s in steps if s.get('name') == 'Upload Episode Artifact')
    assert episode['with']['path'] == 'output/episodes/'
    report = next(s for s in steps if s.get('name') == 'Upload Market Inspection')
    assert report['with']['path'] == 'output/run-market-preflight.json'
