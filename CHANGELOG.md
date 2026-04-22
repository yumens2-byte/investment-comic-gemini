# ICG Character Engine v1.0.0 — 릴리즈 노트

## 날짜: 2026-04-22

## 테스트 결과
- ruff check: PASS × 2회 (line-length=100)
- pytest: 46/46 PASS × 2회
- GitHub 실제 레포 크로스 체크 완료 (curr_row 컬럼 정합)

---

## 신규 파일

### engine/character/
| 파일 | 설명 |
|------|------|
| `character_engine.py` | 4종 캐릭터 등장 조건 판단 (curr_row 기반) |
| `story_state_manager.py` | story_state_json 로드/저장 (icg_table() 패턴) |
| `prompt_builder.py` | 게스트 캐릭터 Claude 프롬프트 빌더 |

### scripts/
| 파일 | 설명 |
|------|------|
| `run_market_step3_story.py` | step_analysis() Step 3-Story 삽입 독립 모듈 |

### engine/narrative/
| 파일 | 설명 |
|------|------|
| `prompt_tpl_patch.py` | prompt_tpl.py 수정 가이드 (guest_character_prompt 추가) |

---

## 영역별 캐릭터 지원 현황

| 캐릭터 | 데이터 | 상태 | 트리거 조건 |
|--------|--------|------|------------|
| SENTINEL YIELD | us10y, yield_curve | ✅ 활성 | yield_curve<-0.5 또는 us10y≥4.5% |
| CRYPTO SHADE | crypto_basis_state, btc_sentiment_state | ✅ 활성 | state 불일치 또는 극단 상태 |
| SECTOR PHANTOM | top_etf_ticker, etf_ranks | ⏸️ 대기 | daily_snapshots에 ETF 데이터 없음 |
| MOMENTUM RIDER | spy_sma50, spy_sma200 | ⏸️ 대기 | daily_snapshots에 SMA 데이터 없음 |

---

## GitHub 반영 순서

### Step 1: engine/character/ 신규 파일 3개 업로드
```
engine/character/__init__.py  (빈 파일)
engine/character/character_engine.py
engine/character/story_state_manager.py
engine/character/prompt_builder.py
```

### Step 2: scripts/ 파일 1개 업로드
```
scripts/run_market_step3_story.py
```

### Step 3: engine/narrative/prompt_tpl.py 수정
prompt_tpl_patch.py의 가이드 참조:
- render_user_prompt()에 guest_character_prompt: str = "" 파라미터 추가
- template.render()에 guest_character_prompt=guest_character_prompt 추가

### Step 4: scripts/run_market.py Step 3-Story 삽입
```python
# analysis_upsert() 완료 직후, ctx = {...} 조립 직전
_guest_prompt, _story_state, _guest_characters = ("", {}, [])
try:
    from scripts.run_market_step3_story import run_step3_story
    _guest_prompt, _story_state, _guest_characters = run_step3_story(
        curr_row=curr_row, episode_date=episode_date
    )
except Exception as _e:
    logger.warning("[Step 3-Story] 실패 (계속): %s", _e)

# ctx = { ... } 에 추가:
"guest_character_prompt": _guest_prompt,
"_story_state": _story_state,
"_guest_characters": _guest_characters,
```

### Step 5: step_narrative/persist 완료 후 저장
```python
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
    logger.warning("[Step 3-Story-Save] 실패 (계속): %s", _e)
```

### Step 6: pyproject.toml known-first-party 확인
```toml
[tool.ruff.lint.isort]
known-first-party = ["engine", "scripts"]
```

---

## Supabase (적용 완료)
```sql
-- icg.daily_analysis 컬럼 (이미 적용)
story_state_json JSONB
```
