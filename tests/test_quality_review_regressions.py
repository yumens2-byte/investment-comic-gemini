"""Regression cases independently reproduced during the additional code review."""

import runpy
from pathlib import Path

import pytest
from PIL import Image

from engine.quality.contracts import QualityHold, digest
from engine.quality.release import build_release
from engine.quality.render import Rect, compose_quality_panel

_helpers = runpy.run_path(str(Path(__file__).with_name("test_webtoon_quality.py")))
quality_fixture = _helpers["fixture"]
reviewed_release = _helpers["reviewed_release"]


@pytest.fixture
def review_fixture(tmp_path):
    return quality_fixture.__wrapped__(tmp_path)


def reapprove_changed_inputs(inputs, report, release):
    """Keep every hash consistent to isolate the missing source-contract gate."""
    synthetic = bool(inputs.get("evidence", {}).get("synthetic"))
    content_hash = digest(
        dict(
            episode_id=release.episode_id,
            version=release.release_version,
            inputs={key: digest(value) for key, value in inputs.items()},
            artifacts=release.artifacts,
            channels=release.required_channels,
            synthetic=synthetic,
        )
    )
    report = report.model_copy(update={"content_hash": content_hash})
    release = build_release(
        episode_id=release.episode_id,
        version=release.release_version,
        synthetic=synthetic,
        inputs=inputs,
        artifacts=release.artifacts,
        channels=release.required_channels,
        report=report,
        approved_by=release.approved_by,
        approved_at=release.approved_at,
    )
    return report, release


@pytest.mark.parametrize(
    "missing", ["all", "evidence", "editorial", "claims", "canon", "script", "calculation"]
)
def test_release_rejects_missing_sources_even_with_consistent_approval(review_fixture, missing):
    inputs, _, report, release = reviewed_release(review_fixture)
    if missing == "all":
        inputs.clear()
    else:
        del inputs[missing]
    report, release = reapprove_changed_inputs(inputs, report, release)
    with pytest.raises(QualityHold, match="required release source contracts missing"):
        release.verify(review_fixture["root"], inputs, report, live=missing == "all")


@pytest.mark.parametrize("mutation", ["calculation", "claims", "canon_reference"])
def test_release_revalidates_sources_after_reapproval(review_fixture, mutation):
    inputs, _, report, release = reviewed_release(review_fixture)
    if mutation == "calculation":
        inputs["calculation"]["outcome"] = "BATTLE_LOSS"
    elif mutation == "claims":
        inputs["claims"] = inputs["claims"][1:]
    else:
        inputs["canon"]["entries"][0]["ref_sha256"] = "0" * 64
    report, release = reapprove_changed_inputs(inputs, report, release)
    with pytest.raises(QualityHold):
        release.verify(review_fixture["root"], inputs, report)


@pytest.mark.parametrize("boundary", ["right", "bottom"])
def test_text_background_preserves_touching_protected_pixels(tmp_path, boundary):
    font = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
    if not font.is_file():
        pytest.skip("font fixture unavailable")
    source = tmp_path / "source.png"
    Image.new("RGB", (1080, 1350), "blue").save(source)
    text_area = Rect(x=0, y=0, width=100, height=100)
    if boundary == "right":
        protected = Rect(x=100, y=0, width=10, height=100)
        pixel = (100, 50)
    else:
        protected = Rect(x=0, y=100, width=100, height=10)
        pixel = (50, 100)
    assert not text_area.intersects(protected)
    output = tmp_path / "composed.png"
    compose_quality_panel(
        image_path=source,
        text="",
        text_area=text_area,
        protected=[protected],
        font_path=font,
        output=output,
    )
    with Image.open(output) as image:
        assert image.getpixel(pixel) == (0, 0, 255)
        assert image.getpixel((99, 99)) == (5, 10, 20)
