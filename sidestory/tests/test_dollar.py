"""F3 dollar-index redundancy: selection matrix on the production pattern."""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest

from sidestory.adapters.market.yfinance_dxy import YFinanceDxySource, candidate_from_closes
from sidestory.core.dollar import (
    DollarCandidate,
    DollarIndexKind,
    infer_broad_from_history,
    select_dollar,
)
from sidestory.tests.fixtures import BROAD_HISTORY

MAIN_DAY = date(2026, 10, 5)


def dxy(value=99.8, as_of="2026-10-02", change=-0.4):
    return DollarCandidate(kind=DollarIndexKind.DXY, value=value, as_of=as_of,
                           source="test", change_pct_1w=change)


def test_broad_run_start_inferred_from_carried_forward_values() -> None:
    broad = infer_broad_from_history(BROAD_HISTORY)
    assert broad.value == 120.33
    assert broad.as_of == "2026-09-29"          # first day of the current run, not 10-05
    assert broad.change_pct_1w == pytest.approx((120.33 - 119.5133) / 119.5133 * 100)


def test_broad_whole_window_identical_is_conservative() -> None:
    broad = infer_broad_from_history([("2026-09-14", 118.0), ("2026-10-05", 118.0)])
    assert broad.as_of == "2026-09-14" and broad.change_pct_1w is None


def test_broad_empty_history() -> None:
    assert infer_broad_from_history([]) is None
    assert infer_broad_from_history([("2026-10-05", None)]) is None


def test_dxy_preferred_when_fresh() -> None:
    d = select_dollar(MAIN_DAY, dxy(), infer_broad_from_history(BROAD_HISTORY))
    assert d.chosen.kind is DollarIndexKind.DXY and d.label_ko == "달러인덱스"
    assert d.value == 99.8 and d.rejected == {}


def test_direction_divergence_flag() -> None:
    # DXY -0.4% vs broad +0.68% (production run change) → flagged, still DXY.
    d = select_dollar(MAIN_DAY, dxy(change=-0.4), infer_broad_from_history(BROAD_HISTORY))
    assert "direction_divergence" in d.flags and d.chosen.kind is DollarIndexKind.DXY
    small = select_dollar(MAIN_DAY, dxy(change=-0.1), infer_broad_from_history(BROAD_HISTORY))
    assert "direction_divergence" not in small.flags


def test_fallback_to_broad_when_dxy_missing_or_stale_or_wrong_scale() -> None:
    broad = infer_broad_from_history(BROAD_HISTORY)
    for bad, reason in ((None, "unavailable"),
                        (dxy(as_of="2026-09-30"), "stale"),
                        (dxy(value=120.33), "series mix-up"),   # broad value labelled DXY
                        (dxy(value=1385.0), "out of range"),    # USD/KRW mix-up
                        (dxy(as_of="2026-10-06"), "after reference")):
        d = select_dollar(MAIN_DAY, bad, broad)
        assert d.chosen.kind is DollarIndexKind.BROAD, bad
        assert d.label_ko == "광의 달러지수" and "fallback_broad_index" in d.flags
        assert reason in d.rejected["DXY"], d.rejected


def test_dxy_alone_is_accepted_without_broad() -> None:
    d = select_dollar(MAIN_DAY, dxy(), None)
    assert d.chosen.kind is DollarIndexKind.DXY and d.rejected == {"BROAD": "unavailable"}


def test_omit_when_both_invalid() -> None:
    stale_broad = infer_broad_from_history([("2026-09-15", 118.2), ("2026-09-22", 118.2)])
    d = select_dollar(MAIN_DAY, None, stale_broad)
    assert d.chosen is None and d.value is None
    assert "dollar_omitted" in d.flags and "stale" in d.rejected["BROAD"]


def test_broad_age_boundary() -> None:
    broad = infer_broad_from_history(BROAD_HISTORY)          # run start 09-29
    assert select_dollar(date(2026, 10, 8), None, broad).chosen is not None   # 9 days
    assert select_dollar(date(2026, 10, 9), None, broad).chosen is None       # 10 days


def test_kind_mismatch_rejected() -> None:
    wrong = DollarCandidate(kind=DollarIndexKind.BROAD, value=120.3, as_of="2026-10-05",
                            source="x")
    d = select_dollar(MAIN_DAY, wrong, None)
    assert "kind mismatch" in d.rejected["DXY"] and d.chosen is None


# ── adapter (no network) ─────────────────────────────────────────────────────
def test_candidate_from_closes_latest_bar_on_or_before() -> None:
    bars = [(date(2026, 9, 24) + timedelta(days=i), 100.0 + i * 0.1) for i in range(8)]
    c = candidate_from_closes(bars, date(2026, 9, 30))
    assert c.as_of == "2026-09-30" and c.value == pytest.approx(100.6)
    assert c.change_pct_1w == pytest.approx((100.6 - 100.1) / 100.1 * 100)
    assert candidate_from_closes(bars, date(2026, 9, 1)) is None


def _frame(multi: bool) -> pd.DataFrame:
    idx = pd.to_datetime(["2026-10-01", "2026-10-02"])
    data = {"Close": [100.1, 99.9]}
    frame = pd.DataFrame(data, index=idx)
    if multi:
        frame.columns = pd.MultiIndex.from_tuples([("Close", "DX-Y.NYB")])
    return frame


@pytest.mark.parametrize("multi", [False, True])
def test_yfinance_frame_shapes(multi: bool) -> None:
    calls = {}

    def fake_download(ticker, **kwargs):
        calls.update(kwargs, ticker=ticker)
        return _frame(multi)

    c = YFinanceDxySource(fake_download).dxy_close(date(2026, 10, 5))
    assert calls["ticker"] == "DX-Y.NYB" and calls["end"] == "2026-10-06"
    assert c.kind is DollarIndexKind.DXY and c.as_of == "2026-10-02" and c.value == 99.9


def test_yfinance_failure_returns_none() -> None:
    def boom(*_a, **_k):
        raise ConnectionError("network down")

    assert YFinanceDxySource(boom).dxy_close(date(2026, 10, 5)) is None
    assert YFinanceDxySource(lambda *a, **k: pd.DataFrame()).dxy_close(date(2026, 10, 5)) is None
