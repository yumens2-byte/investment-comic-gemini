"""Exhaustive 2-year simulation of the Tue/Thu cadence against Mon–Sat main publishing."""
from __future__ import annotations

import random
from datetime import date, timedelta

import pytest

from sidestory.app.pipeline import run_gate_and_echo
from sidestory.core.schedule import is_publish_day, previous_slot
from sidestory.tests.fixtures import FakeFeed, FakeStore, main_row

START, END = date(2026, 1, 1), date(2027, 12, 31)


def _days():
    day = START
    while day <= END:
        yield day
        day += timedelta(days=1)


@pytest.mark.parametrize("skip_ratio", [0.0, 0.3, 0.7])
def test_two_year_simulation(skip_ratio: float) -> None:
    rng = random.Random(20261005)
    rows = [main_row(d.isoformat()) for d in _days()
            if d.weekday() <= 5 and rng.random() >= skip_ratio]  # main: Mon–Sat
    feed, store = FakeFeed(rows), FakeStore()
    produced: list[tuple[date, str]] = []
    for day in _days():
        result = run_gate_and_echo(day, feed, store)
        if result.persisted:
            anchor = store.episodes[result.side_episode_id]["anchor_main_episode"]
            store.anchored.add(anchor)
            produced.append((day, anchor))

    anchors = [a for _, a in produced]
    assert len(anchors) == len(set(anchors)), "a main episode was echoed twice"
    for day, anchor in produced:
        assert is_publish_day(day), f"published on non-slot day {day}"
        main_day = date.fromisoformat(anchor[4:14])
        assert previous_slot(day) < main_day <= day, (day, anchor)
        assert (day - main_day).days <= 3
    slots = sum(1 for d in _days() if is_publish_day(d))
    if skip_ratio == 0.0:
        assert len(produced) == slots  # every Tue/Thu has a same-day main episode
    assert len(produced) <= slots


def test_year_boundary_previous_slot() -> None:
    assert previous_slot(date(2027, 1, 5)) == date(2026, 12, 31)  # Tue → prior Thu
