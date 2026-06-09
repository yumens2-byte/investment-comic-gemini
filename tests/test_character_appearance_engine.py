from engine.narrative.character_appearance_engine import (
    resolve_character_selection,
    score_hero,
    score_neutral_guests,
    score_villain,
)


def _delta(**overrides):
    base = {
        "VIX": {"curr": 18.0, "pct": 0.0},
        "WTI": {"curr": 75.0, "pct": 0.0},
        "DGS10": {"curr": 4.2, "pct": 0.0},
        "HY_SPREAD": {"curr": 350.0, "pct": 0.0},
        "SPY": {"curr": 500.0, "pct": 0.0},
        "NASDAQ": {"curr": 16000.0, "pct": 0.0},
        "FEAR_GREED": {"curr": 50.0, "pct": 0.0},
    }
    for key, value in overrides.items():
        metric, field = key.rsplit("_", 1)
        base.setdefault(metric, {})[field] = value
    return base


def test_oil_shock_selects_leverage_and_oil_titan():
    delta = _delta(WTI_curr=96.0, WTI_pct=8.2)

    result = resolve_character_selection(
        delta=delta,
        event_type="BATTLE",
        scenario_type="ONE_VS_ONE",
        risk_level="MEDIUM",
        base_hero_id="CHAR_HERO_001",
        base_villain_id="CHAR_VILLAIN_004",
        arc_context={"tension": 40},
    )

    assert result.primary_villain == "CHAR_VILLAIN_002"
    assert result.primary_hero == "CHAR_HERO_003"
    assert "WTI pct >= 8" in " ".join(
        d.reasons[0] for d in result.all_candidates if d.char_id == "CHAR_VILLAIN_002"
    )


def test_rate_credit_stress_scores_iron_nuna_and_debt_titan():
    delta = _delta(DGS10_curr=5.1, DGS10_pct=6.0, HY_SPREAD_curr=520.0)

    villain = score_villain("CHAR_VILLAIN_001", delta, "BATTLE")
    hero = score_hero(
        "CHAR_HERO_002",
        delta,
        "ONE_VS_ONE",
        "BATTLE",
        "CHAR_VILLAIN_001",
        {"tension": 50},
    )

    assert villain.appear
    assert villain.score >= 60
    assert hero.appear
    assert hero.score_breakdown["rate_lv2"] == 45
    assert hero.score_breakdown["counter_debt"] == 20


def test_no_battle_suppresses_primary_villain_and_keeps_trace():
    delta = _delta(VIX_curr=14.0, SPY_pct=0.6)

    result = resolve_character_selection(
        delta=delta,
        event_type="NORMAL",
        scenario_type="NO_BATTLE",
        risk_level="LOW",
        base_hero_id="CHAR_HERO_001",
        base_villain_id="CHAR_VILLAIN_005",
    )

    assert result.primary_villain is None
    assert result.primary_hero == "CHAR_HERO_001"
    assert "villain suppressed" in result.selection_reason


def test_alliance_adds_support_hero_from_scores():
    delta = _delta(VIX_curr=36.0, VIX_pct=25.0, SPY_pct=-2.5, NASDAQ_pct=-2.2)

    result = resolve_character_selection(
        delta=delta,
        event_type="SHOCK",
        scenario_type="ALLIANCE",
        risk_level="HIGH",
        base_hero_id="CHAR_HERO_001",
        base_villain_id="CHAR_VILLAIN_004",
        arc_context={"tension": 80},
    )

    assert result.primary_villain == "CHAR_VILLAIN_004"
    assert result.primary_hero in {"CHAR_HERO_001", "CHAR_HERO_004"}
    assert len(result.support_heroes) == 1
    assert result.support_heroes[0] != result.primary_hero


def test_neutral_guests_score_arbitrator_and_double_agent():
    delta = _delta(DGS10_curr=5.0, DGS10_pct=6.0, BTC_pct=6.0)
    guests = score_neutral_guests(
        delta,
        {
            "us10y": 5.0,
            "yield_curve": -0.7,
            "crypto_basis_state": "Premium",
            "btc_sentiment_state": "Bullish",
            "crypto_basis_spread": 1.5,
            "btc_social_sentiment": 80,
        },
    )

    roles = {g.char_id: g.role for g in guests}
    assert roles["SENTINEL_YIELD"] == "ARBITRATOR"
    assert roles["CRYPTO_SHADE"] == "DOUBLE_AGENT"
    assert all(g.appear for g in guests)


def test_multi_villain_flag_adds_support_villain(monkeypatch):
    monkeypatch.setenv("MULTI_VILLAIN_ENABLED", "true")
    monkeypatch.setenv("MULTI_VILLAIN_MAX", "2")
    delta = _delta(
        WTI_curr=96.0,
        WTI_pct=8.2,
        VIX_curr=36.0,
        VIX_pct=25.0,
        SPY_pct=-2.5,
        NASDAQ_pct=-2.2,
    )

    result = resolve_character_selection(
        delta=delta,
        event_type="BATTLE",
        scenario_type="ALLIANCE",
        risk_level="HIGH",
        base_hero_id="CHAR_HERO_001",
        base_villain_id="CHAR_VILLAIN_004",
        arc_context={"tension": 80},
    )

    assert len(result.villains) == 2
    assert result.primary_villain in result.villains
    assert result.support_villains
    assert result.villain_roles[result.primary_villain] == "PRIMARY_THREAT"
    assert result.villain_roles[result.support_villains[0]] == "SECONDARY_THREAT"
    assert result.to_dict()["villains"] == result.villains
