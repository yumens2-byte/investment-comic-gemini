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
import re
from datetime import datetime, timezone
from typing import Any

VERSION = "1.0.0"

logger = logging.getLogger(__name__)

_ARC_STATE_SCHEMA_OPTIONAL_FIELDS = frozenset({
    "pair_tension",
    "edt_pressure",
    "emergence_deficit_days",
    "zero_block_just_appeared",
})

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

def _missing_schema_column_from_error(exc: Exception) -> str | None:
    """Extract a PostgREST schema-cache missing-column name from an exception."""
    text = str(exc)
    if "PGRST204" not in text and "Could not find" not in text:
        return None
    match = re.search(r"Could not find the '([^']+)' column", text)
    if not match:
        return None
    return match.group(1)


def _upsert_arc_state_schema_compatible(state: dict[str, Any]) -> list[str]:
    """Upsert arc_state, retrying without optional columns missing in DB schema."""
    from engine.common.supabase_client import icg_table

    remaining = dict(state)
    stripped: list[str] = []
    while True:
        try:
            icg_table("arc_state").upsert(remaining, on_conflict="id").execute()
            return stripped
        except Exception as exc:
            missing_column = _missing_schema_column_from_error(exc)
            if not missing_column or missing_column not in remaining:
                raise
            if missing_column not in _ARC_STATE_SCHEMA_OPTIONAL_FIELDS:
                raise
            stripped.append(missing_column)
            remaining.pop(missing_column, None)


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
        state["updated_at"] = datetime.now(tz=timezone.utc).isoformat()
        state["id"] = 1  # 단일 행 보장

        stripped = _upsert_arc_state_schema_compatible(state)
        if stripped:
            logger.warning(
                "[ArcStateEngine] arc_state DB schema missing optional columns; "
                "saved without fields=%s. Apply pending migrations.",
                stripped,
            )
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
    # ── Phase 2.3 신규 (모두 기본값 — 후방 호환) ──
    hero_ids: list[str] | None = None,
    form_triggered: int = 0,
    zero_block_appeared: bool = False,
    villain_defeated: bool = False,
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
    else:
        # F&G 부재 시: 자동 감쇠 (RULE CM-02 — G08)
        s["crowd_momentum"] = attenuate_crowd_momentum(s.get("crowd_momentum") or 0)

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

    # ── Phase 2.3: PAIR_TENSION 갱신 (Feature Flag 가드) ─────────────────────
    if is_pair_tension_enabled():
        s = update_pair_tension(
            state=s,
            outcome=outcome,
            episode_type=episode_type,
            hero_ids=hero_ids or [],
            form_triggered=form_triggered,
            zero_block_appeared=zero_block_appeared,
            villain_defeated=villain_defeated,
        )

    # ── Phase 2.3: EMERGENCE Information Deficit days 갱신 ──────────────────
    # RULE EMR-01 — Feature Flag 무관 트래킹 (저장만, 적용은 modifier 함수에서)
    s = update_emergence_deficit(s, episode_type)

    logger.info(
        "[ArcStateEngine] 갱신 완료 — "
        "arc_day=%d tension=%d momentum=%d sig=%d crowd=%d rift=%d%% "
        "pair=%s edt_pressure=%.2f deficit_days=%d",
        s.get("arc_day", 0),
        s.get("arc_tension", 30),
        s.get("hero_momentum", 50),
        s.get("villain_signature", 1),
        s.get("crowd_momentum", 0),
        s.get("dimensional_rift_progress", 0),
        s.get("pair_tension", {}),
        s.get("edt_pressure", 0.0),
        s.get("emergence_deficit_days", 0),
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
        # ── Phase 2.3 (PAIR + EMERGENCE) ──
        "pair_tension":         state.get("pair_tension", {"PAIR_A": 0, "PAIR_B": 0, "PAIR_C": 0}),
        "edt_pressure":         state.get("edt_pressure", 0.0),
        "emergence_deficit_days": state.get("emergence_deficit_days", 0),
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
        # ── v2.2 신규 (PAIR_TENSION_ENABLED 시 사용) ──
        "pair_tension":             {"PAIR_A": 0, "PAIR_B": 0, "PAIR_C": 0},
        "edt_pressure":             0.0,
        # ── EMERGENCE Information Deficit (RULE EMR-01) ──
        "emergence_deficit_days":   0,
    }


# ── Feature Flag 가드 ─────────────────────────────────────────────────────────

def is_enabled() -> bool:
    """ARC_STATE_V3_ENABLED 환경변수 확인."""
    return os.environ.get("ARC_STATE_V3_ENABLED", "false").lower() == "true"


