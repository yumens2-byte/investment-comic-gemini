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


# v8.10 (pilot 2: "본편의 결과는 OBSERVATION"): readers see Korean names only.
OUTCOME_LABEL_KO: dict[str, str] = {
    "HERO_VICTORY": "히어로 승리",
    "HERO_TACTICAL_VICTORY": "히어로 전술적 승리",
    "PYRRHIC_VICTORY": "상처뿐인 승리",
    "DRAW": "무승부",
    "VILLAIN_TEMP_VICTORY": "빌런의 일시적 우세",
    "HERO_DEFEAT": "히어로 패배",
    "SYSTEM_COLLAPSE": "시스템 붕괴",
    "OBSERVATION": "관측(전투 없음)",
    "PEACEFUL_GROWTH": "평온한 성장(전투 없음)",
}
CLASS_LABEL_KO: dict[OutcomeClass, str] = {
    OutcomeClass.VICTORY: "승리",
    OutcomeClass.DRAW: "무승부",
    OutcomeClass.DEFEAT: "패배",
    OutcomeClass.NO_BATTLE: "전투 없음",
}
# Mirror of main scenario_selector.ScenarioType (2026-10-05).
SCENARIO_LABEL_KO: dict[str, str] = {
    "ONE_VS_ONE": "1대1 대결",
    "ALLIANCE": "연합 대결",
    "NO_BATTLE": "전투 없음",
}
# Internal codes that must never reach reader-facing text.
INTERNAL_CODES: frozenset[str] = (MAIN_OUTCOMES | {c.value for c in OutcomeClass}
                                  | frozenset(SCENARIO_LABEL_KO))


def scenario_label_ko(scenario: str | None) -> str | None:
    if not scenario:
        return None
    key = scenario.strip().upper()
    return SCENARIO_LABEL_KO.get(key, key)


def outcome_label_ko(outcome: str | None) -> str | None:
    if not outcome:
        return None
    return OUTCOME_LABEL_KO.get(outcome.strip().upper())


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
