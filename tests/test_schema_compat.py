"""engine.common.schema_compat 단위 테스트.

C-리팩토링(2026-06-30): asset_writer / arc_state_engine / snapshot_writer 에
중복돼 있던 _missing_schema_column_from_error 를 공통 모듈로 추출했다.
공통 함수의 정확성과, 3개 래퍼가 공통 함수와 동일하게 동작함을 검증한다.
"""

from __future__ import annotations

import pytest

from engine.common.schema_compat import extract_missing_column


@pytest.mark.parametrize(
    "message,expected",
    [
        (
            "{'code': 'PGRST204', 'message': \"Could not find the 'data_quality' "
            "column of 'daily_snapshots' in the schema cache\"}",
            "data_quality",
        ),
        (
            "Could not find the 'character_selection' column of 'daily_analysis'",
            "character_selection",
        ),
        (
            "Could not find the 'zero_block_just_appeared' column",
            "zero_block_just_appeared",
        ),
    ],
)
def test_extract_returns_missing_column(message: str, expected: str) -> None:
    assert extract_missing_column(Exception(message)) == expected


@pytest.mark.parametrize(
    "message",
    [
        "duplicate key value violates unique constraint",
        "connection timeout",
        "",
        "PGRST204 but no recognizable column phrase here",
    ],
)
def test_extract_returns_none_for_non_schema_errors(message: str) -> None:
    assert extract_missing_column(Exception(message)) is None


def test_wrappers_match_common_source() -> None:
    """3개 writer 래퍼가 공통 함수와 동일 결과를 반환해야 한다(회귀 방지)."""
    from engine.arc.arc_state_engine import (
        _missing_schema_column_from_error as arc_wrap,
    )
    from engine.data.snapshot_writer import (
        _missing_schema_column_from_error as snap_wrap,
    )
    from engine.persist.asset_writer import (
        _missing_schema_column_from_error as asset_wrap,
    )

    samples = [
        Exception("Could not find the 'data_quality' column of 'daily_snapshots'"),
        Exception("PGRST204 unrelated"),
        Exception("some other db error"),
    ]
    for exc in samples:
        expected = extract_missing_column(exc)
        assert asset_wrap(exc) == expected
        assert arc_wrap(exc) == expected
        assert snap_wrap(exc) == expected