# ════════════════════════════════════════════════════════════════════════════
# Phase 2.3 신규 — PAIR_TENSION + edt_pressure (G03)
# Feature Flag: PAIR_TENSION_ENABLED
# 설계 기반: EDT ARC_STATE_SCHEMA v2.2 / 05 v2.11 RULE PR-*
# ════════════════════════════════════════════════════════════════════════════

# ── PAIR 가중치 (edt_pressure 자동 재계산용) ───────────────────────────────
_PAIR_WEIGHT: dict[str, float] = {
    "PAIR_A": 1.0,   # EDT ↔ Leverage  (통제 vs 야성)
    "PAIR_B": 0.5,   # Iron Nuna ↔ Futures Girl (방어 vs 신호)
    "PAIR_C": 0.3,   # Gold Bond ↔ Zero Block (질서 vs 혼돈)
}

# ── 캐릭터 → 페어 매핑 (관련 페어 판정용) ─────────────────────────────────
_CHAR_TO_PAIR: dict[str, str] = {
    "CHAR_HERO_001": "PAIR_A",   # EDT (SOLO HUB이지만 PAIR_A 한 축)
    "CHAR_HERO_003": "PAIR_A",   # Leverage Muscle Man
    "CHAR_HERO_002": "PAIR_B",   # Iron Securities Nuna
    "CHAR_HERO_004": "PAIR_B",   # Exposure Futures Girl
    "CHAR_HERO_005": "PAIR_C",   # Gold Bond Muscle
    # CHAR_ANTI_HERO_001 (Zero Block) → PAIR_C 짝, ICG 미정의 시 비활성
}

# ── PAIR 증감량 (RULE PR-03/04/05/06) ──────────────────────────────────────
_PAIR_DELTA_DRAW         = 5
_PAIR_DELTA_DEFEAT       = 10
_PAIR_DELTA_FORM2        = 20   # PAIR_A 전용, 1회성
_PAIR_DELTA_ZERO_BLOCK   = 30   # PAIR_C 전용
_PAIR_DELTA_CONFLICT     = -30  # 해당 페어만
_PAIR_DELTA_AFTERMATH    = -10  # 모든 페어
_PAIR_DELTA_VILLAIN_DEFEATED = -15  # 모든 페어

# ── PR-01/07 임계값 ─────────────────────────────────────────────────────────
PAIR_TENSION_TRIGGER_THRESHOLD = 70    # CONFLICT 가중 발동
EDT_PRESSURE_FORM3_BONUS_THRESHOLD = 150.0  # PR-07 Form3 가중

# ── PR-01 동률 우선순위 ─────────────────────────────────────────────────────
_PAIR_PRIORITY_ORDER = ["PAIR_A", "PAIR_B", "PAIR_C"]


def is_pair_tension_enabled() -> bool:
    """PAIR_TENSION_ENABLED 환경변수 확인."""
    return os.environ.get("PAIR_TENSION_ENABLED", "false").lower() == "true"


def clamp_pair_value(value: int | float) -> int:
    """페어 텐션 값 0~100 클램프."""
    return max(0, min(100, int(value)))


def calc_edt_pressure(pair_tension: dict[str, int]) -> float:
    """
    edt_pressure 자동 재계산.
    공식: PAIR_A * 1.0 + PAIR_B * 0.5 + PAIR_C * 0.3
    최대값: 100 + 50 + 30 = 180.0
    """
    if not isinstance(pair_tension, dict):
        return 0.0
    total = 0.0
    for pair_id, weight in _PAIR_WEIGHT.items():
        val = pair_tension.get(pair_id, 0) or 0
        total += float(val) * weight
    return round(total, 2)


def get_pair_for_character(char_id: str) -> str | None:
    """캐릭터 ID → 소속 페어 (없으면 None)."""
    return _CHAR_TO_PAIR.get(char_id)


def get_relevant_pair(hero_ids: list[str]) -> str | None:
    """
    에피소드에 등장한 히어로들로부터 '관련 페어' 결정.
    페어 양 캐릭터가 모두 등장한 경우에만 해당 페어 반환.

    Returns:
        페어 ID ("PAIR_A" 등) 또는 None.
    """
    pair_member_count: dict[str, int] = {}
    for h_id in hero_ids:
        p = _CHAR_TO_PAIR.get(h_id)
        if p:
            pair_member_count[p] = pair_member_count.get(p, 0) + 1
    # 양 캐릭터 모두 등장(>=2)한 페어 우선
    for p in _PAIR_PRIORITY_ORDER:
        if pair_member_count.get(p, 0) >= 2:
            return p
    return None


