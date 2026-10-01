from types import SimpleNamespace

import pytest

import shorts_media
from engine.video import shorts_media as video_shorts


@pytest.mark.parametrize("module", [shorts_media, video_shorts])
def test_short_ref_loader_failure_blocks(module, monkeypatch):
    from engine.image import ref_loader

    def failing(_):
        raise RuntimeError("canon unavailable")

    monkeypatch.setattr(ref_loader, "get_refs_for_panel", failing)
    with pytest.raises(module.ShortsMediaError):
        module._load_character_refs(SimpleNamespace(hero_ids=["EDT"], villain_id="DEBT_TITAN"))


@pytest.mark.parametrize("module", [shorts_media, video_shorts])
def test_short_missing_ref_blocks(module, monkeypatch):
    from engine.image import ref_loader

    monkeypatch.setattr(ref_loader, "get_refs_for_panel", lambda _: [])
    with pytest.raises(module.ShortsMediaError):
        module._load_character_refs(SimpleNamespace(hero_ids=["EDT"], villain_id="DEBT_TITAN"))


@pytest.mark.parametrize("module", [shorts_media, video_shorts])
def test_short_cast_refs_present(module, monkeypatch, tmp_path):
    from engine.image import ref_loader

    refs = [tmp_path / "hero.png", tmp_path / "villain.png"]
    for ref in refs:
        ref.write_bytes(b"reference")
    monkeypatch.setattr(ref_loader, "get_refs_for_panel", lambda _: refs)
    assert module._load_character_refs(
        SimpleNamespace(hero_ids=["EDT", "EDT"], villain_id="DEBT_TITAN")
    ) == refs
