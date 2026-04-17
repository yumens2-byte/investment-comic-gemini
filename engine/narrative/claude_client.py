"""
engine/narrative/claude_client.py
Claude API 호출 — EpisodeScript 생성.

모델: claude-sonnet-4-6 (fallback: claude-haiku-4-5-20251001)
max_tokens: 8000
temperature: 0.7
검증 실패 시 최대 3회 재전송.
자동 트리밍: Pydantic 검증 전 글자수 초과 필드 자동 처리.

v2.0 변경사항 (2026-04-18):
- generate_episode(): scenario_type, ending_tone, heroes 파라미터 추가 (기본값 포함)
- render_user_prompt() 호출에 v2.0 파라미터 전달
- _validate_canon(): NO_BATTLE 시 villain 패널이 없음을 확인하는 방어 로직 추가
"""

from __future__ import annotations

import json
import logging
import re

from anthropic import Anthropic

from engine.common.exceptions import (
    InvalidVillainNameError,
    NarrativeValidationError,
)
from engine.narrative.prompt_tpl import load_system_prompt, render_user_prompt
from engine.narrative.schema import EpisodeScript

logger = logging.getLogger(__name__)

_MODEL_PRIMARY = "claude-sonnet-4-6"
_MODEL_FALLBACK = "claude-haiku-4-5-20251001"
_MAX_TOKENS = 8000
_TEMPERATURE = 0.7
_MAX_RETRIES = 3  # 2 → 3 으로 증가

# Canon 빌런 영문 이름 집합 (RULE 06)
_CANON_VILLAIN_NAMES: set[str] = {
    "Oil Shock Titan",
    "Debt Titan",
    "Liquidity Leviathan",
    "Volatility Hydra",
    "Algorithm Reaper",
    "War Dominion",
}

# 각 필드별 max_length (schema.py와 동기화)
_FIELD_LIMITS: dict[str, int] = {
    "narration": 120,
    "key_text": 40,
    "logline": 100,
    "caption_x_cover": 240,
    "caption_x_final": 240,
}

# 면책 고지 필수 문구
_DISCLAIMER_PHRASES = ["투자 참고", "투자 권유가 아닙니다", "투자 권유 아닙니다"]
_DISCLAIMER_FALLBACK = " ⚠️ 투자 참고 정보이며, 투자 권유가 아닙니다."


def _trim_str(text: str, max_len: int) -> str:
    """
    글자 수 초과 시 안전하게 트리밍.
    마지막 완성된 문장 경계에서 자름.
    """
    if len(text) <= max_len:
        return text
    truncated = text[: max_len - 1]
    # 마지막 문장 부호 기준으로 자름
    for sep in (".", "。", "!", "?", "다", "요"):
        idx = truncated.rfind(sep)
        if idx > max_len // 2:
            return truncated[: idx + 1]
    return truncated + "…"


def _ensure_disclaimer(text: str, max_len: int) -> str:
    """
    caption_x_final에 면책 고지 문구가 없으면 추가.
    max_len 제한 내에서 처리.
    """
    if any(p in text for p in _DISCLAIMER_PHRASES):
        return _trim_str(text, max_len)
    # 면책 고지 없으면 공간 확보 후 추가
    available = max_len - len(_DISCLAIMER_FALLBACK)
    trimmed = _trim_str(text, max(available, 0))
    result = trimmed + _DISCLAIMER_FALLBACK
    return result[:max_len]


def _auto_trim_raw_json(raw_json: dict) -> dict:
    """
    Pydantic 검증 전 글자 수 초과 필드 자동 트리밍.
    Claude가 제한을 넘긴 경우 검증 실패 없이 처리.
    """
    trimmed_fields: list[str] = []

    # 패널별 narration / key_text 트리밍
    for panel in raw_json.get("panels", []):
        for field, limit in [("narration", 120), ("key_text", 40)]:
            val = panel.get(field, "")
            if isinstance(val, str) and len(val) > limit:
                panel[field] = _trim_str(val, limit)
                trimmed_fields.append(f"panels[{panel.get('idx', '?')}].{field}")

    # 에피소드 레벨 필드 트리밍
    for field, limit in [
        ("logline", 100),
        ("caption_x_cover", 240),
    ]:
        val = raw_json.get(field, "")
        if isinstance(val, str) and len(val) > limit:
            raw_json[field] = _trim_str(val, limit)
            trimmed_fields.append(field)

    # caption_x_final — 면책 고지 보존하며 트리밍
    caption_final = raw_json.get("caption_x_final", "")
    if isinstance(caption_final, str) and len(caption_final) > 240:
        raw_json["caption_x_final"] = _ensure_disclaimer(caption_final, 240)
        trimmed_fields.append("caption_x_final")

    # caption_x_parts 각 항목 트리밍 (X Premium 기준 480자)
    parts = raw_json.get("caption_x_parts", [])
    if isinstance(parts, list):
        for i, part in enumerate(parts):
            if isinstance(part, str) and len(part) > 480:
                parts[i] = _trim_str(part, 480)
                trimmed_fields.append(f"caption_x_parts[{i}]")

    if trimmed_fields:
        logger.info("[claude] 자동 트리밍 적용: %s", ", ".join(trimmed_fields))

    return raw_json


