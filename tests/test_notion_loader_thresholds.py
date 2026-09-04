"""2026-09-04 결함 1 회귀 테스트: EVENT_CLASSIFIER_THRESHOLDS 블록 분류."""

from unittest.mock import patch

from engine.common import notion_loader

_PAGE_TEXT = """
## EVENT_CLASSIFIER_THRESHOLDS
{
  "wti_shock_pct": 5.0,
  "vix_shock_level": 24,
  "vix_shock_pct": 25,
  "dgs10_battle": 4.7,
  "spy_collapse_pct": -3.0,
  "nasdaq_collapse_pct": -2.0,
  "btc_battle_abs_pct": 7.0,
  "aftermath_tension": 40,
  "intel_days_since": 2
}
## OUTCOME_THRESHOLDS
{"HERO_VICTORY": 30, "HERO_TACTICAL_VICTORY": 10, "DRAW_UPPER": 9, "DRAW_LOWER": -5, "VILLAIN_TEMP_VICTORY": -10, "HERO_DEFEAT": -30}
"""


def test_event_classifier_thresholds_are_loaded(monkeypatch) -> None:
    monkeypatch.setenv("NOTION_BATTLE_CONSTANTS_ID", "dummy-page")
    with patch.object(notion_loader, "_load_page_cached", return_value=_PAGE_TEXT):
        constants = notion_loader.load_battle_constants()

    thresholds = constants.get("EVENT_CLASSIFIER_THRESHOLDS")
    assert thresholds is not None, "분류 분기 부재 회귀 (2026-09-04 결함 1)"
    assert thresholds["dgs10_battle"] == 4.7
    assert thresholds["nasdaq_collapse_pct"] == -2.0
    assert constants["OUTCOME_THRESHOLDS"]["HERO_VICTORY"] == 30
