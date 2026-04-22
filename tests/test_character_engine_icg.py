"""
tests/test_character_engine_icg.py
ICG character_engine — curr_row (daily_snapshots) 기반 테스트
conftest.py가 engine.common.supabase_client 모킹 처리
"""
from __future__ import annotations

import pytest

from engine.character.character_engine import (
    _apply_cooldown,
    _derive_basis_score,
    _derive_sentiment_score,
    resolve_guest_characters,
    should_appear_crypto_shade,
    should_appear_momentum_rider,
    should_appear_sector_phantom,
    should_appear_sentinel_yield,
)


@pytest.fixture()
def empty_row() -> dict:
    return {}


@pytest.fixture()
def empty_state() -> dict:
    return {}


# ──────────────────────────────────────────────────────────
# SENTINEL YIELD (us10y + yield_curve 기반)
# ──────────────────────────────────────────────────────────
class TestSentinelYield:
    def test_arbitrator_yield_curve_inverted(self):
        row = {"us10y": 4.0, "yield_curve": -0.6}
        appear, role = should_appear_sentinel_yield(row)
        assert appear and role == "ARBITRATOR"

    def test_arbitrator_boundary_minus_05_not_triggered(self):
        row = {"us10y": 4.0, "yield_curve": -0.5}
        _, role = should_appear_sentinel_yield(row)
        assert role != "ARBITRATOR"

    def test_warner_high_us10y(self):
        row = {"us10y": 4.5, "yield_curve": 0.1}
        appear, role = should_appear_sentinel_yield(row)
        assert appear and role == "WARNER"

    def test_warner_above_threshold(self):
        row = {"us10y": 5.2, "yield_curve": 0.2}
        _, role = should_appear_sentinel_yield(row)
        assert role == "WARNER"

    def test_observer_normal(self):
        row = {"us10y": 3.8, "yield_curve": 0.3}
        appear, role = should_appear_sentinel_yield(row)
        assert appear and role == "OBSERVER"

    def test_absent_low_rate(self):
        row = {"us10y": 2.0, "yield_curve": 0.5}
        appear, role = should_appear_sentinel_yield(row)
        assert not appear and role == "ABSENT"

    def test_absent_empty_row(self, empty_row):
        appear, role = should_appear_sentinel_yield(empty_row)
        assert not appear and role == "ABSENT"

    def test_arbitrator_overrides_warner(self):
        row = {"us10y": 5.0, "yield_curve": -0.8}
        _, role = should_appear_sentinel_yield(row)
        assert role == "ARBITRATOR"

    def test_none_values(self):
        row = {"us10y": None, "yield_curve": None}
        appear, _ = should_appear_sentinel_yield(row)
        assert not appear


# ──────────────────────────────────────────────────────────
# score 파생 함수
# ──────────────────────────────────────────────────────────
class TestDeriveScores:
    def test_basis_premium_state(self):
        assert _derive_basis_score({"crypto_basis_state": "Premium"}) == 3

    def test_basis_discount_state(self):
        assert _derive_basis_score({"crypto_basis_state": "Discount"}) == 1

    def test_basis_normal_state(self):
        assert _derive_basis_score({"crypto_basis_state": "Normal"}) == 2

    def test_basis_from_spread_premium(self):
        assert _derive_basis_score({"crypto_basis_spread": 1.5}) == 3

    def test_basis_from_spread_discount(self):
        assert _derive_basis_score({"crypto_basis_spread": -1.5}) == 1

    def test_sentiment_bullish_state(self):
        assert _derive_sentiment_score({"btc_sentiment_state": "Bullish"}) == 1

    def test_sentiment_bearish_state(self):
        assert _derive_sentiment_score({"btc_sentiment_state": "Bearish"}) == 3

    def test_sentiment_neutral_state(self):
        assert _derive_sentiment_score({"btc_sentiment_state": "Neutral"}) == 2

    def test_sentiment_from_value_high(self):
        assert _derive_sentiment_score({"btc_social_sentiment": 80}) == 1

    def test_sentiment_from_value_low(self):
        assert _derive_sentiment_score({"btc_social_sentiment": 40}) == 3