def update_pair_tension(
    state: dict[str, Any],
    outcome: str,
    episode_type: str,
    hero_ids: list[str],
    form_triggered: int = 0,
    zero_block_appeared: bool = False,
    villain_defeated: bool = False,
) -> dict[str, Any]:
    """
    에피소드 결과에 따라 pair_tension 갱신.

    RULE PR-03: 자동 증가 (Draw/Defeat/Form2/Zero Block 등장)
    RULE PR-04: CONFLICT 발행 후 해당 페어 -30
    RULE PR-05: AFTERMATH 발행 후 모든 페어 -10
    RULE PR-06: 빌런 격퇴 시 모든 페어 -15

    Args:
        state:               현재 arc_state
        outcome:             OUTCOME 문자열
        episode_type:        에피소드 타입 (CONFLICT/AFTERMATH/...)
        hero_ids:            등장 히어로 ID 리스트
        form_triggered:      2 또는 3 (Form 발동 단계), 0이면 미발동
        zero_block_appeared: Zero Block 등장 여부
        villain_defeated:    빌런 Arc 종결 여부

    Returns:
        갱신된 arc_state (deep copy)
    """
    import copy
    s = copy.deepcopy(state)
    pt = s.get("pair_tension") or {"PAIR_A": 0, "PAIR_B": 0, "PAIR_C": 0}
    # JSON 직렬화/역직렬화 안전성 확보
    pt = {k: int(pt.get(k, 0) or 0) for k in ("PAIR_A", "PAIR_B", "PAIR_C")}

    relevant_pair = get_relevant_pair(hero_ids)

    # ── PR-04: CONFLICT 발행 후 해당 페어 -30 ────────────────────────────
    if episode_type == "CONFLICT":
        target_pair = _select_highest_pair_over_threshold(pt) or relevant_pair
        if target_pair:
            pt[target_pair] = clamp_pair_value(pt[target_pair] + _PAIR_DELTA_CONFLICT)
            logger.info(
                "[ArcStateEngine] RULE PR-04: CONFLICT 종결 → %s -30 (현재 %d)",
                target_pair, pt[target_pair],
            )

    # ── PR-05: AFTERMATH 발행 후 모든 페어 -10 ───────────────────────────
    elif episode_type == "AFTERMATH":
        for p in pt:
            pt[p] = clamp_pair_value(pt[p] + _PAIR_DELTA_AFTERMATH)
        logger.info("[ArcStateEngine] RULE PR-05: AFTERMATH → 모든 페어 -10")

    # ── PR-06 [6-1]: 빌런 격퇴 시 모든 페어 -15 ──────────────────────────
    if villain_defeated:
        for p in pt:
            pt[p] = clamp_pair_value(pt[p] + _PAIR_DELTA_VILLAIN_DEFEATED)
        logger.info("[ArcStateEngine] RULE PR-06: 빌런 격퇴 → 모든 페어 -15")

    # ── PR-03: 자동 증가 (관련 페어가 식별된 경우만) ─────────────────────
    if relevant_pair and episode_type not in ("CONFLICT", "AFTERMATH"):
        if outcome == "DRAW":
            pt[relevant_pair] = clamp_pair_value(pt[relevant_pair] + _PAIR_DELTA_DRAW)
            logger.info(
                "[ArcStateEngine] RULE PR-03: Draw → %s +5", relevant_pair,
            )
        elif outcome in ("HERO_DEFEAT", "VILLAIN_TEMP_VICTORY"):
            pt[relevant_pair] = clamp_pair_value(pt[relevant_pair] + _PAIR_DELTA_DEFEAT)
            logger.info(
                "[ArcStateEngine] RULE PR-03: Defeat → %s +10", relevant_pair,
            )

    # ── PR-03: Form 2 발동 → PAIR_A +20 (1회성, Arc 내 중복은 호출자 책임) ──
    if form_triggered == 2:
        pt["PAIR_A"] = clamp_pair_value(pt["PAIR_A"] + _PAIR_DELTA_FORM2)
        logger.info("[ArcStateEngine] RULE PR-03: Form 2 발동 → PAIR_A +20")

    # ── PR-03: Zero Block 등장 → PAIR_C +30 (다음 EP부터 산입은 PR-06 [6-2]) ──
    if zero_block_appeared:
        pt["PAIR_C"] = clamp_pair_value(pt["PAIR_C"] + _PAIR_DELTA_ZERO_BLOCK)
        s["zero_block_just_appeared"] = True  # STEP 1.5-B에서 트리거 제외 플래그
        logger.info("[ArcStateEngine] RULE PR-03: Zero Block 등장 → PAIR_C +30")
    else:
        s["zero_block_just_appeared"] = False

    # ── edt_pressure 자동 재계산 ─────────────────────────────────────────
    s["pair_tension"] = pt
    s["edt_pressure"] = calc_edt_pressure(pt)
    logger.info(
        "[ArcStateEngine] pair_tension=%s edt_pressure=%.2f",
        pt, s["edt_pressure"],
    )
    return s


