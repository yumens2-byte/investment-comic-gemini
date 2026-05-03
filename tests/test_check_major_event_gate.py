from scripts.check_major_event_gate import should_run_expensive


def test_should_run_expensive_major():
    assert should_run_expensive("BATTLE") is True
    assert should_run_expensive("battle_plus_form2") is True


def test_should_run_expensive_non_major():
    assert should_run_expensive("NORMAL") is False
    assert should_run_expensive("INTEL") is False
