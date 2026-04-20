from engine.narrative.storyline_guard import choose_scenario_with_diversity


def test_keep_base_when_streak_is_short():
    scenario, reason = choose_scenario_with_diversity(
        base_scenario="ONE_VS_ONE",
        risk_level="MEDIUM",
        event_type="BATTLE",
        recent_scenarios=["ALLIANCE", "ONE_VS_ONE"],
        max_same_streak=2,
    )
    assert scenario == "ONE_VS_ONE"
    assert "keep_base" in reason


def test_rotate_high_risk_crisis_to_alliance_when_one_vs_one_repeats():
    scenario, reason = choose_scenario_with_diversity(
        base_scenario="ONE_VS_ONE",
        risk_level="HIGH",
        event_type="SHOCK",
        recent_scenarios=["ONE_VS_ONE", "ONE_VS_ONE", "ONE_VS_ONE"],
        max_same_streak=2,
    )
    assert scenario == "ALLIANCE"
    assert "rotated_for_diversity" in reason


def test_rotate_low_risk_calm_to_no_battle_when_one_vs_one_repeats():
    scenario, reason = choose_scenario_with_diversity(
        base_scenario="ONE_VS_ONE",
        risk_level="LOW",
        event_type="NORMAL",
        recent_scenarios=["ONE_VS_ONE", "ONE_VS_ONE"],
        max_same_streak=2,
    )
    assert scenario == "NO_BATTLE"
    assert "rotated_for_diversity" in reason


def test_keep_when_no_alternative_allowed():
    scenario, reason = choose_scenario_with_diversity(
        base_scenario="ONE_VS_ONE",
        risk_level="MEDIUM",
        event_type="TACTICAL",
        recent_scenarios=["ONE_VS_ONE", "ONE_VS_ONE", "ONE_VS_ONE"],
        max_same_streak=2,
    )
    assert scenario == "ONE_VS_ONE"
    assert "no_alternative_allowed" in reason
