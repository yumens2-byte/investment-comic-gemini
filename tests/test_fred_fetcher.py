import pandas as pd

from engine.data.fred_fetcher import _fetch_series


class FakeFred:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def get_series(self, series_id: str, *, observation_start: str, observation_end: str):
        self.calls.append(
            {
                "series_id": series_id,
                "observation_start": observation_start,
                "observation_end": observation_end,
            }
        )
        return pd.Series([None, 4.25])


def test_fetch_series_uses_target_date_for_observation_window() -> None:
    fred = FakeFred()

    value = _fetch_series(fred, "DGS10", lookback_days=10, target_date="2026-06-20")

    assert value == 4.25
    assert fred.calls == [
        {
            "series_id": "DGS10",
            "observation_start": "2026-06-10",
            "observation_end": "2026-06-20",
        }
    ]