def _extract_json(text: str) -> str:
    """Claude 응답에서 JSON 블록 추출."""
    fence_match = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", text)
    if fence_match:
        return fence_match.group(1).strip()
    text = text.strip()
    if text.startswith("{"):
        return text
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1:
        return text[start : end + 1]
    return text


def _validate_canon(script: EpisodeScript, scenario_type: str = "ONE_VS_ONE") -> None:
    """
    Canon 검증:
    1. char_id가 characters.yaml에 존재하는지 확인.
    2. villain role 캐릭터의 영문 이름이 6 Canon 리스트 내인지 확인.
    3. v2.0: NO_BATTLE 시나리오에서 villain role 캐릭터가 등장하지 않아야 함.

    Args:
        script:        검증할 EpisodeScript.
        scenario_type: "NO_BATTLE" 시 villain 패널 금지 검증 추가.
    """
    from pathlib import Path

    import yaml

    canon = yaml.safe_load(Path("config/characters.yaml").read_text(encoding="utf-8"))
    all_char_ids = set(canon.get("heroes", {}).keys()) | set(canon.get("villains", {}).keys())
    villain_map = {
        cid: entry.get("name_en", "") for cid, entry in canon.get("villains", {}).items()
    }

    for panel in script.panels:
        for char in panel.characters:
            # ── Canon ID 검증 ────────────────────────────────────────────────
            if char.char_id not in all_char_ids:
                raise ValueError(f"Canon 외 char_id 사용: {char.char_id}")

            # ── villain 이름 Canon 검증 ──────────────────────────────────────
            if char.role == "villain":
                # v2.0: NO_BATTLE에서 villain 등장 금지
                if scenario_type == "NO_BATTLE":
                    raise NarrativeValidationError(
                        attempt=0,
                        detail=(
                            f"NO_BATTLE 시나리오에서 villain role 캐릭터 등장 금지: "
                            f"panel={panel.idx} char_id={char.char_id}. "
                            "Claude가 Scenario 지시를 무시한 것으로 판단, 재생성 필요."
                        ),
                    )
                en_name = villain_map.get(char.char_id, "")
                if en_name and en_name not in _CANON_VILLAIN_NAMES:
                    raise InvalidVillainNameError(en_name)


