"""BL-01: compositor cards never count as missing generated sources."""
from pathlib import Path

from scripts.run_resume import count_missing_paid_sources


def test_text_and_disclaimer_cards_are_not_missing(tmp_path):
    image = tmp_path / "P1.png"
    image.write_bytes(b"x")
    panels = [{"panel_type": "BATTLE"}, {"panel_type": "TEXT_CARD"},
              {"panel_type": "DISCLAIMER"}]
    assert count_missing_paid_sources(panels, [image, None, None]) == 0


def test_missing_or_absent_generated_sources_are_counted(tmp_path):
    panels = [{"panel_type": "COVER"}, {"panel_type": "BATTLE"}, {"panel_type": "AFTERMATH"}]
    assert count_missing_paid_sources(panels, [Path(tmp_path / "gone.png"), None]) == 3