# ──────────────────────────────────────────────────────────
# CRYPTO SHADE (curr_row 컬럼 기반)
# ──────────────────────────────────────────────────────────
class TestCryptoShade:
    def test_double_agent_state_mismatch(self):
        # Premium(score=3) + Bullish(score=1) → diff=2 → DOUBLE_AGENT
        row = {
            "crypto_basis_state": "Premium",
            "btc_sentiment_state": "Bullish",
            "crypto_basis_spread": 1.5,
            "btc_social_sentiment": 80,
        }
        appear, role = should_appear_crypto_shade(row)
        assert appear and role == "DOUBLE_AGENT"

    def test_broker_premium(self):
        # Premium(score=3) + Bearish(score=3) → diff=0 → BROKER
        row = {
            "crypto_basis_state": "Premium",
            "btc_sentiment_state": "Bearish",
            "crypto_basis_spread": 1.2,
            "btc_social_sentiment": 35,
        }
        appear, role = should_appear_crypto_shade(row)
        assert appear and role == "BROKER"

    def test_informant_bearish_sentiment(self):
        # Normal(score=2) + Bearish(score=3) → diff=1 < 2 → INFORMANT
        row = {
            "crypto_basis_state": "Normal",
            "btc_sentiment_state": "Bearish",
            "crypto_basis_spread": 0.2,
            "btc_social_sentiment": 35,
        }
        appear, role = should_appear_crypto_shade(row)
        assert appear and role == "INFORMANT"

    def test_absent_both_unknown(self, empty_row):
        appear, role = should_appear_crypto_shade(empty_row)
        assert not appear and role == "ABSENT"

    def test_absent_neutral_match(self):
        row = {
            "crypto_basis_state": "Normal",
            "btc_sentiment_state": "Neutral",
            "crypto_basis_spread": 0.3,
            "btc_social_sentiment": 60,
        }
        appear, role = should_appear_crypto_shade(row)
        assert not appear and role == "ABSENT"


# ──────────────────────────────────────────────────────────
# SECTOR PHANTOM / MOMENTUM RIDER — 항상 ABSENT
# ──────────────────────────────────────────────────────────
class TestMisuportedCharacters:
    def test_sector_phantom_always_absent(self, empty_row, empty_state):
        appear, role = should_appear_sector_phantom(empty_row, empty_state)
        assert not appear and role == "ABSENT"

    def test_momentum_rider_always_absent(self, empty_row):
        appear, role = should_appear_momentum_rider(empty_row)
        assert not appear and role == "ABSENT"


# ──────────────────────────────────────────────────────────
# resolve_guest_characters
# ──────────────────────────────────────────────────────────
class TestResolveGuestCharacters:
    def test_no_trigger_empty_row(self, empty_row, empty_state):
        result = resolve_guest_characters(empty_row, empty_state)
        assert result == []

    def test_sentinel_yield_appears(self, empty_state):
        row = {"us10y": 5.0, "yield_curve": 0.1}
        result = resolve_guest_characters(row, empty_state)
        codes = [c for c, _ in result]
        assert "SENTINEL_YIELD" in codes

    def test_crypto_shade_appears(self, empty_state):
        row = {
            "crypto_basis_state": "Premium",
            "btc_sentiment_state": "Bearish",
            "crypto_basis_spread": 1.5,
            "btc_social_sentiment": 35,
        }
        result = resolve_guest_characters(row, empty_state)
        codes = [c for c, _ in result]
        assert "CRYPTO_SHADE" in codes

    def test_cooldown_filters(self):
        from datetime import date, timedelta

        yesterday = (date.today() - timedelta(days=1)).isoformat()
        prev_state = {
            "character_states": {
                "sentinel_yield": {"last_appear_date": yesterday}
            }
        }
        row = {"us10y": 5.0, "yield_curve": 0.1}
        result = resolve_guest_characters(row, prev_state)
        codes = [c for c, _ in result]
        assert "SENTINEL_YIELD" not in codes


# ──────────────────────────────────────────────────────────
# _apply_cooldown
# ──────────────────────────────────────────────────────────
class TestApplyCooldown:
    def test_empty_candidates(self):
        assert _apply_cooldown([], {}) == []

    def test_no_state_passes(self):
        candidates = [("SENTINEL_YIELD", "WARNER")]
        assert _apply_cooldown(candidates, {}) == candidates

    def test_filters_yesterday(self):
        from datetime import date, timedelta

        yesterday = (date.today() - timedelta(days=1)).isoformat()
        state = {"character_states": {"sentinel_yield": {"last_appear_date": yesterday}}}
        result = _apply_cooldown([("SENTINEL_YIELD", "WARNER")], state)
        assert result == []

    def test_passes_two_days_ago(self):
        from datetime import date, timedelta

        from engine.character.character_engine import COOLDOWN_DAYS

        old = (date.today() - timedelta(days=COOLDOWN_DAYS)).isoformat()
        state = {"character_states": {"sentinel_yield": {"last_appear_date": old}}}
        result = _apply_cooldown([("SENTINEL_YIELD", "WARNER")], state)
        assert len(result) == 1
