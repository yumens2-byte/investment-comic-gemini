from scripts.run_publish import MAJOR_EVENT_TYPES, is_major_event, validate_major_event_types


def test_is_major_event_basic():
    assert is_major_event("BATTLE") is True
    assert is_major_event("battle_plus") is True
    assert is_major_event("NORMAL") is False


def test_major_event_types_are_supported_and_complete():
    unknown, missing = validate_major_event_types()
    assert unknown == set()
    assert missing == set()


def test_major_event_set_expected_core_types():
    expected = {
        "BATTLE",
        "SHOCK",
        "AFTERMATH",
        "BATTLE_PLUS",
        "BATTLE_PLUS_FORM2",
        "BATTLE_PLUS_FORM3",
        "EMERGENCE",
        "SEASON_FINALE",
    }
    assert expected.issubset(MAJOR_EVENT_TYPES)
