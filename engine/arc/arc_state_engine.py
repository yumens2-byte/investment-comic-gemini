"""
engine/arc/arc_state_engine.py
ICG Arc State 로드 / 저장 / 갱신 엔진

설계 기반:
    - EDT ARC_STATE_SCHEMA v2.1
    - ICG 독자 세계관 (dimensional_rift_progress) 보존
    - Supabase icg.arc_state 단일 행 관리 (id=1)

배포 위치: engine/arc/arc_state_engine.py
Feature Flag: ARC_STATE_V3_ENABLED (env)

VERSION: 1.0.0
DATE: 2026-05-02
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any

VERSION = "1.0.0"

logger = logging.getLogger(__name__)

# ── 상수 ────────────────────────────────────────────────────────────────────

# arc_tension 변화량 (EDT 04 v2.3 기준)
_TENSION_DELTA: dict[str, int] = {
    "HERO_VICTORY":          -5,
    "PYRRHIC_VICTORY":       -3,
    "DRAW":                   0,
    "VILLAIN_TEMP_VICTORY":  +5,
    "HERO_DEFEAT":           +7,
    "SYSTEM_COLLAPSE":       +12,
    "PEACEFUL_GROWTH":       -3,
}

# dimensional_rift 변화량 (ICG 독자 세계관)
_RIFT_DELTA_HIGH_VIX  = 10   # vix >= 35
_RIFT_DELTA_LOW_VIX   = -2   # vix < 25

# villain_signature 임계값 (EDT 02 v2.19 / 21_MARKET_THRESHOLD_MATRIX)
_VILLAIN_SIG_RULES: dict[str, dict] = {
    "CHAR_VILLAIN_001": {  # Debt Titan
        "lv2_condition": lambda snap: (snap.get("us10y") or 0) >= 5.0,
        "lv3_condition": lambda snap: (snap.get("us10y") or 0) >= 5.5,
    },
    "CHAR_VILLAIN_002": {  # Oil Shock Titan
        "lv2_condition": lambda snap: (snap.get("oil_wti") or 0) >= 90.0,
        "lv3_condition": lambda snap: (snap.get("oil_wti") or 0) >= 110.0,
    },
    "CHAR_VILLAIN_003": {  # Liquidity Leviathan
        "lv2_condition": lambda snap: (snap.get("hy_spread") or 0) >= 400.0,
        "lv3_condition": lambda snap: (snap.get("hy_spread") or 0) >= 500.0,
    },
    "CHAR_VILLAIN_004": {  # Volatility Hydra
        "lv2_condition": lambda snap: (snap.get("vix") or 0) >= 30.0,
        "lv3_condition": lambda snap: (snap.get("vix") or 0) >= 40.0,
    },
    "CHAR_VILLAIN_005": {  # Algorithm Reaper
        "lv2_condition": lambda snap: (snap.get("vix") or 0) >= 28.0,
        "lv3_condition": lambda snap: (snap.get("vix") or 0) >= 35.0,
    },
    "CHAR_VILLAIN_006": {  # War Dominion
        "lv2_condition": lambda snap: (snap.get("oil_wti") or 0) >= 95.0,
        "lv3_condition": lambda snap: (snap.get("oil_wti") or 0) >= 115.0,
    },
}

# crowd_momentum 계산 (F&G 기준, EDT 04 v2.12)
_CROWD_F_G_MAP = [
    (0,  10, -20),   # Extreme Fear
    (11, 25, -12),   # Fear
    (26, 45,  -5),   # Mild Fear
    (46, 55,   0),   # Neutral
    (56, 74,  +5),   # Mild Greed
    (75, 89, +12),   # Greed
    (90, 100, +20),  # Extreme Greed
]


# ── 로드 / 저장 ──────────────────────────────────────────────────────────────

def load_arc_state() -> dict[str, Any]:
    """
    Supabase icg.arc_state (id=1) 에서 현재 아크 상태 로드.

    Returns:
        arc_state dict. DB 장애 시 기본값 반환.
    """
    try:
        from engine.common.supabase_client import icg_table

        resp = icg_table("arc_state").select("*").eq("id", 1).limit(1).execute()
        if resp.data:
            state = dict(resp.data[0])
            logger.info(
                "[ArcStateEngine v%s] 로드 완료 "
                "(villain=%s arc_day=%d tension=%d sig=%d)",
                VERSION,
                state.get("active_villain"),
                state.get("arc_day", 0),
                state.get("arc_tension", 30),
                state.get("villain_signature", 1),
            )
            return state

        logger.warning("[ArcStateEngine] arc_state 행 없음 → 기본값 반환")
        return _default_arc_state()

    except Exception as exc:
        logger.error("[ArcStateEngine] 로드 실패: %s → 기본값 반환", exc)
        return _default_arc_state()


def save_arc_state(state: dict[str, Any]) -> bool:
    """
    Supabase icg.arc_state (id=1) upsert 저장.

    Args:
        state: 갱신할 arc_state dict.

    Returns:
        True if 성공.
    """
    try:
        from engine.common.supabase_client import icg_table

        state["updated_at"] = datetime.now(tz=timezone.utc).isoformat()
        state["id"] = 1  # 단일 행 보장

        icg_table("arc_state").upsert(state, on_conflict="id").execute()
        logger.info(
            "[ArcStateEngine] 저장 완료 "
            "(villain=%s arc_day=%d tension=%d)",
            state.get("active_villain"),
            state.get("arc_day", 0),
            state.get("arc_tension", 30),
        )
        return True

    except Exception as exc:
        logger.error("[ArcStateEngine] 저장 실패: %s", exc)
        return False


def snapshot_to_daily_analysis(
    episode_date: str,
    state: dict[str, Any],
    episode_type_v3: str | None = None,
) -> bool:
    """
    현재 arc_state를 icg.daily_analysis 스냅샷 컬럼에 저장.

    Args:
        episode_date: YYYY-MM-DD
        state: 현재 arc_state
        episode_type_v3: 결정된 에피소드 타입 (None = v2.0 레코드)

    Returns:
        True if 성공.
    """
    try:
        from engine.common.supabase_client import icg_table

        payload: dict[str, Any] = {
            "arc_day":           state.get("arc_day"),
            "arc_tension":       state.get("arc_tension"),
            "hero_momentum":     state.get("hero_momentum"),
            "villain_signature": state.get("villain_signature"),
            "crowd_momentum":    state.get("crowd_momentum"),
            "active_villain":    state.get("active_villain"),
        }
        if episode_type_v3:
            payload["episode_type_v3"] = episode_type_v3

        icg_table("daily_analysis").update(payload).eq(
            "analysis_date", episode_date
        ).execute()

        logger.info("[ArcStateEngine] daily_analysis 스냅샷 저장 완료 (%s)", episode_date)
        return True

    except Exception as exc:
        logger.warning("[ArcStateEngine] daily_analysis 스냅샷 실패: %s", exc)
        return False


# ── 갱신 로직 ────────────────────────────────────────────────────────────────

def update_after_episode(
    state: dict[str, Any],
    outcome: str,
    episode_type: str,
    snapshot: dict[str, Any],
    new_villain: str | None = None,
    open_hook: str | None = None,
) -> dict[str, Any]:
    """
    에피소드 완료 후 arc_state 갱신.

    EDT ARC_STATE_SCHEMA v2.1 기준:
        - arc_day += 1 (villain 전환 시 1 리셋)
        - arc_tension: outcome별 자동 조정
        - hero_momentum: 최근 승패 기반 재계산
        - villain_signature: 시장 스냅샷 기반 자동 판정
        - crowd_momentum: F&G 기반 자동 계산
        - dimensional_rift_progress: ICG 독자 세계관 유지

    Args:
        state:        현재 arc_state (load_arc_state() 결과)
        outcome:      battle_result.outcome (HERO_VICTORY 등)
        episode_type: 에피소드 타입 (BATTLE, ALLIANCE 등)
        snapshot:     오늘 daily_snapshots 행 (시장 데이터)
        new_villain:  새 빌런 ID (None = 빌런 유지)
        open_hook:    이번 에피소드 Next Hook 텍스트

    Returns:
        갱신된 arc_state dict (저장 전)
    """
    import copy
    s = copy.deepcopy(state)

    # ── 빌런 전환 감지 (EMERGENCE 리셋) ─────────────────────────────────────
    villain_changed = (
        new_villain is not None
        and new_villain != s.get("active_villain")
    )
    if villain_changed:
        logger.info(
            "[ArcStateEngine] 빌런 전환: %s → %s (arc_day 리셋)",
            s.get("active_villain"), new_villain,
        )
        s["active_villain"]    = new_villain
        s["arc_day"]           = 1
        s["villain_streak"]    = 1
        s["villain_signature"] = 1
    else:
        s["arc_day"]        = (s.get("arc_day") or 0) + 1
        s["villain_streak"] = (s.get("villain_streak") or 0) + 1

    # ── arc_tension 자동 조정 ────────────────────────────────────────────────
    tension = s.get("arc_tension") or 30
    delta_t = _TENSION_DELTA.get(outcome, 0)
    s["arc_tension"] = max(0, min(100, tension + delta_t))

    # ── hero_momentum 재계산 ─────────────────────────────────────────────────
    # 간단 모델: 승리 +8 / 무승부 0 / 패배 -8 (EDT 기준 근사)
    momentum = s.get("hero_momentum") or 50
    if outcome in ("HERO_VICTORY", "PEACEFUL_GROWTH"):
        s["hero_momentum"] = min(100, momentum + 8)
        s["hero_win_streak"] = (s.get("hero_win_streak") or 0) + 1
    elif outcome == "PYRRHIC_VICTORY":
        s["hero_momentum"] = min(100, momentum + 3)
        s["hero_win_streak"] = 0
    elif outcome in ("HERO_DEFEAT", "SYSTEM_COLLAPSE"):
        s["hero_momentum"] = max(0, momentum - 8)
        s["hero_win_streak"] = 0
    else:
        s["hero_win_streak"] = 0

    # ── villain_signature 자동 판정 ──────────────────────────────────────────
    villain_id = s.get("active_villain", "")
    s["villain_signature"] = _calc_villain_signature(villain_id, snapshot)

    # ── crowd_momentum 자동 계산 (F&G 기준) ──────────────────────────────────
    fg = snapshot.get("fear_greed")
    if fg is not None:
        s["crowd_momentum"] = _calc_crowd_momentum(int(fg))
    # else: 전날 값 유지

    # ── dimensional_rift_progress 갱신 (ICG 독자 세계관) ────────────────────
    vix = float(snapshot.get("vix") or 0)
    rift = s.get("dimensional_rift_progress") or 0
    if vix >= 35:
        rift = min(100, rift + _RIFT_DELTA_HIGH_VIX)
    elif vix < 25:
        rift = max(0, rift + _RIFT_DELTA_LOW_VIX)
    s["dimensional_rift_progress"] = rift
    s["volatility_fields_active"]  = vix >= 30

    # ── Season Progress ──────────────────────────────────────────────────────
    s["season_arc_days"] = (s.get("season_arc_days") or 0) + 1

    # ── Form 상태 ─────────────────────────────────────────────────────────────
    # Form 2: 4-AND (arc_tension >= 75 / arc_day >= 5 / VICTORY / ...)
    # arc_state 저장 시 form2_available은 check_form2()에서 별도 판정.
    # 여기서는 Form 3 활성화 여부만 기록 (일회성 시즌 플래그)
    if outcome == "SYSTEM_LEVEL_VICTORY":
        s["form3_activated"] = True

    # ── 메타 ─────────────────────────────────────────────────────────────────
    s["last_outcome"]      = outcome
    s["last_episode_type"] = episode_type
    s["last_episode_date"] = datetime.now(tz=timezone.utc).date().isoformat()
    if open_hook:
        s["open_hook"] = open_hook

    logger.info(
        "[ArcStateEngine] 갱신 완료 — "
        "arc_day=%d tension=%d momentum=%d sig=%d crowd=%d rift=%d%%",
        s.get("arc_day", 0),
        s.get("arc_tension", 30),
        s.get("hero_momentum", 50),
        s.get("villain_signature", 1),
        s.get("crowd_momentum", 0),
        s.get("dimensional_rift_progress", 0),
    )
    return s


def build_arc_context(state: dict[str, Any]) -> dict[str, Any]:
    """
    run_market.py STEP 3의 arc_context 빌드.
    기존 하드코딩 {"tension": 40, ...} 대체.

    Returns:
        battle_calc.py / narrative에 전달되는 arc_context dict.
    """
    return {
        # EDT 기존 키 유지 (battle_calc.py 호환)
        "tension":           state.get("arc_tension", 30),
        "days_since_last":   state.get("arc_day", 0),
        "yesterday_type":    state.get("last_episode_type", "ONE_VS_ONE"),
        # 확장 필드
        "hero_momentum":     state.get("hero_momentum", 50),
        "villain_signature": state.get("villain_signature", 1),
        "crowd_momentum":    state.get("crowd_momentum", 0),
        "villain_streak":    state.get("villain_streak", 0),
        "hero_win_streak":   state.get("hero_win_streak", 0),
        "last_outcome":      state.get("last_outcome", "DRAW"),
        "open_hook":         state.get("open_hook"),
        "dimensional_rift":  state.get("dimensional_rift_progress", 0),
        "form2_available":   state.get("form2_available", False),
        "form3_activated":   state.get("form3_activated", False),
    }


# ── Form 판정 헬퍼 ────────────────────────────────────────────────────────────

def check_form2(state: dict[str, Any], balance: int, is_edt_hero: bool) -> bool:
    """
    Form 2 트리거 4-AND 조건 판정.
    EDT 04 v2.5 기준.

    Args:
        state:       현재 arc_state
        balance:     이번 에피소드 battle balance
        is_edt_hero: 주 히어로가 EDT(Form 0/1/2) 계열인지

    Returns:
        True if Form 2 발동 가능.
    """
    return (
        (state.get("arc_tension") or 0) >= 75
        and (state.get("arc_day") or 0) >= 5
        and is_edt_hero
        and balance >= 20
        and not (state.get("form3_activated") or False)
    )


def check_form3(state: dict[str, Any], balance: int, is_edt_hero: bool) -> bool:
    """
    Form 3 트리거 5-AND 조건 판정.
    EDT 04 v2.5 기준 (시즌 1회).

    Args:
        state:   현재 arc_state
        balance: 이번 에피소드 battle balance
        is_edt_hero: EDT 계열 히어로 여부

    Returns:
        True if Form 3 발동 가능.
    """
    return (
        (state.get("arc_tension") or 0) >= 95
        and (state.get("arc_day") or 0) >= 14
        and is_edt_hero
        and balance >= 50
        and (state.get("form2_available") or False)
        and not (state.get("form3_activated") or False)
    )


# ── 내부 헬퍼 ────────────────────────────────────────────────────────────────

def _calc_villain_signature(villain_id: str, snapshot: dict) -> int:
    """villain_id + 시장 스냅샷 → Lv.1/2/3 판정."""
    rules = _VILLAIN_SIG_RULES.get(villain_id)
    if not rules:
        return 1
    try:
        if rules["lv3_condition"](snapshot):
            return 3
        if rules["lv2_condition"](snapshot):
            return 2
        return 1
    except Exception:
        return 1


def _calc_crowd_momentum(fear_greed: int) -> int:
    """F&G 0~100 → crowd_momentum -20~+20."""
    for lo, hi, cm in _CROWD_F_G_MAP:
        if lo <= fear_greed <= hi:
            return cm
    return 0


def _default_arc_state() -> dict[str, Any]:
    """기본 arc_state (DB 없을 때 폴백)."""
    return {
        "id": 1,
        "active_villain":           "CHAR_VILLAIN_004",
        "arc_day":                  0,
        "arc_tension":              30,
        "hero_momentum":            50,
        "villain_signature":        1,
        "crowd_momentum":           0,
        "villain_streak":           0,
        "last_outcome":             "DRAW",
        "last_episode_type":        "ONE_VS_ONE",
        "last_episode_date":        None,
        "hero_win_streak":          0,
        "form2_available":          False,
        "form3_activated":          False,
        "season_arc_days":          0,
        "defeated_villains":        0,
        "dimensional_rift_progress": 0,
        "volatility_fields_active": False,
        "open_hook":                None,
    }


# ── Feature Flag 가드 ─────────────────────────────────────────────────────────

def is_enabled() -> bool:
    """ARC_STATE_V3_ENABLED 환경변수 확인."""
    return os.environ.get("ARC_STATE_V3_ENABLED", "false").lower() == "true"