def _select_highest_pair_over_threshold(
    pair_tension: dict[str, int],
    threshold: int = PAIR_TENSION_TRIGGER_THRESHOLD,
) -> str | None:
    """
    임계값 이상인 페어 중 최고 텐션 페어 반환.
    동률 시 A > B > C 우선순위.
    """
    candidates: list[tuple[str, int]] = []
    for p in _PAIR_PRIORITY_ORDER:
        v = pair_tension.get(p, 0) or 0
        if v >= threshold:
            candidates.append((p, v))
    if not candidates:
        return None
    # 최고값 → 동률 시 우선순위 순서
    candidates.sort(key=lambda x: (-x[1], _PAIR_PRIORITY_ORDER.index(x[0])))
    return candidates[0][0]


def check_pair_tension_trigger(state: dict[str, Any]) -> tuple[bool, str | None]:
    """
    STEP 1.5-B 페어 텐션 체크.

    Returns:
        (pair_tension_trigger_flag, triggered_pair)
    """
    pt = state.get("pair_tension") or {}
    pt = {k: int(pt.get(k, 0) or 0) for k in ("PAIR_A", "PAIR_B", "PAIR_C")}

    # Zero Block 당일 PAIR_C 제외 (RULE PR-06 [6-2])
    if state.get("zero_block_just_appeared"):
        eval_pt = {**pt, "PAIR_C": 0}
    else:
        eval_pt = pt

    triggered = _select_highest_pair_over_threshold(eval_pt)
    return (triggered is not None), triggered


# ════════════════════════════════════════════════════════════════════════════
# Phase 2.3 신규 — crowd_momentum 감쇠 + EMERGENCE deficit (G08, G09)
# ════════════════════════════════════════════════════════════════════════════

def attenuate_crowd_momentum(crowd_momentum: int, step: int = 2) -> int:
    """
    RULE CM-02 — crowd_momentum 자동 감쇠.

    원리: 매 에피소드마다 abs(값) - step (최소 0).
    부호는 유지. ICG 범위 -20~+20 보존.

    Args:
        crowd_momentum: 현재 값 (-20 ~ +20)
        step:           감쇠량 (기본 2)

    Returns:
        감쇠된 값.
    """
    if crowd_momentum > 0:
        return max(0, crowd_momentum - step)
    if crowd_momentum < 0:
        return min(0, crowd_momentum + step)
    return 0


def update_emergence_deficit(
    state: dict[str, Any],
    episode_type: str,
) -> dict[str, Any]:
    """
    RULE EMR-01 — EMERGENCE Information Deficit days 갱신.

    EMERGENCE 에피소드 발행 시: deficit_days = 2 (이번 EP 포함 → 다음 EP 1, 그 다음 0)
    매 에피소드 후: deficit_days -= 1 (최소 0)

    Args:
        state:        현재 arc_state
        episode_type: 이번 에피소드 타입

    Returns:
        갱신된 state (deep copy)
    """
    import copy
    s = copy.deepcopy(state)
    days = s.get("emergence_deficit_days") or 0

    if episode_type == "EMERGENCE":
        s["emergence_deficit_days"] = 2
        logger.info("[ArcStateEngine] RULE EMR-01: EMERGENCE 발행 → deficit_days=2")
    else:
        s["emergence_deficit_days"] = max(0, days - 1)
        if days > 0:
            logger.info(
                "[ArcStateEngine] RULE EMR-01: deficit_days %d → %d",
                days, s["emergence_deficit_days"],
            )
    return s


def get_emergence_deficit_modifier(state: dict[str, Any], episode_type: str) -> int:
    """
    RULE EMR-01 — EMERGENCE Information Deficit 적용값 산출.

    Hero Total Power 감산용 modifier 반환:
        EMERGENCE 에피소드 당일:  -10
        deficit_days == 1:        -5  (직후 1 EP 잔류)
        그 외:                      0

    Args:
        state:        현재 arc_state (deficit_days 갱신 *전* 상태)
        episode_type: 이번 에피소드 타입

    Returns:
        Hero Power에 더할 modifier (음수 또는 0).
    """
    if not os.environ.get("EMERGENCE_DEFICIT_ENABLED", "false").lower() == "true":
        return 0
    if episode_type == "EMERGENCE":
        return -10
    days = state.get("emergence_deficit_days") or 0
    if days >= 2:
        return -10
    if days == 1:
        return -5
    return 0
