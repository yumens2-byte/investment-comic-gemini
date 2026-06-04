from engine.data.sector_fetcher import build_heatmap, classify_sector_state


def test_classify_sector_state_uses_relative_and_absolute_moves() -> None:
    assert classify_sector_state(1.4, 1.1) == "leader"
    assert classify_sector_state(-0.2, 0.7) == "relative_safe"
    assert classify_sector_state(-1.6, -1.2) == "laggard"
    assert classify_sector_state(2.4, 0.1) == "volatile"
    assert classify_sector_state(None, None) == "Unknown"


def test_build_heatmap_ranks_and_keeps_partial_failures() -> None:
    heatmap = build_heatmap(
        {"XLK": 1.2, "XLF": -0.8, "XLE": None, "XLV": 0.3},
        spy_change=0.2,
        as_of="2026-06-03",
    )

    assert heatmap["as_of"] == "2026-06-03"
    assert heatmap["coverage"] > 0
    assert heatmap["leaders"][0]["symbol"] == "XLK"
    assert any(row["symbol"] == "XLE" and row["state"] == "Unknown" for row in heatmap["sectors"])
    xlk = next(row for row in heatmap["sectors"] if row["symbol"] == "XLK")
    assert xlk["relative_pct"] == 1.0
    assert xlk["id"] == "sector:XLK"
