"""
Phase 2.3 G02 — narrative_user.j2 belief + pair_tension 블록 렌더링 검증.

검증 항목:
- narrative_depth_enabled=False → belief 블록 미출력 (백워드 호환)
- narrative_depth_enabled=True → Character Belief Sheet 출력
- natural_disaster 빌런 (V002 Oil Shock) → 4요소 분기 출력
- pair_tension_enabled=False → Pair Relationship 블록 미출력
- pair_tension_enabled=True → 블록 출력 + triggered_pair 경고 표시
- Feature Flag OFF 양쪽 → 기존 동작과 동일 (블록 미포함)
"""
from __future__ import annotations

import pytest

from engine.narrative.prompt_tpl import render_user_prompt

# ── 공통 fixture (최소한의 렌더 입력) ─────────────────────────────────────────

@pytest.fixture
def base_kwargs() -> dict:
    return dict(
        date="2026-05-14",
        episode_id="ep029",
        event_type="MARKET_SHOCK",
        delta={
            "spx": {"change_pct": -2.0},
            "wti": {"change_pct": 5.0},
            "reversal_state": "NONE",
        },
        battle_result={
            "hero_power": 100,
            "villain_power": 90,
            "balance": 10,
            "outcome": "HERO_TACTICAL_VICTORY",
        },
        hero_id="CHAR_HERO_001",
        villain_id="CHAR_VILLAIN_002",
        arc_context={
            "arc_day": 5,
            "arc_tension": 50,
            "crowd_momentum": 5,
            "villain_signature": 1,
            "pair_tension": {"PAIR_A": 75, "PAIR_B": 0, "PAIR_C": 0},
            "edt_pressure": 75.0,
            "emergence_deficit_days": 0,
        },
    )


HERO_BELIEF_SAMPLE = {
    "want": "무너지지 않는 시스템을 만드는 것.",
    "need": "회복력의 본질을 깨닫는 것.",
    "fear": "팀이 무너지는 것.",
    "lie": "내가 강하면 충분하다.",
    "truth": "함께 있어야 강하다.",
    "contradiction": "리더지만 외롭다.",
}

VILLAIN_BELIEF_NATURAL_DISASTER = {
    "natural_disaster": True,
    "phenomenon": "에너지 가격 임계 초과 시 발현.",
    "attenuation": "가격이 회귀할 때 약화.",
    "revelation": "자연재해는 영원하지 않다.",
    "paradox": "파괴 후 자신도 사라진다.",
    "defeat_visual": "화염이 잦아든다.",
}

VILLAIN_BELIEF_REGULAR = {
    "want": "모든 가치가 부채로 환산되는 세상.",
    "lie": "쌓이는 것이 곧 힘이다.",
    "truth": "무한히 쌓이면 무너진다.",
    "contradiction": "시간이 키우지만 누구의 편도 아니다.",
    "defeat_visual": "쌓인 산이 무너진다.",
}


# ── 백워드 호환: 모든 Flag OFF ─────────────────────────────────────────────────

def test_render_default_no_belief_block(base_kwargs: dict) -> None:
    """narrative_depth_enabled 미지정 (기본 False) → belief 블록 미출력."""
    rendered = render_user_prompt(**base_kwargs)
    assert "Character Belief Sheet" not in rendered
    assert "RULE BS-01" not in rendered


def test_render_default_no_pair_block(base_kwargs: dict) -> None:
    """pair_tension_enabled 기본 False → Pair Relationship 블록 미출력."""
    rendered = render_user_prompt(**base_kwargs)
    assert "Pair Relationship Tension" not in rendered
    assert "Triggered Pair" not in rendered


# ── narrative_depth_enabled=True: belief 블록 출력 ───────────────────────────

def test_render_belief_block_hero_present(base_kwargs: dict) -> None:
    rendered = render_user_prompt(
        **base_kwargs,
        narrative_depth_enabled=True,
        hero_belief=HERO_BELIEF_SAMPLE,
        villain_belief=VILLAIN_BELIEF_REGULAR,
    )
    assert "Character Belief Sheet" in rendered
    assert "RULE BS-01" in rendered
    # 히어로 belief 6요소 모두 포함
    assert "무너지지 않는 시스템" in rendered  # want
    assert "회복력의 본질" in rendered          # need
    assert "팀이 무너지는 것" in rendered       # fear
    assert "내가 강하면 충분" in rendered       # lie
    assert "함께 있어야 강하다" in rendered     # truth
    assert "리더지만 외롭다" in rendered        # contradiction


