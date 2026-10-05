from __future__ import annotations

from datetime import date

from sidestory.core.schedule import is_publish_day, previous_slot, select_anchor
from sidestory.tests.fixtures import main_row


def test_publish_days_are_tue_and_thu() -> None:
    week = [date(2026, 10, 5 + i) for i in range(7)]  # Mon..Sun
    assert [d.isoformat() for d in week if is_publish_day(d)] == ["2026-10-06", "2026-10-08"]


def test_previous_slot() -> None:
    assert previous_slot(date(2026, 10, 8)) == date(2026, 10, 6)
    assert previous_slot(date(2026, 10, 6)) == date(2026, 10, 1)


def test_same_day_anchor_preferred() -> None:
    rows = [main_row("2026-10-05"), main_row("2026-10-06")]
    assert select_anchor(date(2026, 10, 6), rows, set()).episode_date == "2026-10-06"


def test_fallback_to_latest_unanchored_in_window() -> None:
    rows = [main_row("2026-10-05"), main_row("2026-10-04")]
    assert select_anchor(date(2026, 10, 6), rows, set()).episode_date == "2026-10-05"


def test_already_anchored_and_previous_slot_excluded() -> None:
    rows = [main_row("2026-10-06"), main_row("2026-10-07")]
    # Thu 10-08: window (Tue 10-06, Thu 10-08]; 10-06 belongs to the previous slot.
    anchor = select_anchor(date(2026, 10, 8), rows, {"ICG-2026-10-07-001"})
    assert anchor is None


def test_no_main_episode_returns_none() -> None:
    assert select_anchor(date(2026, 10, 6), [], set()) is None
