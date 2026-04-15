"""
engine/narrative/prompt_tpl.py
Claude 사용자 프롬프트 Jinja2 렌더링.

프롬프트 원본은 Public repo에 노출되지 않도록
Notion에 저장하고 런타임에 로드한다.
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
) -> str:
    """
    Notion에서 로드한 narrative_user 템플릿 렌더링.
    """
    from engine.common.notion_loader import load_narrative_user_template

    template_str = load_narrative_user_template()
    canon = _load_canon()
    heroes = canon.get("heroes", {})
    villains = canon.get("villains", {})

    hero_entry = heroes.get(hero_id, {})
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
        heroes=heroes,
        villains=villains,
    )


def load_system_prompt() -> str:
    """Notion에서 narrative_system_prompt 로드."""
    from engine.common.notion_loader import load_narrative_system

    return load_narrative_system()
