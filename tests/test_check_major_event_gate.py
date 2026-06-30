from scripts.check_major_event_gate import decide_major_gate, should_run_expensive


def test_should_run_expensive_major():
    assert should_run_expensive("BATTLE") is True
    assert should_run_expensive("battle_plus_form2") is True


def test_should_run_expensive_non_major():
    assert should_run_expensive("NORMAL") is False
    assert should_run_expensive("INTEL") is False


def test_decide_major_gate_uses_regime_first():
    decision = decide_major_gate("BATTLE", "FLASHBACK")

    assert decision.should_run_expensive is True
    assert decision.gate_source == "regime"
    assert decision.regime == "BATTLE"
    assert decision.episode_type_v3 == "FLASHBACK"


def test_decide_major_gate_uses_episode_type_v3_when_legacy_regime_is_non_major():
    decision = decide_major_gate("INTEL", "BATTLE_PLUS")

    assert decision.should_run_expensive is True
    assert decision.gate_source == "episode_type_v3"


def test_decide_major_gate_skips_when_both_signals_are_non_major():
    decision = decide_major_gate("INTEL", "FLASHBACK")

    assert decision.should_run_expensive is False
    assert decision.gate_source == "none"
