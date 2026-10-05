from __future__ import annotations

from sidestory.core.echo import build_echo_pack
from sidestory.core.models import OutcomeClass
from sidestory.tests.fixtures import arc_row, main_row, market_row


def test_echo_copies_main_values_verbatim() -> None:
    echo = build_echo_pack("2026-10-06", main_row(), market_row(), arc_row())
    assert echo.main_episode_id == "ICG-2026-10-06-001"
    assert echo.title == "첨탑 아래의 방패"
    assert echo.outcome == "HERO_VICTORY"
    assert echo.outcome_class is OutcomeClass.VICTORY
    assert echo.next_hook == "30년물이 다시 문을 두드린다"
    assert echo.main_threads == ["첨탑의 균열은 어디서 시작됐나", "방패의 한계"]
    assert echo.market["us10y"] == 5.24
    assert echo.arc["arc_tension"] == 87


def test_next_hook_falls_back_to_final_story_panel() -> None:
    row = main_row()
    row.script_json.pop("_continuity")
    echo = build_echo_pack("2026-10-06", row, None, None)
    # TEXT_CARD and DISCLAIMER are skipped, same as main continuity.
    assert echo.next_hook == "첨탑은 아직 서 있다"
    assert echo.market == {}
    assert echo.arc == {}


def test_no_battle_main_episode() -> None:
    echo = build_echo_pack("2026-10-06", main_row(outcome="DRAW", scenario="NO_BATTLE"),
                           None, None)
    assert echo.outcome_class is OutcomeClass.NO_BATTLE
