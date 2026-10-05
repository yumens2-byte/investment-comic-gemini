from __future__ import annotations

from datetime import date

from sidestory.app.pipeline import run_gate_and_echo, side_episode_id
from sidestory.tests.fixtures import FakeFeed, FakeStore, main_row


def test_side_episode_id_format() -> None:
    assert side_episode_id(date(2026, 10, 6)) == "SIDE-2026-10-06-01"


def test_echo_persists_draft_and_passes_sg7() -> None:
    store = FakeStore()
    result = run_gate_and_echo(date(2026, 10, 6), FakeFeed([main_row()]), store)
    assert [g.gate for g in result.gates] == ["SG-0", "SG-1", "SG-7"]
    assert all(g.passed for g in result.gates)
    saved = store.episodes["SIDE-2026-10-06-01"]
    assert saved["anchor_main_episode"] == "ICG-2026-10-06-001"
    assert saved["outcome_class"] == "VICTORY"
    assert saved["status"] == "draft"


def test_read_only_mode_writes_nothing() -> None:
    store = FakeStore()
    result = run_gate_and_echo(date(2026, 10, 6), FakeFeed([main_row()]), store, persist=False)
    assert result.echo is not None and not result.persisted
    assert store.episodes == {} and store.logs == []


def test_skip_on_non_slot_day_and_no_anchor() -> None:
    store = FakeStore()
    assert run_gate_and_echo(date(2026, 10, 7), FakeFeed([main_row("2026-10-07")]), store).skipped
    assert run_gate_and_echo(date(2026, 10, 6), FakeFeed([]), store).skipped
    assert store.episodes == {}


def test_sg7_flags_main_change() -> None:
    feed = FakeFeed([main_row()], fingerprints=("a" * 64, "b" * 64))
    store = FakeStore()
    result = run_gate_and_echo(date(2026, 10, 6), feed, store)
    assert not result.gates[-1].passed
    assert store.logs[-1][1] == "hold"


def test_rerun_same_slot_never_reanchors_or_overwrites() -> None:
    """Regression (found by db_contract E5): a rerun fell back to an older main
    episode and overwrote the slot's draft with a different anchor."""
    store = FakeStore()
    feed = FakeFeed([main_row("2026-10-05", outcome="DRAW"), main_row("2026-10-06")])
    first = run_gate_and_echo(date(2026, 10, 6), feed, store)
    assert first.persisted
    store.anchored = {store.episodes["SIDE-2026-10-06-01"]["anchor_main_episode"]}
    snapshot = dict(store.episodes)
    second = run_gate_and_echo(date(2026, 10, 6), feed, store)
    assert second.skipped and "slot exists" in second.gates[0].reason
    assert store.episodes == snapshot
