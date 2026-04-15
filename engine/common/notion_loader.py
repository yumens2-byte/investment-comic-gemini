"""
engine/common/notion_loader.py
Notion 페이지에서 민감 콘텐츠를 런타임에 로드하는 공통 모듈.

Public repo에 노출되면 안 되는 프롬프트/캐논/수식을 Notion에 저장하고
이 모듈을 통해 런타임에 가져온다.

필요 환경변수:
    NOTION_API_KEY                — Notion 통합 토큰
    NOTION_NARRATIVE_SYSTEM_ID   — narrative_system_prompt 페이지 ID
    NOTION_NARRATIVE_USER_ID     — narrative_user_template 페이지 ID
    NOTION_IMAGE_PROMPTS_ID      — image_prompt_blocks 페이지 ID
    NOTION_BATTLE_CONSTANTS_ID   — battle_calc_constants 페이지 ID
    NOTION_REF_PROMPTS_ID        — character_ref_prompts 페이지 ID
"""

from __future__ import annotations

import json
import logging
import os
import re
from functools import lru_cache

import requests

logger = logging.getLogger(__name__)

_NOTION_API = "https://api.notion.com/v1"
_HEADERS_CACHE: dict | None = None


def _headers() -> dict:
    global _HEADERS_CACHE
    if _HEADERS_CACHE is None:
        token = os.environ.get("NOTION_API_KEY", "")
        if not token:
            raise RuntimeError("NOTION_API_KEY 환경변수 없음")
        _HEADERS_CACHE = {
            "Authorization": f"Bearer {token}",
            "Notion-Version": "2022-06-28",
        }
    return _HEADERS_CACHE


def _fetch_page_text(page_id: str) -> str:
    """Notion 페이지 블록 전체를 plain text로 반환."""
    page_id = page_id.replace("-", "")
    url = f"{_NOTION_API}/blocks/{page_id}/children?page_size=100"
    resp = requests.get(url, headers=_headers(), timeout=15)
    resp.raise_for_status()
    blocks = resp.json().get("results", [])

    lines: list[str] = []
    for block in blocks:
        btype = block.get("type", "")
        rich = block.get(btype, {}).get("rich_text", [])
        text = "".join(r.get("plain_text", "") for r in rich)

        if btype == "code":
            # 코드블록: 언어 무시하고 내용만
            lines.append(text)
        elif btype in ("paragraph", "heading_1", "heading_2", "heading_3"):
            if text.strip():
                lines.append(text)
        elif btype == "bulleted_list_item":
            lines.append(f"- {text}")
        # 그 외 블록은 무시

    return "\n".join(lines)


@lru_cache(maxsize=16)
def _load_page_cached(page_id: str) -> str:
    """페이지 텍스트 캐시 (프로세스 내 1회만 호출)."""
    logger.debug("[notion_loader] 로드: %s", page_id[:8])
    return _fetch_page_text(page_id)


# ── Public API ─────────────────────────────────────────────────────────────


def load_narrative_system() -> str:
    """Claude 시스템 프롬프트 로드."""
    page_id = os.environ.get("NOTION_NARRATIVE_SYSTEM_ID")
    if not page_id:
        raise RuntimeError("NOTION_NARRATIVE_SYSTEM_ID 환경변수 필수")
    return _load_page_cached(page_id)


def load_narrative_user_template() -> str:
    """Claude 유저 프롬프트 Jinja2 템플릿 로드."""
    page_id = os.environ.get("NOTION_NARRATIVE_USER_ID")
    if not page_id:
        raise RuntimeError("NOTION_NARRATIVE_USER_ID 환경변수 필수")
    return _load_page_cached(page_id)


def load_image_prompt_blocks() -> dict[str, str]:
    """
    Gemini 이미지 프롬프트 블록 로드.

    Returns:
        {
            "GLOBAL_STYLE_BLOCK": "...",
            "SECURITY_NEGATIVE_BLOCK_V1_1": "...",
        }
    """
    page_id = os.environ.get("NOTION_IMAGE_PROMPTS_ID")
    if not page_id:
        raise RuntimeError("NOTION_IMAGE_PROMPTS_ID 환경변수 필수")
    text = _load_page_cached(page_id)

    result: dict[str, str] = {}

    # GLOBAL_STYLE_BLOCK 추출
    m = re.search(r"GLOBAL_STYLE_BLOCK\n(.*?)(?=SECURITY_NEGATIVE|PANEL_TYPE|\Z)", text, re.DOTALL)
    if m:
        result["GLOBAL_STYLE_BLOCK"] = m.group(1).strip()

    # SECURITY_NEGATIVE_BLOCK 추출
    m = re.search(r"SECURITY_NEGATIVE_BLOCK_V1_1\n(.*?)(?=PANEL_TYPE|\Z)", text, re.DOTALL)
    if m:
        result["SECURITY_NEGATIVE_BLOCK_V1_1"] = m.group(1).strip()

    return result


def load_battle_constants() -> dict:
    """
    전투 계산 상수 로드.

    Returns:
        {
            "HERO_BONUS_TABLE": {...},
            "VILLAIN_PENALTY_TABLE": {...},
            "OUTCOME_THRESHOLDS": {...},
            "FORM_BONUS_TABLE": {...},
        }
    """
    page_id = os.environ.get("NOTION_BATTLE_CONSTANTS_ID")
    if not page_id:
        raise RuntimeError("NOTION_BATTLE_CONSTANTS_ID 환경변수 필수")
    text = _load_page_cached(page_id)

    result: dict = {}
    # JSON 코드블록 추출
    for match in re.finditer(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", text, re.DOTALL):
        try:
            data = json.loads(match.group())
            # 첫 번째 키로 테이블 구분
            keys = list(data.keys())
            if not keys:
                continue
            first_key = keys[0]
            if first_key.startswith("CHAR_HERO"):
                result["HERO_BONUS_TABLE"] = data
            elif first_key.startswith("CHAR_VILLAIN"):
                result["VILLAIN_PENALTY_TABLE"] = data
            elif "HERO_VICTORY" in keys:
                result["OUTCOME_THRESHOLDS"] = data
            elif "form0" in keys:
                result["FORM_BONUS_TABLE"] = data
        except json.JSONDecodeError:
            continue

    return result


def load_ref_prompts() -> dict[str, str]:
    """
    캐릭터 REF 이미지 생성 프롬프트 로드.

    Returns:
        {char_id: prompt_text, ...}
    """
    page_id = os.environ.get("NOTION_REF_PROMPTS_ID")
    if not page_id:
        raise RuntimeError("NOTION_REF_PROMPTS_ID 환경변수 필수")
    text = _load_page_cached(page_id)

    result: dict[str, str] = {}
    # ## CHAR_XXX 섹션 분리
    sections = re.split(r"## (CHAR_(?:HERO|VILLAIN)_\d+)", text)
    for i in range(1, len(sections), 2):
        char_id = sections[i].strip().split(" ")[0]  # "CHAR_HERO_001"만
        content = sections[i + 1].strip() if i + 1 < len(sections) else ""
        if char_id and content:
            result[char_id] = content

    return result


def load_characters_canon() -> dict:
    """
    characters.yaml 대신 Notion에서 캐릭터 캐논 로드.
    현재는 로컬 yaml 폴백 유지 (Phase 2에서 완전 이전 예정).
    """
    from pathlib import Path

    import yaml

    canon_path = Path("config/characters.yaml")
    if canon_path.exists():
        return yaml.safe_load(canon_path.read_text(encoding="utf-8"))
    raise FileNotFoundError("config/characters.yaml 없음")
