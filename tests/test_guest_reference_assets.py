"""Approved guest reference bytes are mandatory in comic and Shorts generation."""
from pathlib import Path
from unittest.mock import patch

import pytest

from engine.common.exceptions import CanonLockViolation
from engine.image import ref_loader
from engine.image.prompt_builder import build_for_episode


@pytest.mark.parametrize("cid", sorted(ref_loader.GUEST_CHARACTER_IDS))
def test_guest_reference_has_verified_real_image(cid):
    from PIL import Image
    ref_loader.verify_canon(cid)
    refs = ref_loader.get_refs_for_panel([cid])
    assert len(refs) == 1
    assert refs[0].suffix == ".jpg"
    with Image.open(refs[0]) as image:
        assert image.format == "JPEG"
        image.verify()


def test_mixed_cast_includes_hero_and_guest_reference():
    episode = {"panels": [{"idx": 1, "panel_type": "TENSION", "characters": [
        {"char_id": "CHAR_HERO_003", "role": "hero"},
        {"char_id": "SENTINEL_YIELD", "role": "npc"}]}]}
    with patch('engine.common.notion_loader.load_char_design_blocks', return_value={}), \
            patch('engine.common.notion_loader.load_image_prompt_blocks', return_value={}):
        prompts = build_for_episode(episode)
    assert [p.name for p in prompts[0].ref_image_paths] == [
        "hero_leverage_muscle_man.png", "guest_sentinel_yield.jpg"]


def test_changed_guest_reference_is_fatal(monkeypatch, tmp_path):
    monkeypatch.setattr(ref_loader, '_get_char_entry', lambda _: ('guests', {
        'ref': str(tmp_path / 'ref.jpg'), 'sha256': '0' * 64}))
    Path(tmp_path / 'ref.jpg').write_bytes(b'changed reference')
    with pytest.raises(CanonLockViolation):
        ref_loader.get_refs_for_panel(['SENTINEL_YIELD'])
