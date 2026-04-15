"""
engine/analysis/analysis_writer.py
분석 결과를 icg.daily_analysis에 upsert.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def upsert(
    analysis_date: str,
    event_type: str,
    battle_result: dict,
    delta: dict,
    arc_context: dict,
) -> None:
    """
    분석 결과를 icg.daily_analysis에 upsert.

    Args:
        analysis_date: 'YYYY-MM-DD'
        event_type: 에피소드 타입
        battle_result: BattleResult.to_dict()
        delta: delta_engine 출력
        arc_context: 연속성 정보
    """
    from engine.common.supabase_client import upsert_analysis

    payload: dict = {
        "regime": event_type,
        "risk_level": _map_risk_level(battle_result.get("outcome", "DRAW")),
        "trading_signal": _map_signal(battle_result.get("outcome", "DRAW")),
        "regime_score": battle_result.get("balance", 0),
        "market_score": {
            "hero_power": battle_result.get("hero_power", 0),
            "villain_power": battle_result.get("villain_power", 0),
            "balance": battle_result.get("balance", 0),
            "outcome": battle_result.get("outcome", "DRAW"),
        },
        "etf_rank": {},
        "etf_allocation": {},
        "buy_watch": [],
        "reduce_list": [],
    }

    upsert_analysis(analysis_date, payload)
    logger.info(
        "[analysis_writer] upsert date=%s regime=%s outcome=%s",
        analysis_date,
        event_type,
        battle_result.get("outcome"),
    )


def _map_risk_level(outcome: str) -> str:
    """battle outcome → 리스크 레벨 매핑."""
    return {
        "HERO_VICTORY": "LOW",
        "HERO_TACTICAL_VICTORY": "LOW",
        "DRAW": "MEDIUM",
        "VILLAIN_TEMP_VICTORY": "MEDIUM",
        "HERO_DEFEAT": "HIGH",
        "SYSTEM_COLLAPSE": "HIGH",
    }.get(outcome, "MEDIUM")


def _map_signal(outcome: str) -> str:
    """battle outcome → 트레이딩 시그널."""
    return {
        "HERO_VICTORY": "RISK_ON",
        "HERO_TACTICAL_VICTORY": "CAUTIOUS_BUY",
        "DRAW": "NEUTRAL",
        "VILLAIN_TEMP_VICTORY": "CAUTIOUS_SELL",
        "HERO_DEFEAT": "RISK_OFF",
        "SYSTEM_COLLAPSE": "DEFENSIVE",
    }.get(outcome, "NEUTRAL")