def generate_episode(
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
) -> EpisodeScript:
    """
    Claude API를 호출하여 EpisodeScript를 생성.

    Args:
        date:          에피소드 날짜 (YYYY-MM-DD).
        episode_id:    에피소드 ID (예: ICG-2026-04-18-001).
        event_type:    이벤트 타입 (7종).
        delta:         시장 변화 데이터.
        battle_result: 전투 결과 dict (battle_calc 순수 함수 출력).
        hero_id:       히어로 캐릭터 ID.
        villain_id:    빌런 캐릭터 ID.
        arc_context:   에피소드 연속성 정보.
        scenario_type: v2.0 — "ONE_VS_ONE" | "NO_BATTLE" | "ALLIANCE" (기본: ONE_VS_ONE).
        ending_tone:   v2.0 — "OPTIMISTIC" | "TENSE" | "OMINOUS" (기본: TENSE).
        heroes:        v2.0 — 히어로 ID 리스트 (ALLIANCE=2개, 그 외=1개, 기본: [hero_id]).

    Returns:
        검증된 EpisodeScript 인스턴스.

    Raises:
        NarrativeValidationError: 3회 재시도 후에도 검증 실패 시.
    """
    if heroes is None:
        heroes = [hero_id]

    client = Anthropic()
    system_prompt = load_system_prompt()

    # ── render_user_prompt() 호출 — v2.0 파라미터 추가 ──────────────────────
    # render_user_prompt()가 **kwargs 또는 v2.0 파라미터를 수용하는 경우 직접 전달.
    # 그렇지 않으면 기존 파라미터만 전달하고 v2.0 정보를 user_prompt에 append.
    try:
        user_prompt = render_user_prompt(
            date=date,
            episode_id=episode_id,
            event_type=event_type,
            delta=delta,
            battle_result=battle_result,
            hero_id=hero_id,
            villain_id=villain_id,
            arc_context=arc_context,
            # v2.0 추가 파라미터
            scenario_type=scenario_type,
            ending_tone=ending_tone,
            heroes=heroes,
        )
    except TypeError:
        # render_user_prompt()가 v2.0 파라미터를 수용하지 못할 경우 fallback:
        # 기존 방식으로 호출 후 v2.0 컨텍스트를 문자열로 append.
        logger.warning(
            "[claude] render_user_prompt()가 v2.0 파라미터를 수용하지 못함 — "
            "기존 방식 fallback. prompt_tpl.py 업데이트를 권장합니다."
        )
        user_prompt = render_user_prompt(
            date=date,
            episode_id=episode_id,
            event_type=event_type,
            delta=delta,
            battle_result=battle_result,
            hero_id=hero_id,
            villain_id=villain_id,
            arc_context=arc_context,
        )
        # v2.0 컨텍스트를 직접 append
        _heroes_str = ", ".join(heroes)
        user_prompt += (
            f"\n\n## [v2.0 Scenario Override]\n"
            f"scenario_type: {scenario_type}\n"
            f"ending_tone: {ending_tone}\n"
            f"heroes: [{_heroes_str}]\n"
        )
        if scenario_type == "NO_BATTLE":
            user_prompt += (
                "\n⚠️ NO_BATTLE: DO NOT introduce any villain character in any panel.\n"
            )
        elif scenario_type == "ALLIANCE":
            user_prompt += (
                f"\n⚠️ ALLIANCE: 2 heroes ({_heroes_str}) vs 1 villain. "
                "Show alliance formation in panels 3-4.\n"
            )

    last_error: Exception | None = None

    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            logger.info(
                "[claude] 에피소드 생성 시도 %d/%d (scenario=%s)",
                attempt, _MAX_RETRIES, scenario_type,
            )

            # 재시도 시 에러 정보 + 글자수 가이드 추가
            if attempt > 1 and last_error:
                error_msg = str(last_error)
                retry_prompt = (
                    user_prompt
                    + f"\n\n## ⚠️ 이전 시도 오류 ({attempt - 1}회차) — 반드시 수정 후 재출력\n"
                    f"{error_msg}\n\n"
                    "## 글자 수 HARD LIMIT (초과 시 자동 실패)\n"
                    "- panels[].narration: 최대 **120자** (한국어)\n"
                    "- panels[].key_text: 최대 **40자** (한국어)\n"
                    "- caption_x_final: 최대 **240자** (면책 고지 포함)\n"
                    "- caption_x_cover: 최대 **240자**\n"
                    "- logline: 최대 **100자**\n\n"
                    "위 제한을 반드시 지키고 JSON만 반환하세요."
                )
                messages = [{"role": "user", "content": retry_prompt}]
            else:
                messages = [{"role": "user", "content": user_prompt}]

            # 3회차는 haiku로 fallback
            model = _MODEL_PRIMARY if attempt <= 2 else _MODEL_FALLBACK

            resp = client.messages.create(
                model=model,
                max_tokens=_MAX_TOKENS,
                system=system_prompt,
                messages=messages,
                temperature=_TEMPERATURE,
            )

            raw_text = resp.content[0].text
            json_str = _extract_json(raw_text)
            raw_json = json.loads(json_str)

            # 불변 필드 오버라이드
            raw_json["episode_id"] = episode_id
            raw_json["date"] = date
            raw_json["event_type"] = event_type

            # ── 자동 트리밍 (검증 전) ────────────────────────────────────
            raw_json = _auto_trim_raw_json(raw_json)

            script = EpisodeScript.model_validate(raw_json)

            # v2.0 scenario_type 전달하여 Canon 검증
            _validate_canon(script, scenario_type=scenario_type)

            usage = resp.usage
            logger.info(
                "[claude] 에피소드 생성 완료 (model=%s, scenario=%s, input=%d, output=%d)",
                model,
                scenario_type,
                usage.input_tokens,
                usage.output_tokens,
            )
            return script

        except Exception as exc:
            last_error = exc
            logger.warning("[claude] 시도 %d 실패: %s", attempt, exc)

    raise NarrativeValidationError(attempt=_MAX_RETRIES, detail=str(last_error))


def estimate_cost(input_tokens: int, output_tokens: int, model: str = _MODEL_PRIMARY) -> float:
    """Claude API 비용 추정 (USD)."""
    rates = {
        "claude-sonnet-4-6": (3.0, 15.0),
        "claude-haiku-4-5-20251001": (0.25, 1.25),
    }
    in_rate, out_rate = rates.get(model, (3.0, 15.0))
    return (input_tokens * in_rate + output_tokens * out_rate) / 1_000_000
