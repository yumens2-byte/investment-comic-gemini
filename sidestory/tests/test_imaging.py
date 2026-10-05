"""B1 band trimming (pilot 1: P2 white frame, P5 letterbox)."""
from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

from sidestory.app.imaging import detect_bands, trim_panel


def _content(w, h, seed=0):
    rng = np.random.default_rng(seed)
    return rng.integers(30, 220, (h, w, 3), dtype=np.uint8)


def _img(arr):
    return Image.fromarray(arr.astype(np.uint8))


def test_letterbox_like_pilot1_p5(tmp_path) -> None:
    a = _content(1024, 1024)
    a[:96] = 0
    a[-97:] = 2
    res = detect_bands(_img(a))
    assert res.box == (0, 96 + 4, 1024, 1024 - 97 - 4) and res.trimmed


def test_white_frame_with_black_rule_like_pilot1_p2() -> None:
    a = _content(1024, 1024)
    a[:143], a[-143:], a[:, :31], a[:, -32:] = 255, 255, 255, 255
    a[143:147, 31:-32] = 0          # black rule inside the white margin
    a[-147:-143, 31:-32] = 0
    res = detect_bands(_img(a))
    assert res.box[1] >= 147 and res.box[3] <= 1024 - 147
    assert res.box[0] >= 31 and res.box[2] <= 1024 - 32
    assert res.kept_ratio > 0.6


@pytest.mark.parametrize("name,mutate", [
    ("clean", lambda a: a),
    ("thin 4px line", lambda a: a.__setitem__((slice(0, 4),), 0)),
])
def test_no_trim_for_clean_or_thin_lines(name, mutate) -> None:
    a = _content(800, 1200)
    mutate(a)
    assert not detect_bands(_img(a)).trimmed, name


def test_side_cap_prevents_overcut() -> None:
    a = _content(1000, 1000)
    a[:500] = 0                      # half the image dark and flat: not a band, cap at 30%
    res = detect_bands(_img(a))
    assert res.box[1] == 0


def test_dark_textured_sky_not_trimmed() -> None:
    rng = np.random.default_rng(3)
    a = rng.normal(22, 8, (1024, 1024, 3)).clip(0, 255)   # dark but grainy (pilot P1/P6 style)
    assert not detect_bands(_img(a)).trimmed


def test_trim_panel_writes_copy_and_keeps_original(tmp_path) -> None:
    a = _content(600, 600)
    a[:60] = 0
    a[-60:] = 0
    src = tmp_path / "P5.png"
    _img(a).save(src)
    before = src.read_bytes()
    used, res = trim_panel(src, tmp_path / "trimmed")
    assert used == tmp_path / "trimmed" / "P5.png" and src.read_bytes() == before
    with Image.open(used) as out:
        assert out.size == (600, 472)
    clean = tmp_path / "P1.png"
    _img(_content(600, 600)).save(clean)
    assert trim_panel(clean, tmp_path / "trimmed")[0] == clean
