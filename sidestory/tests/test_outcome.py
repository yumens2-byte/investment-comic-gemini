from __future__ import annotations

import ast

import pytest

from sidestory.core.models import OutcomeClass
from sidestory.core.outcome import MAIN_OUTCOMES, UnknownOutcome, classify
from sidestory.tests.conftest import REPO_ROOT


@pytest.mark.parametrize(
    ("outcome", "expected"),
    [
        ("HERO_VICTORY", OutcomeClass.VICTORY),
        ("HERO_TACTICAL_VICTORY", OutcomeClass.VICTORY),
        ("PYRRHIC_VICTORY", OutcomeClass.VICTORY),
        ("DRAW", OutcomeClass.DRAW),
        ("VILLAIN_TEMP_VICTORY", OutcomeClass.DEFEAT),
        ("HERO_DEFEAT", OutcomeClass.DEFEAT),
        ("SYSTEM_COLLAPSE", OutcomeClass.DEFEAT),
        ("OBSERVATION", OutcomeClass.NO_BATTLE),
        ("PEACEFUL_GROWTH", OutcomeClass.NO_BATTLE),
    ],
)
def test_outcome_classes(outcome: str, expected: OutcomeClass) -> None:
    assert classify(outcome, "ONE_VS_ONE") is expected


def test_no_battle_scenario_overrides_legacy_outcome() -> None:
    # main persists a legacy battle_json for NO_BATTLE runs
    assert classify("DRAW", "NO_BATTLE") is OutcomeClass.NO_BATTLE


def test_unknown_outcome_holds() -> None:
    with pytest.raises(UnknownOutcome):
        classify("SOMETHING_NEW", "ONE_VS_ONE")


def test_drift_against_main_battle_calc() -> None:
    """ICG-coupled: fails if main adds/removes an outcome (remove after repo split)."""
    source = (REPO_ROOT / "engine/narrative/battle_calc.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    main_values: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "Outcome" for t in node.targets
        ):
            main_values = {
                elt.value
                for elt in ast.walk(node.value)
                if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
            }
    assert main_values, "Outcome Literal not found in main battle_calc"
    assert main_values - {"Literal"} == set(MAIN_OUTCOMES)
