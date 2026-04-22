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
    from engine.common.notion_loader import load_characters_canon

    return load_characters_canon()


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

    Returns:
        렌더링된 사용자 프롬프트 문자열.
    """
    from engine.common.notion_loader import load_narrative_user_template

    # heroes 기본값 처리 — None이면 기존 단일 히어로로 fallback
    if heroes is None:
        heroes = [hero_id]

    template_str = load_narrative_user_template()
    canon = _load_canon()
    heroes_canon = canon.get("heroes", {})
    villains = canon.get("villains", {})
    hero_entry = heroes_canon.get(hero_id, {})
    villain_entry = villains.get(villain_id, {})

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
        heroes=heroes_canon,          # 기존: 캐릭터 전체 dict ({% for cid, char in heroes.items() %} 루프용)
        villains=villains,
        # ── v2.0 신규 변수 ────────────────────────────────────────────────────
        scenario_type=scenario_type,  # {{ scenario_type }} 치환
        ending_tone=ending_tone,      # {{ ending_tone }} 치환
        hero_ids=heroes,              # {{ hero_ids[0] }}, {{ hero_ids[1] }} 치환 (ALLIANCE 2명)
        # ── Step 3-Story 신규 변수 (2026-04-22 보정) ──────────────────────────
        guest_character_prompt=guest_character_prompt,  # {{ guest_character_prompt }} 치환
    )


def load_system_prompt() -> str:
    """Notion에서 narrative_system_prompt 로드."""
    from engine.common.notion_loader import load_narrative_system

    return load_narrative_system()
