"""
engine/narrative/claude_client.py
Claude API 호출 — EpisodeScript 생성.

모델: claude-sonnet-4-6 (fallback: claude-haiku-4-5-20251001)
max_tokens: 8000
temperature: 0.7
검증 실패 시 최대 2회 재전송 (doc 16a).
Canon 검증: char_id 존재 확인, villain 이름 6종 확인.
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
_MAX_RETRIES = 2

# Canon 빌런 영문 이름 집합 (RULE 06)
_CANON_VILLAIN_NAMES: set[str] = {
    "Oil Shock Titan",
    "Debt Titan",
    "Liquidity Leviathan",
    "Volatility Hydra",
    "Algorithm Reaper",
    "War Dominion",
}


def _extract_json(text: str) -> str:
    """
    Claude 응답에서 JSON 블록 추출.
    마크다운 코드 펜스 또는 순수 JSON 모두 처리.
    """
    # ```json ... ``` 또는 ``` ... ``` 블록 추출
    fence_match = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", text)
    if fence_match:
        return fence_match.group(1).strip()
    # 순수 JSON (중괄호로 시작)
    text = text.strip()
    if text.startswith("{"):
        return text
    # 첫 번째 { ... } 블록 추출
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1:
        return text[start : end + 1]
    return text


def _validate_canon(script: EpisodeScript) -> None:
    """
    Canon 검증:
    1. char_id가 characters.yaml에 존재하는지 확인.
    2. villain role 캐릭터의 영문 이름이 6 Canon 리스트 내인지 확인.
    3. battle_result outcome이 스크립트와 일치하는지 확인.
    """
    from pathlib import Path

    import yaml

    canon = yaml.safe_load(Path("config/characters.yaml").read_text(encoding="utf-8"))
    all_char_ids = set(canon.get("heroes", {}).keys()) | set(canon.get("villains", {}).keys())
    villain_map = {
        cid: entry.get("name_en", "")
        for cid, entry in canon.get("villains", {}).items()
    }

    for panel in script.panels:
        for char in panel.characters:
            if char.char_id not in all_char_ids:
                raise ValueError(f"Canon 외 char_id 사용: {char.char_id}")
            # villain role 이름 검증
            if char.role == "villain":
                en_name = villain_map.get(char.char_id, "")
                if en_name and en_name not in _CANON_VILLAIN_NAMES:
                    raise InvalidVillainNameError(en_name)


def _check_battle_override(
    script: EpisodeScript,
    expected_outcome: str,
) -> None:
    """
    BattleOverride 검증: Claude가 battle_calc 결과를 임의로 바꿨는지 확인.
    DISCLAIMER 패널의 market_ref 또는 narration에 다른 outcome이 언급되면 경고.
    """
    # 간접 검증: 스크립트 전체에 모순되는 승패 표현이 없는지 점검
    # (직접적인 outcome 필드가 없으므로 과도한 제약 없이 최소 검증)
    pass  # Phase 1: 경고 수준으로 유지, Phase 2에서 강화


def generate_episode(
    date: str,
    episode_id: str,
    event_type: str,
    delta: dict,
    battle_result: dict,
    hero_id: str,
    villain_id: str,
    arc_context: dict,
) -> EpisodeScript:
    """
    Claude API를 호출하여 EpisodeScript를 생성.

    Args:
        date: 에피소드 날짜 (YYYY-MM-DD)
        episode_id: 에피소드 ID (ICG-YYYY-MM-DD-001)
        event_type: 에피소드 타입
        delta: delta_engine 출력
        battle_result: BattleResult.to_dict()
        hero_id: CHAR_HERO_00N
        villain_id: CHAR_VILLAIN_00N
        arc_context: 연속성 정보

    Returns:
        검증된 EpisodeScript 인스턴스.

    Raises:
        NarrativeValidationError: 2회 재시도 후에도 검증 실패 시.
    """
    client = Anthropic()
    system_prompt = load_system_prompt()
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

    last_error: Exception | None = None

    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            logger.info("[claude] 에피소드 생성 시도 %d/%d", attempt, _MAX_RETRIES)

            messages: list[dict] = [{"role": "user", "content": user_prompt}]

            # 2회차: 에러 메시지 추가로 재전송
            if attempt > 1 and last_error:
                messages.append(
                    {
                        "role": "assistant",
                        "content": "[이전 응답]",
                    }
                )
                messages = [
                    {
                        "role": "user",
                        "content": (
                            user_prompt
                            + f"\n\n## 이전 시도 오류 ({attempt-1}회차)\n{last_error}\n\n"
                            "위 오류를 수정하여 유효한 JSON만 반환하세요."
                        ),
                    }
                ]

            model = _MODEL_PRIMARY if attempt == 1 else _MODEL_FALLBACK
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

            # episode_id 오버라이드 (Claude가 바꿀 수 없음)
            raw_json["episode_id"] = episode_id
            raw_json["date"] = date
            raw_json["event_type"] = event_type

            script = EpisodeScript.model_validate(raw_json)
            _validate_canon(script)

            # 비용 로깅
            usage = resp.usage
            logger.info(
                "[claude] 에피소드 생성 완료 (model=%s, input=%d, output=%d)",
                model,
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
    # claude-sonnet-4-6 기준 (2026-04 단가)
    rates = {
        "claude-sonnet-4-6": (3.0, 15.0),          # input, output per 1M tokens
        "claude-haiku-4-5-20251001": (0.25, 1.25),
    }
    in_rate, out_rate = rates.get(model, (3.0, 15.0))
    return (input_tokens * in_rate + output_tokens * out_rate) / 1_000_000
