"""
engine/analysis/event_classifier.py
EDT Episode Type Engine v1.1 이식.

7종 타입: BATTLE / SHOCK / AFTERMATH / INTEL / NORMAL / FLASHBACK / TACTICAL
분기 로직은 결정론적 — 외부 상태 없음.
"""

from __future__ import annotations

from typing import Literal

EpisodeType = Literal[
    "BATTLE",    # 유가 쇼크 또는 금리 급등 — 주요 빌런 등장
    "SHOCK",     # VIX 급등 — 볼래틸리티 하이드라 소환
    "AFTERMATH", # 전일 전투 직후 — 여파 처리
    "INTEL",     # 주 2일 이상 조용할 때 — 정보 수집
    "NORMAL",    # 일반 시장 상황
    "FLASHBACK", # 과거 전투 회상 (수동 트리거)
    "TACTICAL",  # 중간 강도 긴장 — 전술 전투
]

# 타입 → Notion Tracker 표기 매핑
NOTION_EVENT_TYPE_MAP: dict[str, str] = {
    "BATTLE": "BATTLE",
    "SHOCK": "SHOCK",
    "AFTERMATH": "AFTERMATH",
    "INTEL": "INTEL",
    "NORMAL": "NORMAL",
    "FLASHBACK": "FLASHBACK",
    "TACTICAL": "TACTICAL",
}


def classify(delta: dict, arc: dict) -> EpisodeType:
    """
    시장 delta + 에피소드 arc 기반 에피소드 타입 결정.

    Args:
        delta: 시장 지표 전일 대비 변화.
            구조 예시:
            {
                "VIX":   {"prev": 18.2, "curr": 24.1, "pct": 32.4},
                "WTI":   {"prev": 82.1, "curr": 88.5, "pct":  7.8},
                "DGS10": {"prev":  4.5, "curr":  4.9, "pct":  8.9},
                "SPY":   {"prev": 510.0, "curr": 495.0, "pct": -2.9},
            }
        arc: 에피소드 연속성 정보.
            {
                "yesterday_type": "BATTLE",
                "tension": 45,
                "days_since_last": 0,  # 마지막 전투 이후 일수
            }

    Returns:
        EpisodeType 문자열.

    분기 우선순위 (순서 보장):
    1. WTI 3일 변화율 >= 5% → BATTLE (Oil Shock Titan)
    2. VIX > 28 AND VIX 전일 대비 > 20% → SHOCK
    3. DGS10 현재값 > 4.8% → BATTLE (Debt Titan)
    4. SPY 일간 -3% 이하 → BATTLE (Algorithm Reaper 연계 가능)
    5. 전일 BATTLE + tension > 40 → AFTERMATH
    6. days_since_last >= 2 (조용한 시장) → INTEL
    7. 기타 → NORMAL
    """
    wti_pct = delta.get("WTI", {}).get("pct", 0.0)
    vix_curr = delta.get("VIX", {}).get("curr", 0.0)
    vix_pct = delta.get("VIX", {}).get("pct", 0.0)
    dgs10_curr = delta.get("DGS10", {}).get("curr", 0.0)
    spy_pct = delta.get("SPY", {}).get("pct", 0.0)

    yesterday_type = arc.get("yesterday_type", "")
    tension = arc.get("tension", 0)
    days_since_last = arc.get("days_since_last", 0)

    # 1. 유가 쇼크 — Oil Shock Titan 소환
    if wti_pct >= 5.0:
        return "BATTLE"

    # 2. VIX 급등 — Volatility Hydra 소환
    if vix_curr > 28 and vix_pct > 20:
        return "SHOCK"

    # 3. 금리 급등 — Debt Titan 소환
    if dgs10_curr > 4.8:
        return "BATTLE"

    # 4. 지수 급락 — Algorithm Reaper 연계
    if spy_pct <= -3.0:
        return "BATTLE"

    # 5. 전일 전투 여파
    if yesterday_type == "BATTLE" and tension > 40:
        return "AFTERMATH"

    # 6. 조용한 시장 — 정보 수집 국면
    if days_since_last >= 2:
        return "INTEL"

    return "NORMAL"


def get_market_context_for_battle(delta: dict, snapshot: dict) -> dict:
    """
    battle_calc에 전달할 market_context 딕셔너리 조립.

    Args:
        delta: classify()에 사용한 동일 delta.
        snapshot: icg.daily_snapshots 최신 row.

    Returns:
        market_context dict (battle_calc.battle() 입력용).
    """
    wti_pct = delta.get("WTI", {}).get("pct", 0.0)

    return {
        "oil_shock": wti_pct >= 5.0,
        "vix": snapshot.get("vix", 0.0),
        "wti_pct_3d": wti_pct,
        "dgs10": snapshot.get("us10y", 0.0),
        "hy_spread": snapshot.get("hy_spread", 0.0),
        "system_stress": (
            snapshot.get("vix", 0) > 35
            and snapshot.get("hy_spread", 0) > 700
        ),
    }
