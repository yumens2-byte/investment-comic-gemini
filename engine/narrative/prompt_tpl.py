"""
engine/narrative/prompt_tpl.py
Claude 사용자 프롬프트 Jinja2 렌더링.
프롬프트 원본은 Public repo에 노출되지 않도록
Notion에 저장하고 런타임에 로드한다.

v2.0 변경사항 (2026-04-18):
- render_user_prompt(): scenario_type, ending_tone, heroes 파라미터 추가 (기본값 포함).
- template.render()에 3개 변수 주입 → Notion 템플릿의 {{ scenario_type }} 등 치환 가능.
- 후방 호환: 기본값으로 기존 ONE_VS_ONE 동작 유지.

v2.1 변경사항 (2026-04-22 — Step 3-Story 보정):
- render_user_prompt(): guest_character_prompt 파라미터 추가 (기본값 "").
- template.render()에 guest_character_prompt 변수 주입 → Notion 템플릿의
  {% if guest_character_prompt %}{{ guest_character_prompt }}{% endif %} 블록에서 치환.
- 후방 호환: 기본값 ""으로 기존 동작 그대로 유지 (블록 자체가 스킵됨).
"""

from __future__ import annotations

import json
from pathlib import Path

from jinja2 import DictLoader, Environment, select_autoescape

_CANON_PATH = Path("config/characters.yaml")


def _load_canon() -> dict:
    """Load canon from Notion first, fallback to local YAML for tests/dev."""
    try:
        from engine.common.notion_loader import load_characters_canon

        return load_characters_canon()
    except Exception:
        import yaml

        if not _CANON_PATH.exists():
            return {"heroes": {}, "villains": {}}
        return yaml.safe_load(_CANON_PATH.read_text(encoding="utf-8")) or {
            "heroes": {}, "villains": {}
        }


def _make_jinja_env_from_string(template_str: str) -> Environment:
    env = Environment(
        loader=DictLoader({"narrative_user.j2": template_str}),
        autoescape=select_autoescape([]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["tojson"] = lambda val, indent=None: json.dumps(
        val, ensure_ascii=False, indent=indent
    )
    return env


def render_user_prompt(
    date: str,
    episode_id: str,
    event_type: str,
    delta: dict,
    battle_result: dict,
    hero_id: str,
    villain_id: str,
    arc_context: dict,
    # ── v2.0 신규 파라미터 (기본값으로 하위 호환 보장) ────────────────────────
    scenario_type: str = "ONE_VS_ONE",
    ending_tone: str = "TENSE",
    heroes: list[str] | None = None,
    # ── Step 3-Story 신규 파라미터 (2026-04-22 보정) ──────────────────────────
    guest_character_prompt: str = "",
    # ── Phase 2.3 신규 파라미터 (G02 BS_PR_RULES) ─────────────────────────────
    narrative_depth_enabled: bool = False,
    pair_tension_enabled: bool = False,
    triggered_pair: str | None = None,
    hero_belief: dict | None = None,
    villain_belief: dict | None = None,
) -> str:
    """
    Notion에서 로드한 narrative_user 템플릿 렌더링.

    Args:
        date:          에피소드 날짜 (YYYY-MM-DD).
        episode_id:    에피소드 ID.
        event_type:    이벤트 타입 (7종).
        delta:         시장 변화 데이터.
        battle_result: 전투 결과 dict.
        hero_id:       주 히어로 ID.
        villain_id:    빌런 ID.
        arc_context:   에피소드 연속성 정보.
        scenario_type: v2.0 — "ONE_VS_ONE" | "NO_BATTLE" | "ALLIANCE" (기본: ONE_VS_ONE).
        ending_tone:   v2.0 — "OPTIMISTIC" | "TENSE" | "OMINOUS" (기본: TENSE).
        heroes:        v2.0 — 히어로 ID 리스트. ALLIANCE=2개, 그 외=1개.
                       None이면 [hero_id] 사용.
        guest_character_prompt: 게스트 캐릭터 프롬프트 블록.
        narrative_depth_enabled: v2.3 — Belief Sheet 블록 출력 여부.
        pair_tension_enabled:    v2.3 — Pair Relationship 블록 출력 여부.
        triggered_pair:          v2.3 — STEP 1.5-B에서 triggered된 페어 ID.
        hero_belief:             v2.3 — 주 히어로 belief 6요소 dict.
        villain_belief:          v2.3 — 빌런 belief 6요소 dict (Oil Shock은 4요소).

    Returns:
        렌더링된 사용자 프롬프트 문자열.
    """
    from engine.common.notion_loader import load_narrative_user_template

    # heroes 기본값 처리 — None이면 기존 단일 히어로로 fallback
    if heroes is None:
        heroes = [hero_id]

    try:
        template_str = load_narrative_user_template()
    except Exception:
        template_str = Path("config/prompts/narrative_user.j2").read_text(encoding="utf-8")
    canon = _load_canon()
    heroes_canon = canon.get("heroes", {})
    villains = canon.get("villains", {})
    hero_entry = heroes_canon.get(hero_id, {})
    villain_entry = villains.get(villain_id, {})

    # ── Phase 2.3: characters.yaml의 belief 블록 자동 로드 ────────────────────
    # 명시적으로 hero_belief/villain_belief가 전달되지 않으면 canon에서 추출
    if narrative_depth_enabled:
        if hero_belief is None:
            hero_belief = hero_entry.get("belief") or {}
        if villain_belief is None:
            villain_belief = villain_entry.get("belief") or {}

    env = _make_jinja_env_from_string(template_str)
    template = env.get_template("narrative_user.j2")

    return template.render(
        date=date,
        episode_id=episode_id,
        event_type=event_type,
        delta=delta,
        battle_result=battle_result,
        hero_id=hero_id,
        hero_name=hero_entry.get("name_ko", hero_id),
        villain_id=villain_id,
        villain_name=villain_entry.get("name_ko", villain_id),
        arc_context=arc_context,
        heroes=heroes_canon,
        villains=villains,
        scenario_type=scenario_type,
        ending_tone=ending_tone,
        hero_ids=heroes,
        guest_character_prompt=guest_character_prompt,
        # ── Phase 2.3 신규 변수 ──
        narrative_depth_enabled=narrative_depth_enabled,
        pair_tension_enabled=pair_tension_enabled,
        triggered_pair=triggered_pair,
        hero_belief=hero_belief,
        villain_belief=villain_belief,
    )


def load_system_prompt() -> str:
    """Notion에서 narrative_system_prompt 로드."""
    from engine.common.notion_loader import load_narrative_system

    return load_narrative_system()
