"""Side canon rules (EDT ACT2 New Network canon, Phase-1 = NW-E01 latent stage).

Sources (ACT2 project docs):
  02 v2.29 SECTION 7 / RULE NW-03  — event order fixed, node first appearance needs master approval
  05 v2.19 RULE NW-N-01 / NW-N-05  — expression ceiling per stage, nodes = silhouette only w/o REF
  05 v2.19 PATCH-B                 — S1: Zero Block appears in side stories only
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from sidestory.core.models import OutcomeClass

# Exact string required by main X publisher (engine/publish/x_publisher.py:28).
DISCLAIMER = "본 콘텐츠는 투자 참고 정보이며, 투자 권유가 아닙니다"

NN_STAGES = ("E00", "E01", "E02", "E03", "E04", "E05", "E06")

# Data vendor names must never appear in published copy (ACT2 PP-08 equivalent).
VENDOR_TERMS = (
    "FRED",
    "yfinance",
    "Yahoo",
    "Bloomberg",
    "Alpha Vantage",
    "FMP",
    "LunarCrush",
    "CL=F",
    "^VIX",
    "^IXIC",
    "DGS10",
    "DGS30",
    "BAMLH0A0HYM2",
    "DCOILWTICO",
)

NODE_NAMES = ("Null Trader", "Phantom Relay", "Void Anchor")


@dataclass(frozen=True)
class StageAllowance:
    zero_block_dialogue: bool
    node_names_allowed: bool
    faction_declaration_allowed: bool
    node_visual: str  # "none" | "silhouette" | "full"


_ALLOWANCE = {
    "E00": StageAllowance(False, False, False, "none"),
    "E01": StageAllowance(True, False, False, "silhouette"),
    "E02": StageAllowance(True, False, False, "silhouette"),
    "E03": StageAllowance(True, False, False, "silhouette"),
    "E04": StageAllowance(True, False, False, "silhouette"),
    "E05": StageAllowance(True, True, True, "silhouette"),
    "E06": StageAllowance(True, True, True, "silhouette"),
}

# Faction self-declaration is reserved for NW-E05 ("우리는 New Network다").
_FACTION_DECLARATION = re.compile(r"(우리는|we are)\s*(the\s*)?new\s*network", re.IGNORECASE)


def allowance(stage: str) -> StageAllowance:
    if stage not in _ALLOWANCE:
        raise ValueError(f"unknown nn_stage: {stage!r}")
    return _ALLOWANCE[stage]


# Side reaction beat per main outcome class (master: follow the main system's classes).
REACTION_BEATS: dict[OutcomeClass, str] = {
    OutcomeClass.VICTORY: (
        "본편 승리 직후의 잔해를 관찰한다. 물러난 빌런이 남긴 붕괴 데이터가 "
        "어딘가로 흘러가고, Zero Block은 그 흐름을 기록한다."
    ),
    OutcomeClass.DRAW: (
        "본편이 승부를 내지 못한 균형의 틈을 관찰한다. 양측 어느 쪽도 회수하지 못한 "
        "데이터가 공중에 떠 있다."
    ),
    OutcomeClass.DEFEAT: (
        "본편 패배로 시스템 균열이 커진 순간을 관찰한다. 붕괴 데이터가 급증하지만 "
        "Zero Block은 개입하지 않고 기록만 한다."
    ),
    OutcomeClass.NO_BATTLE: (
        "전투가 없는 날의 시장을 관찰한다. 조용한 데이터 흐름 속에서 다음 균열의 "
        "징후를 찾는다."
    ),
}


def find_vendor_terms(text: str) -> list[str]:
    lowered = text.lower()
    return [term for term in VENDOR_TERMS if term.lower() in lowered]


def find_stage_violations(text: str, stage: str) -> list[str]:
    rules = allowance(stage)
    violations: list[str] = []
    if not rules.node_names_allowed:
        violations += [f"node name before E05: {name}" for name in NODE_NAMES if name in text]
    if not rules.faction_declaration_allowed and _FACTION_DECLARATION.search(text):
        violations.append("New Network faction declaration before E05")
    return violations
