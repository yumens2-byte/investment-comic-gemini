"""
engine/narrative/prompt_tpl.py
Claude 사용자 프롬프트 Jinja2 렌더링.
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader, select_autoescape

_PROMPTS_DIR = Path("config/prompts")
_CANON_PATH = Path("config/characters.yaml")


def _load_canon() -> dict:
    with open(_CANON_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _make_jinja_env() -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(_PROMPTS_DIR)),
        autoescape=select_autoescape([]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    # tojson 필터 추가
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
    narrative_user.j2 렌더링.

    Args:
        date: 'YYYY-MM-DD'
        episode_id: 'ICG-YYYY-MM-DD-001'
        event_type: 에피소드 타입
        delta: delta_engine 출력
        battle_result: BattleResult.to_dict()
        hero_id: CHAR_HERO_00N
        villain_id: CHAR_VILLAIN_00N
        arc_context: {"tension": int, "days_since_last": int, "yesterday_type": str}

    Returns:
        렌더링된 사용자 프롬프트 문자열.
    """
    canon = _load_canon()
    heroes = canon.get("heroes", {})
    villains = canon.get("villains", {})

    hero_entry = heroes.get(hero_id, {})
    villain_entry = villains.get(villain_id, {})

    env = _make_jinja_env()
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
    """narrative_system.txt 로드."""
    path = _PROMPTS_DIR / "narrative_system.txt"
    return path.read_text(encoding="utf-8")
