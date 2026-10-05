"""Map main battle outcomes to side reaction classes.

The outcome vocabulary is owned by the main track (engine/narrative/battle_calc.py
``Outcome`` Literal). The side track only classifies it. A drift test
(sidestory/tests/test_outcome.py) fails if the main vocabulary changes.
"""
from __future__ import annotations

from sidestory.core.models import OutcomeClass

# Mirror of main battle_calc.Outcome (2026-10-05). Update together with the drift test.
MAIN_OUTCOMES: frozenset[str] = frozenset(
    {
        "HERO_VICTORY",
        "HERO_TACTICAL_VICTORY",
        "DRAW",
        "VILLAIN_TEMP_VICTORY",
        "HERO_DEFEAT",
        "SYSTEM_COLLAPSE",
        "PEACEFUL_GROWTH",
        "OBSERVATION",
        "PYRRHIC_VICTORY",
    }
)

_OUTCOME_TO_CLASS: dict[str, OutcomeClass] = {
    "HERO_VICTORY": OutcomeClass.VICTORY,
    "HERO_TACTICAL_VICTORY": OutcomeClass.VICTORY,
    "PYRRHIC_VICTORY": OutcomeClass.VICTORY,
    "DRAW": OutcomeClass.DRAW,
    "VILLAIN_TEMP_VICTORY": OutcomeClass.DEFEAT,
    "HERO_DEFEAT": OutcomeClass.DEFEAT,
    "SYSTEM_COLLAPSE": OutcomeClass.DEFEAT,
    "OBSERVATION": OutcomeClass.NO_BATTLE,
    "PEACEFUL_GROWTH": OutcomeClass.NO_BATTLE,
}


class UnknownOutcome(ValueError):
    """Main produced an outcome the side track does not know — hold, never guess."""


def classify(outcome: str | None, scenario_type: str | None) -> OutcomeClass:
    """Classify a main episode. NO_BATTLE scenario wins regardless of stored outcome
    (main persists a legacy battle_json for NO_BATTLE runs)."""
    if (scenario_type or "").upper() == "NO_BATTLE":
        return OutcomeClass.NO_BATTLE
    key = (outcome or "").strip().upper()
    if key not in _OUTCOME_TO_CLASS:
        raise UnknownOutcome(f"unmapped main outcome: {outcome!r}")
    return _OUTCOME_TO_CLASS[key]
