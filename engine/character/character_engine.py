"""
engine/character/character_engine.py
ICG 신규 캐릭터 4종 등장 조건 판단 엔진

데이터 소스: icg.daily_snapshots curr_row (step_analysis에서 전달)

컬럼 매핑 (daily_snapshots 실제 컬럼 기준):
  SENTINEL YIELD : us10y, yield_curve (spread_2y10y_bp 대체)
  CRYPTO SHADE   : crypto_basis_state, btc_sentiment_state, crypto_basis_spread, btc_social_sentiment
  SECTOR PHANTOM : 미지원 — daily_snapshots에 etf 데이터 없음 → 항상 ABSENT
  MOMENTUM RIDER : 미지원 — daily_snapshots에 SMA 데이터 없음 → 항상 ABSENT
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Literal

VERSION = "1.0.0"

logger = logging.getLogger(__name__)

COOLDOWN_DAYS = 2

YieldRole = Literal["ARBITRATOR", "WARNER", "OBSERVER", "ABSENT"]
ShadeRole = Literal["DOUBLE_AGENT", "BROKER", "INFORMANT", "ABSENT"]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 1. SENTINEL YIELD — us10y / yield_curve (spread 대체)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def should_appear_sentinel_yield(curr_row: dict) -> tuple[bool, YieldRole]:
    """
    daily_snapshots curr_row 기준 등장 조건 판단.

    Args:
        curr_row: icg.daily_snapshots 최신 행 dict

    Returns:
        (등장여부, 역할코드)
    """
    us10y: float = curr_row.get("us10y") or 0.0
    # daily_snapshots에는 spread_2y10y_bp 없음 → yield_curve 사용
    # yield_curve < 0 = 역전 (10Y < 2Y), 단위는 % 또는 bp (레포 설정 확인 필요)
    yield_curve: float = curr_row.get("yield_curve") or 0.0

    # 역전 구간 — 가장 강력한 등장 (0 미만 = 역전)
    if yield_curve < -0.5:
        logger.info("[CharacterEngine] SENTINEL_YIELD: ARBITRATOR (yield_curve=%.3f)", yield_curve)
        return True, "ARBITRATOR"

    if us10y >= 4.5:
        logger.info("[CharacterEngine] SENTINEL_YIELD: WARNER (us10y=%.2f%%)", us10y)
        return True, "WARNER"

    if 3.0 <= us10y < 4.5 and yield_curve >= 0:
        logger.info("[CharacterEngine] SENTINEL_YIELD: OBSERVER (us10y=%.2f%%)", us10y)
        return True, "OBSERVER"

    return False, "ABSENT"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 2. CRYPTO SHADE — crypto_basis_state / btc_sentiment_state
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def _derive_basis_score(curr_row: dict) -> int:
    """
    crypto_basis_state 우선, 없으면 spread 값으로 파생.
    Premium → 3, Discount → 1, Normal/Unknown → 2
    """
    state = curr_row.get("crypto_basis_state", "Unknown")
    spread = curr_row.get("crypto_basis_spread")

    if state == "Premium":
        return 3
    if state == "Discount":
        return 1
    if state == "Normal":
        return 2
    # state Unknown → spread 값으로 판단
    if spread is not None and spread > 1.0:
        return 3
    if spread is not None and spread < -1.0:
        return 1
    return 2


def _derive_sentiment_score(curr_row: dict) -> int:
    """
    btc_sentiment_state 우선, 없으면 btc_social_sentiment 값으로 파생.
    Bullish → 1, Bearish → 3, Neutral/Unknown → 2
    None 값은 Neutral(2)로 처리 (0으로 기본값 처리 금지).
    """
    state = curr_row.get("btc_sentiment_state", "Unknown")
    sentiment = curr_row.get("btc_social_sentiment")

    if state == "Bullish":
        return 1
    if state == "Bearish":
        return 3
    if state == "Neutral":
        return 2
    # state Unknown → 값으로 판단
    if sentiment is not None and sentiment > 70:
        return 1
    if sentiment is not None and sentiment < 50:
        return 3
    return 2


def should_appear_crypto_shade(curr_row: dict) -> tuple[bool, ShadeRole]:
    """
    daily_snapshots curr_row 기준 등장 조건 판단.
    """
    basis_state: str = curr_row.get("crypto_basis_state", "Unknown")
    sentiment_state: str = curr_row.get("btc_sentiment_state", "Unknown")

    if basis_state == "Unknown" and sentiment_state == "Unknown":
        return False, "ABSENT"

    basis_score = _derive_basis_score(curr_row)
    sentiment_score = _derive_sentiment_score(curr_row)

    # DOUBLE_AGENT: 완전 반대 방향 (score 차이 2 이상 = Premium vs Bullish 등)
    if abs(basis_score - sentiment_score) >= 2:
        logger.info(
            "[CharacterEngine] CRYPTO_SHADE: DOUBLE_AGENT "
            "(basis=%s score=%d vs sentiment=%s score=%d)",
            basis_state, basis_score, sentiment_state, sentiment_score,
        )
        return True, "DOUBLE_AGENT"

    if basis_state in ("Premium", "Discount"):
        logger.info("[CharacterEngine] CRYPTO_SHADE: BROKER (basis=%s)", basis_state)
        return True, "BROKER"

    if sentiment_state in ("Bullish", "Bearish"):
        logger.info("[CharacterEngine] CRYPTO_SHADE: INFORMANT (sentiment=%s)", sentiment_state)
        return True, "INFORMANT"

    return False, "ABSENT"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 3. SECTOR PHANTOM — 현재 미지원 (ETF 데이터 없음)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def should_appear_sector_phantom(
    curr_row: dict,
    prev_story_state: dict,
) -> tuple[bool, str]:
    """
    daily_snapshots에 ETF 랭킹/top_etf_ticker 컬럼 없음.
    Phase 2에서 daily_snapshots에 etf 데이터 추가 후 활성화 예정.
    """
    logger.debug("[CharacterEngine] SECTOR_PHANTOM: ABSENT (ETF 데이터 미지원)")
    return False, "ABSENT"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 4. MOMENTUM RIDER — 현재 미지원 (SMA 데이터 없음)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def should_appear_momentum_rider(curr_row: dict) -> tuple[bool, str]:
    """
    daily_snapshots에 spy_sma50/sma200 컬럼 없음.
    Phase 2에서 SMA 데이터 추가 후 활성화 예정.
    """
    logger.debug("[CharacterEngine] MOMENTUM_RIDER: ABSENT (SMA 데이터 미지원)")
    return False, "ABSENT"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 통합 — 쿨다운 + 최종 리스트
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def resolve_guest_characters(
    curr_row: dict,
    prev_story_state: dict,
) -> list[tuple[str, str]]:
    """
    오늘 등장할 게스트 캐릭터 목록 반환 (쿨다운 적용).

    Args:
        curr_row: icg.daily_snapshots 최신 행
        prev_story_state: 전날 story_state_json (없으면 {})

    Returns:
        [(캐릭터코드, 역할코드), ...]
    """
    logger.info("[CharacterEngine] v%s 게스트 캐릭터 판단 시작", VERSION)
    candidates: list[tuple[str, str]] = []

    yield_appear, yield_role = should_appear_sentinel_yield(curr_row)
    if yield_appear:
        candidates.append(("SENTINEL_YIELD", yield_role))

    shade_appear, shade_role = should_appear_crypto_shade(curr_row)
    if shade_appear:
        candidates.append(("CRYPTO_SHADE", shade_role))

    # SECTOR_PHANTOM, MOMENTUM_RIDER: 미지원 → 항상 ABSENT
    should_appear_sector_phantom(curr_row, prev_story_state)
    should_appear_momentum_rider(curr_row)

    filtered = _apply_cooldown(candidates, prev_story_state)

    logger.info(
        "[CharacterEngine] 최종 등장: %s",
        [f"{c}({r})" for c, r in filtered] or ["없음"],
    )
    return filtered


def _apply_cooldown(
    candidates: list[tuple[str, str]],
    prev_story_state: dict,
) -> list[tuple[str, str]]:
    """쿨다운(COOLDOWN_DAYS) 미충족 캐릭터 제거."""
    today = datetime.now(tz=timezone.utc).date()
    char_states: dict = prev_story_state.get("character_states", {})
    result = []

    for char_code, role in candidates:
        key = char_code.lower()
        last_appear_str: str | None = char_states.get(key, {}).get("last_appear_date")
        if last_appear_str:
            last_date = datetime.fromisoformat(last_appear_str).date()
            if (today - last_date).days < COOLDOWN_DAYS:
                logger.info(
                    "[CharacterEngine] 쿨다운 미충족 스킵: %s", char_code
                )
                continue
        result.append((char_code, role))

    return result
