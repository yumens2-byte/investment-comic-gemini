"""Side-track domain models."""
from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class OutcomeClass(str, Enum):
    """Main-episode result class the side story reacts to (follows main battle_calc)."""

    VICTORY = "VICTORY"
    DRAW = "DRAW"
    DEFEAT = "DEFEAT"
    NO_BATTLE = "NO_BATTLE"


class MainEpisodeRow(BaseModel):
    """One row of icg_side.main_feed_episode_v1 (published main episodes only)."""

    episode_date: str
    episode_no: int = 1
    event_type: str | None = None
    scenario_type: str | None = None
    heroes_json: list[Any] = Field(default_factory=list)
    battle_json: dict[str, Any] = Field(default_factory=dict)
    script_json: dict[str, Any] = Field(default_factory=dict)

    @property
    def main_episode_id(self) -> str:
        return f"ICG-{self.episode_date}-{self.episode_no:03d}"


class MarketRow(BaseModel):
    """One row of icg_side.main_feed_market_v1."""

    snapshot_date: str
    us10y: float | None = None
    vix: float | None = None
    oil_wti: float | None = None
    spy_change: float | None = None
    nasdaq_change: float | None = None
    dollar_index: float | None = None
    hy_spread: float | None = None
    fear_greed: float | None = None


class ArcRow(BaseModel):
    """Single row of icg_side.main_feed_arc_v1."""

    arc_day: int | None = None
    arc_tension: int | None = None
    hero_momentum: int | None = None
    active_villain: str | None = None
    last_outcome: str | None = None
    last_episode_date: str | None = None


class EchoPack(BaseModel):
    """Main→side echo input (L-A). Values are copied verbatim from main; never altered."""

    version: str = "echo-1"
    side_date: str
    main_episode_id: str
    main_date: str
    title: str
    logline: str
    event_type: str | None
    scenario_type: str | None
    outcome: str | None
    outcome_class: OutcomeClass
    villain_id: str | None
    hero_ids: list[str]
    next_hook: str
    main_threads: list[str]
    market: dict[str, float | None]
    arc: dict[str, Any]


class GateResult(BaseModel):
    gate: str
    passed: bool
    reason: str = ""
    skip: bool = False  # True = stop the run as a normal no-op (e.g. no anchor)
