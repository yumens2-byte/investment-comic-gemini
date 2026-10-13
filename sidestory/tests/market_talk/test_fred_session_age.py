from datetime import datetime

import pytest

from sidestory.market_talk.policy import KST, PolicyError, validate_source
from sidestory.tests.market_talk.test_automation import snapshot


def source(session="2026-10-08", provider="FRED", instrument="DGS10"):
    row = snapshot()
    row["snapshot_date"] = "2026-10-13"
    row["created_at"] = "2026-10-13T08:10:00+09:00"
    for meta in row["data_quality"]["source_status"].values():
        meta.update(observed_at=row["created_at"], market_session_date="2026-10-12")
    row["data_quality"]["source_status"]["us10y"].update(
        provider=provider, instrument=instrument, market_session_date=session
    )
    return row


def test_fred_latest_observation_spanning_weekend_remains_original_date():
    row = source()
    assert validate_source(row, datetime(2026, 10, 13, 16, tzinfo=KST)) is row
    assert row["data_quality"]["source_status"]["us10y"]["market_session_date"] == "2026-10-08"


@pytest.mark.parametrize(
    "session,provider,instrument",
    [
        ("2026-10-07", "FRED", "DGS10"),
        ("2026-10-08", "yfinance", "DGS10"),
        ("2026-10-08", "FRED", "OTHER"),
        ("2026-10-14", "FRED", "DGS10"),
    ],
)
def test_allowance_is_bounded_and_specific(session, provider, instrument):
    with pytest.raises(PolicyError, match="SOURCE_SESSION_INVALID"):
        validate_source(
            source(session, provider, instrument), datetime(2026, 10, 13, 16, tzinfo=KST)
        )


def test_other_fields_remain_calendar_day_bounded():
    row = source()
    row["data_quality"]["source_status"]["vix"]["market_session_date"] = "2026-10-08"
    with pytest.raises(PolicyError, match="SOURCE_SESSION_INVALID"):
        validate_source(row, datetime(2026, 10, 13, 16, tzinfo=KST))
