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
            first_val = data[first_key]
            if first_key.startswith("CHAR_HERO"):
                # 값이 dict이면 HERO_BONUS_TABLE, int이면 CHARACTER_BASE_POWER
                if isinstance(first_val, dict):
                    result["HERO_BONUS_TABLE"] = data
                else:
                    result["CHARACTER_BASE_POWER"] = data
            elif first_key.startswith("CHAR_VILLAIN"):
                if isinstance(first_val, dict):
                    result["VILLAIN_PENALTY_TABLE"] = data
                else:
                    result.setdefault("CHARACTER_BASE_POWER", {}).update(data)
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


def load_chart_direction_rule() -> dict[str, str]:
    """
    아웃컴별 배경 차트 방향 규칙 로드.
    Notion image_prompt_blocks의 CHART_DIRECTION_RULE JSON 파싱.
    """
    page_id = os.environ.get("NOTION_IMAGE_PROMPTS_ID")
    if not page_id:
        return {}
    text = _load_page_cached(page_id)

    spec_start = text.find("CHART_DIRECTION_RULE")
    if spec_start == -1:
        return {}

    section_text = text[spec_start:]
    brace_start = section_text.find("{")
    if brace_start == -1:
        return {}

    depth = 0
    json_end = -1
    for i, ch in enumerate(section_text[brace_start:], brace_start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                json_end = i + 1
                break

    if json_end == -1:
        return {}

    try:
        return json.loads(section_text[brace_start:json_end])
    except json.JSONDecodeError:
        return {}


def load_panel_visual_spec() -> dict[str, dict]:
    """
    패널 타입별 시각적 스펙 로드 (조명/구도/분위기).

    Notion image_prompt_blocks의 PANEL_TYPE_VISUAL_SPEC JSON 파싱.

    Returns:
        {panel_type: {composition, lighting, atmosphere, camera_rule}}
    """
    page_id = os.environ.get("NOTION_IMAGE_PROMPTS_ID")
    if not page_id:
        raise RuntimeError("NOTION_IMAGE_PROMPTS_ID 환경변수 필수")
    text = _load_page_cached(page_id)

    # PANEL_TYPE_VISUAL_SPEC JSON 블록 추출 (중첩 JSON 대응)
    # "PANEL_TYPE_VISUAL_SPEC" 헤더 이후 첫 번째 완전한 JSON 오브젝트 추출
    spec_start = text.find("PANEL_TYPE_VISUAL_SPEC")
    if spec_start == -1:
        logger.warning("[notion_loader] PANEL_TYPE_VISUAL_SPEC 섹션 없음 — fallback 빈 dict")
        return {}

    # 해당 섹션 이후 텍스트에서 { ... } 블록 추출
    section_text = text[spec_start:]
    brace_start = section_text.find("{")
    if brace_start == -1:
        return {}

    # 중첩 괄호 카운팅으로 JSON 범위 확정
    depth = 0
    json_end = -1
    for i, ch in enumerate(section_text[brace_start:], brace_start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                json_end = i + 1
                break

    if json_end == -1:
        logger.warning("[notion_loader] PANEL_TYPE_VISUAL_SPEC JSON 범위 추출 실패")
        return {}

    try:
        return json.loads(section_text[brace_start:json_end])
    except json.JSONDecodeError as e:
        logger.warning("[notion_loader] PANEL_TYPE_VISUAL_SPEC 파싱 실패: %s", e)
        return {}


def load_char_design_blocks(char_ids: list[str] | None = None) -> dict[str, dict]:
    """
    Notion character_ref_prompts 페이지의 CHAR_DESIGN_SPECS JSON 로드.

    캐릭터별 외형 고정 명세를 패널 프롬프트에 자동 주입하기 위해 사용.

    Args:
        char_ids: 필터링할 char_id 목록. None이면 전체 반환.

    Returns:
        {char_id: {name, role, position, facing, body, costume, identifier, color_rule, strict, ...}}
    """
    page_id = os.environ.get("NOTION_REF_PROMPTS_ID")
    if not page_id:
        raise RuntimeError("NOTION_REF_PROMPTS_ID 환경변수 필수")
    text = _load_page_cached(page_id)

    # CHAR_DESIGN_SPECS JSON 블록 추출 (중첩 JSON 대응)
    spec_start = text.find("CHAR_DESIGN_SPECS")
    if spec_start == -1:
        logger.warning("[notion_loader] CHAR_DESIGN_SPECS 섹션 없음")
        return {}

    section_text = text[spec_start:]
    brace_start = section_text.find("{")
    if brace_start == -1:
        return {}

    depth = 0
    json_end = -1
    for i, ch in enumerate(section_text[brace_start:], brace_start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                json_end = i + 1
                break

    if json_end == -1:
        logger.warning("[notion_loader] CHAR_DESIGN_SPECS JSON 범위 추출 실패")
        return {}

    try:
        all_specs: dict[str, dict] = json.loads(section_text[brace_start:json_end])
    except json.JSONDecodeError as e:
        logger.warning("[notion_loader] CHAR_DESIGN_SPECS JSON 파싱 실패: %s", e)
        return {}

    if char_ids is None:
        return all_specs

    return {k: v for k, v in all_specs.items() if k in char_ids}


def char_design_to_prompt_block(char_id: str, spec: dict) -> str:
    """
    캐릭터 외형 명세 dict → Gemini 프롬프트 텍스트 블록 변환.

    Example output:
        == CHAR_DESIGN: EDT (Endurance D Tiger) ==
        Role: HERO | Position: LEFT | Facing: RIGHT
        Body: Korean male warrior, 30s...
        ...
        STRICT: Same design every panel.
        == END CHAR_DESIGN ==
    """
    name = spec.get("name", char_id)
    role = spec.get("role", "")
    position = spec.get("position", "")
    facing = spec.get("facing", "")

    lines = [
        f"== CHAR_DESIGN: {name} ==",
        f"Role: {role} | Position: {position} side | Facing: {facing}",
    ]

    field_labels = [
        ("body", "Body"),
        ("costume", "Costume"),
        ("helmet", "Helmet"),
        ("shield", "Shield"),
        ("weapon", "Weapon"),
        ("identifier", "Identifier — MANDATORY"),
        ("color_rule", "Color Rule — STRICT"),
        ("strict", "STRICT CONSISTENCY"),
    ]
    for key, label in field_labels:
        val = spec.get(key)
        if val:
            lines.append(f"{label}: {val}")

    lines.append(f"== END CHAR_DESIGN: {name} ==")
    return "\n".join(lines)


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
