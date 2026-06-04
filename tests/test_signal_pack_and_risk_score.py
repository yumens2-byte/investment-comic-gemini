from engine.analysis.risk_score_engine import compute
from engine.analysis.signal_pack_builder import build_signal_pack


def test_signal_pack_builder_normalizes_sector_jsonb() -> None:
    delta = {
        "VIX": {"curr": 18.0, "pct": 5.0},
        "SPY": {"curr": -0.4, "pct": -0.2},
    }
    snapshot = {
        "sector_heatmap": {
            "sectors": [
                {
                    "id": "sector:XLK",
                    "symbol": "XLK",
                    "name": "Technology",
                    "change_pct": -2.1,
                    "relative_pct": -1.7,
                    "state": "laggard",
                    "confidence": 0.92,
                }
            ]
        },
        "event_calendar": [{"name": "CPI", "importance": 5}],
        "news_items": [{"id": "news:fed", "relevance_score": 0.8}],
    }

    pack = build_signal_pack(delta, snapshot)

    assert pack["version"] == "pilot-1"
    assert pack["by_domain"]["sector"][0]["symbol"] == "XLK"
    assert pack["economic_events"][0]["name"] == "CPI"
    assert pack["data_confidence"] > 0


def test_risk_score_uses_multiple_domains_when_vix_is_not_extreme() -> None:
    pack = build_signal_pack(
        {
            "VIX": {"curr": 19.0, "pct": 4.0},
            "SPY": {"curr": -2.3, "pct": -1.0},
            "NASDAQ": {"curr": -2.8, "pct": -1.4},
            "DGS10": {"curr": 4.95, "pct": 8.0},
            "HY_SPREAD": {"curr": 5.2, "pct": 4.0},
            "WTI": {"curr": 82.0, "pct": 3.0},
        },
        {
            "sector_heatmap": {
                "sectors": [
                    {"symbol": "XLK", "name": "Technology", "change_pct": -3.0, "state": "laggard", "confidence": 0.9},
                    {"symbol": "XLF", "name": "Financials", "change_pct": -2.0, "state": "laggard", "confidence": 0.9},
                ]
            }
        },
    )

    trace = compute(pack)

    assert trace["risk_score"] >= 35
    assert trace["risk_level"] in {"MEDIUM", "HIGH"}
    assert trace["risk_drivers"]
    assert trace["domain_scores"]["equity_breadth"] > 0
