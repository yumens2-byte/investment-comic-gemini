"""
engine/narrative/prompt_tpl_patch.py
prompt_tpl.py에 guest_character_prompt 파라미터 추가 패치

적용 방법:
  engine/narrative/prompt_tpl.py에서 아래 2곳 수정

[수정 1] render_user_prompt() 파라미터 끝에 추가:
    guest_character_prompt: str = "",  # 신규 (2026-04-22)

[수정 2] template.render() 호출에 추가:
    guest_character_prompt=guest_character_prompt,  # 신규

전체 diff:
"""

PATCH_DESCRIPTION = """
# engine/narrative/prompt_tpl.py 수정 가이드

## 수정 위치 1: render_user_prompt() 파라미터 마지막에 추가

    # 기존 마지막 파라미터 (heroes) 다음에 추가:
    heroes: list[str] | None = None,
    # ▼ 신규 추가 ▼
    guest_character_prompt: str = "",  # 신규 캐릭터 프롬프트 블록

## 수정 위치 2: template.render() 호출 마지막에 추가

    return template.render(
        # ... 기존 파라미터들 ...
        hero_ids=heroes,
        # ▼ 신규 추가 ▼
        guest_character_prompt=guest_character_prompt,  # 게스트 캐릭터 블록
    )

## 결과

render_user_prompt()가 guest_character_prompt를 받아 Jinja2 템플릿에 주입.
Notion 템플릿에 {{ guest_character_prompt }} 추가 시 소설 프롬프트에 자동 삽입.
"""

# 실제 패치 적용 코드 (run_market.py Step 3-Story에서 호출)
PROMPT_TPL_RENDER_ADDITION = "guest_character_prompt=guest_character_prompt,"
PROMPT_TPL_PARAM_ADDITION = 'guest_character_prompt: str = "",  # 2026-04-22 신규'
