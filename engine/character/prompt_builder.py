"""
engine/character/prompt_builder.py
ICG 게스트 캐릭터 Claude 프롬프트 빌더

적용 대상: engine/narrative/prompt_tpl.py render_user_prompt()에 주입
"""
from __future__ import annotations

import logging

VERSION = "1.0.0"

logger = logging.getLogger(__name__)

_HEADER = """
## 오늘 등장하는 게스트 캐릭터

{guest_block}

### 게스트 등장 규칙
1. 게스트는 메인 전투(히어로 vs 빌런)와 별개로 짧게 등장한다.
2. 게스트 대사는 해당 시장 지표 의미를 자연스럽게 담는다.
3. ABSENT 캐릭터는 언급하지 않는다.
4. 게스트 2명 이상 시: 첫 번째가 주연, 나머지는 배경 대사 1줄만.
"""

_YIELD_BLOCK = """SENTINEL YIELD 📈 (역할: {role})
현재 US10Y: {us10y:.2f}% | Yield Curve: {yield_curve:.3f}
행동:
  ARBITRATOR → 전장 중립지대 선언, 양측 공격 일시 중단
  WARNER     → 히어로·빌런 모두에게 고금리 위험 경고
  OBSERVER   → 배경 대사만 ("금리가 심상치 않다...")"""

_SHADE_BLOCK = """CRYPTO SHADE 🌑 (역할: {role})
BTC Basis: {basis_state} | Sentiment: {sentiment_state}
행동:
  DOUBLE_AGENT → 양측에 모순 정보 각각 판매
  BROKER       → 유리한 쪽에 Basis 정보 팔고 퇴장
  INFORMANT    → Sentiment 정보 유출 후 그림자 속으로"""


def build_guest_character_prompt(
    curr_row: dict,
    prev_story_state: dict,
    guest_characters: list[tuple[str, str]],
) -> str:
    """
    게스트 캐릭터 Claude 프롬프트 블록 생성.

    Args:
        curr_row: daily_snapshots 최신 행
        prev_story_state: 전날 story_state_json
        guest_characters: resolve_guest_characters() 반환값

    Returns:
        render_user_prompt()의 guest_character_prompt 파라미터에 주입할 문자열
    """
    if not guest_characters:
        return ""

    primary_code, primary_role = guest_characters[0]
    secondary = guest_characters[1:]

    primary_block = _build_single_block(primary_code, primary_role, curr_row)

    if secondary:
        secondary_lines = "\n".join(
            f"- {code}: 배경 등장 ({role})" for code, role in secondary
        )
        primary_block += f"\n\n### 배경 캐릭터 (대사 1줄)\n{secondary_lines}"

    return _HEADER.format(guest_block=primary_block)


def _build_single_block(char_code: str, role: str, curr_row: dict) -> str:
    if char_code == "SENTINEL_YIELD":
        return _YIELD_BLOCK.format(
            role=role,
            us10y=curr_row.get("us10y") or 0.0,
            yield_curve=curr_row.get("yield_curve") or 0.0,
        )
    if char_code == "CRYPTO_SHADE":
        return _SHADE_BLOCK.format(
            role=role,
            basis_state=curr_row.get("crypto_basis_state", "Unknown"),
            sentiment_state=curr_row.get("btc_sentiment_state", "Unknown"),
        )
    return f"# {char_code} ({role})"
