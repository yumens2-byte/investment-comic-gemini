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


class _Dxy:
    def __init__(self, cand):
        self.cand, self.asked = cand, None

    def dxy_close(self, on_or_before):
        self.asked = on_or_before
        return self.cand


def test_echo_carries_dollar_decision_and_no_raw_broad_index() -> None:
    from sidestory.core.dollar import DollarCandidate, DollarIndexKind

    src = _Dxy(DollarCandidate(kind=DollarIndexKind.DXY, value=99.81, as_of="2026-10-05",
                               source="t", change_pct_1w=0.5))
    result = run_gate_and_echo(date(2026, 10, 6), FakeFeed([main_row("2026-10-05")]),
                               FakeStore(), persist=False, dxy_source=src)
    assert src.asked == date(2026, 10, 5)          # reference = anchored main date
    assert result.echo["dollar"]["kind"] == "DXY" and result.echo["dollar"]["value"] == 99.81
    assert "dollar_index" not in result.echo["market"]


def test_echo_falls_back_to_broad_without_second_source() -> None:
    result = run_gate_and_echo(date(2026, 10, 6), FakeFeed([main_row("2026-10-05")]),
                               FakeStore(), persist=False, dxy_source=None)
    dollar = result.echo["dollar"]
    assert dollar["kind"] == "BROAD" and dollar["as_of"] == "2026-09-29"
    assert dollar["label_ko"] == "광의 달러지수" and "fallback_broad_index" in dollar["flags"]
