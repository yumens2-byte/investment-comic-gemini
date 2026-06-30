"""
engine/common/schema_compat.py
ICG 파이프라인 공통 schema-compatibility 유틸리티.

배경:
    GitHub Actions가 Supabase migration / PostgREST schema-cache 갱신보다
    먼저 코드를 배포하면, 새로 추가된 optional 컬럼에 대해 PostgREST가
    PGRST204("Could not find the '<col>' column") 를 반환한다.

    asset_writer / arc_state_engine / snapshot_writer 세 모듈이 각자
    동일한 누락 컬럼명 파싱 로직을 중복 구현하고 있었다(DRY 위반).
    이 모듈은 그 파싱 로직의 단일 진실 소스(single source of truth)다.

    각 writer의 strip 정책(one_by_one vs all_at_once)은 모듈별로 다르므로
    여기서 통합하지 않는다(과도 추상화 회피). 파싱만 공통화한다.

VERSION: 1.0.0
"""

from __future__ import annotations

import re

VERSION = "1.0.0"

# PostgREST PGRST204 메시지에서 누락 컬럼명을 추출하는 정규식.
# 예: "Could not find the 'data_quality' column of 'daily_snapshots' ..."
_MISSING_COLUMN_PATTERN = re.compile(r"Could not find the '([^']+)' column")


def extract_missing_column(exc: Exception) -> str | None:
    """PostgREST schema-cache 누락 컬럼명을 예외 메시지에서 추출한다.

    Args:
        exc: Supabase/PostgREST upsert/update 호출에서 발생한 예외.

    Returns:
        누락 컬럼명(예: ``"data_quality"``). schema-cache 누락 패턴이 아니면
        ``None`` (호출부가 이 경우 재시도하지 않고 그대로 raise 하도록 한다).
    """
    text = str(exc)
    if "PGRST204" not in text and "Could not find" not in text:
        return None
    match = _MISSING_COLUMN_PATTERN.search(text)
    if not match:
        return None
    return match.group(1)