def test_render_belief_block_villain_regular(base_kwargs: dict) -> None:
    rendered = render_user_prompt(
        **base_kwargs,
        narrative_depth_enabled=True,
        hero_belief=HERO_BELIEF_SAMPLE,
        villain_belief=VILLAIN_BELIEF_REGULAR,
    )
    # 일반 빌런 belief 요소
    assert "모든 가치가 부채" in rendered
    assert "쌓이는 것이 곧 힘" in rendered
    # natural_disaster 분기는 출력되지 않아야 함
    assert "phenomenon" not in rendered.lower() or "에너지 가격 임계" not in rendered


def test_render_belief_block_villain_natural_disaster(base_kwargs: dict) -> None:
    """V002 Oil Shock = natural_disaster 4요소 분기."""
    rendered = render_user_prompt(
        **base_kwargs,
        narrative_depth_enabled=True,
        hero_belief=HERO_BELIEF_SAMPLE,
        villain_belief=VILLAIN_BELIEF_NATURAL_DISASTER,
    )
    # 4요소 출력 확인
    assert "에너지 가격 임계" in rendered       # phenomenon
    assert "가격이 회귀할 때" in rendered       # attenuation
    assert "자연재해는 영원하지 않다" in rendered  # revelation
    assert "파괴 후 자신도 사라진다" in rendered   # paradox


# ── pair_tension_enabled=True: Pair 블록 출력 ────────────────────────────────

def test_render_pair_block_present(base_kwargs: dict) -> None:
    rendered = render_user_prompt(
        **base_kwargs,
        pair_tension_enabled=True,
    )
    assert "Pair Relationship Tension" in rendered
    assert "RULE PR-01" in rendered
    # 페어 값 출력
    assert "PAIR_A" in rendered
    assert "75" in rendered  # PAIR_A 값
    assert "PR-02" in rendered  # 규칙 안내


def test_render_pair_triggered_warning(base_kwargs: dict) -> None:
    """triggered_pair가 전달되면 경고 표시."""
    rendered = render_user_prompt(
        **base_kwargs,
        pair_tension_enabled=True,
        triggered_pair="PAIR_A",
    )
    assert "Triggered Pair" in rendered
    assert "PAIR_A" in rendered
    assert "tension >= 70" in rendered or "CONFLICT 가중" in rendered


def test_render_pair_no_trigger_no_warning(base_kwargs: dict) -> None:
    """triggered_pair=None이면 경고 미출력."""
    rendered = render_user_prompt(
        **base_kwargs,
        pair_tension_enabled=True,
        triggered_pair=None,
    )
    # Pair 블록은 출력되지만 trigger 경고는 미출력
    assert "Pair Relationship Tension" in rendered
    assert "Triggered Pair" not in rendered


# ── 양 Flag ON 동시 출력 ─────────────────────────────────────────────────────

def test_render_both_features_combined(base_kwargs: dict) -> None:
    rendered = render_user_prompt(
        **base_kwargs,
        narrative_depth_enabled=True,
        pair_tension_enabled=True,
        hero_belief=HERO_BELIEF_SAMPLE,
        villain_belief=VILLAIN_BELIEF_NATURAL_DISASTER,
        triggered_pair="PAIR_A",
    )
    assert "Character Belief Sheet" in rendered
    assert "Pair Relationship Tension" in rendered
    assert "Triggered Pair" in rendered
    # 양쪽 모두 핵심 키워드
    assert "RULE BS-01" in rendered
    assert "RULE PR-01" in rendered


# ── Edge case: belief 미전달 시 안전 동작 ────────────────────────────────────

def test_render_belief_enabled_but_no_belief_falls_back_safely(
    base_kwargs: dict,
) -> None:
    """
    narrative_depth_enabled=True이지만 hero_belief/villain_belief 둘 다 None.
    canon에서 자동 추출되며, canon에 없으면 빈 dict → 블록 자체가 skip.
    """
    # 명시적 None 전달 — canon 자동 로드 시도, characters.yaml에 belief 없을 수 있음
    rendered = render_user_prompt(
        **base_kwargs,
        narrative_depth_enabled=True,
        hero_belief=None,
        villain_belief=None,
    )
    # Exception 없이 렌더링 완료 (블록이 있든 없든 OK)
    assert isinstance(rendered, str)
    assert len(rendered) > 0
