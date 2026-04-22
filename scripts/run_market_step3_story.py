"""
scripts/run_market_step3_story.py
step_analysis() Step 3-Story 삽입 코드 (독립 모듈)

적용 방법:
  scripts/run_market.py → step_analysis() 내부
  analysis_upsert() 호출 완료 직후 + ctx 조립 직전에 삽입

삽입 위치 탐색:
  "analysis_upsert(episode_date, event_type, battle_result.to_dict(), delta, arc_context)"
  이 줄 바로 아래에 run_step3_story() 호출 추가.

  ctx = { ... } 조립 블록에 아래 3개 키 추가:
    "guest_character_prompt": _guest_prompt,
    "_story_state": _story_state,
    "_guest_characters": _guest_characters,

  step_analysis() 반환값 사용 후 (main() 또는 step_narrative 호출 전):
    save_step3_story_state(episode_date, ctx)
"""
from __future__ import annotations

import logging

VERSION = "1.0.0"

logger = logging.getLogger(__name__)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Step 3-Story 실행 함수
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def run_step3_story(
    curr_row: dict,
    episode_date: str,
    prev_story_state: dict | None = None,
) -> tuple[str, dict, list]:
    """
    Step 3-Story: 게스트 캐릭터 판단 + 프롬프트 블록 생성.

    step_analysis() 내부에서 analysis_upsert() 완료 직후 호출.

    Args:
        curr_row: daily_snapshots 최신 행 (delta 계산에 사용된 curr_row)
        episode_date: 오늘 날짜 (YYYY-MM-DD)
        prev_story_state: 전날 story_state (None이면 자동 로드)

    Returns:
        (guest_prompt_block, story_state, guest_characters)
        실패 시 ("", {}, [])
    """
    logger.info("[Step 3-Story] v%s 게스트 캐릭터 판단 시작", VERSION)

    try:
        from engine.character.character_engine import resolve_guest_characters
        from engine.character.prompt_builder import build_guest_character_prompt
        from engine.character.story_state_manager import load_story_state

        if prev_story_state is None:
            prev_story_state = load_story_state(episode_date)

        guest_characters = resolve_guest_characters(curr_row, prev_story_state)

        guest_prompt = build_guest_character_prompt(
            curr_row, prev_story_state, guest_characters
        )

        logger.info(
            "[Step 3-Story] 완료: 게스트 %d명 %s",
            len(guest_characters),
            [f"{c}({r})" for c, r in guest_characters] or ["없음"],
        )
        return guest_prompt, prev_story_state, guest_characters

    except Exception as e:
        logger.warning("[Step 3-Story] 실패 (파이프라인 계속): %s", e)
        return "", {}, []


def save_step3_story_state(
    episode_date: str,
    outcome: str,
    vix: float,
    story_state: dict,
    guest_characters: list[tuple[str, str]],
) -> None:
    """
    에피소드 완료 후 story_state 저장.

    main() 또는 step_persist 완료 직후 호출.

    Args:
        episode_date: 오늘 날짜 (YYYY-MM-DD)
        outcome: battle_result["outcome"] 값
        vix: curr_row["vix"] 값
        story_state: run_step3_story() 반환값
        guest_characters: run_step3_story() 반환값
    """
    if not story_state:
        return

    try:
        from engine.character.story_state_manager import (
            save_story_state,
            update_after_episode,
        )

        updated = update_after_episode(
            story_state, guest_characters, outcome, vix
        )
        save_story_state(episode_date, updated)

        logger.info(
            "[Step 3-Story-Save] 저장 완료 (arc_ep=%d, rift=%d%%)",
            updated.get("arc_episode", 0),
            updated.get("world_state", {}).get("dimensional_rift_progress", 0),
        )

    except Exception as e:
        logger.warning("[Step 3-Story-Save] 저장 실패 (영향 없음): %s", e)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# scripts/run_market.py 삽입 코드 (복사해서 붙여넣기용)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

STEP3_STORY_INSERTION = '''
        # ── STEP 3-Story: 게스트 캐릭터 판단 (2026-04-22) ──────────────────────
        _guest_prompt = ""
        _story_state: dict = {}
        _guest_characters: list = []
        try:
            from scripts.run_market_step3_story import run_step3_story
            _guest_prompt, _story_state, _guest_characters = run_step3_story(
                curr_row=curr_row,
                episode_date=episode_date,
            )
        except Exception as _e:
            logger.warning("[Step 3-Story] 실패 (파이프라인 계속): %s", _e)
        # ────────────────────────────────────────────────────────────────────────
'''

# ctx 조립 블록에 추가할 키 (기존 ctx = { ... } 에 아래 3개 추가)
CTX_ADDITIONS = {
    "guest_character_prompt": "_guest_prompt",
    "_story_state": "_story_state",
    "_guest_characters": "_guest_characters",
}

# step_narrative 완료 직후 save 호출 코드
STEP3_STORY_SAVE_INSERTION = '''
        # ── STEP 3-Story-Save: story_state 저장 ──────────────────────────────────
        try:
            from scripts.run_market_step3_story import save_step3_story_state
            save_step3_story_state(
                episode_date=episode_date,
                outcome=ctx["battle_result"].get("outcome", "DRAW"),
                vix=curr_row.get("vix") or 0.0,
                story_state=ctx.get("_story_state", {}),
                guest_characters=ctx.get("_guest_characters", []),
            )
        except Exception as _e:
            logger.warning("[Step 3-Story-Save] 실패 (파이프라인 계속): %s", _e)
        # ────────────────────────────────────────────────────────────────────────
'''
