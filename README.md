# 🍌 Investment Comic Gemini (ICG)

한국 시장 데이터 → Claude 서사 → Gemini 이미지 → PIL 조립 → X/Telegram 자동 발행 파이프라인.

## 시스템 구성

| 레이어 | 기술 | 역할 |
|--------|------|------|
| L0 스케줄러 | GitHub Actions (cron `0 4 * * *` UTC) | KST 13:00 일일 자동 실행 |
| L1 데이터 | FRED API + yfinance + LunarCrush + Crypto.com + CNN F&G | 시장 지표 수집 |
| L2 분석 | Python (결정론적) | Delta, Event 분류, Battle 계산 |
| L3 내러티브 | Claude API (claude-sonnet-4-6) | 에피소드 스크립트 JSON 생성 |
| L4 이미지 | Gemini API (gemini-2.5-flash-image) | REF 이미지 주입, 패널 생성 |
| L5 조립 | Python PIL | 1080×1350 슬라이드 조립 |
| L6 발행 | X API v2 + Telegram Bot API | 수동 승인 게이트 후 발행 |

## 실행

```bash
# STEP 2~6 전체
python -m scripts.run_market --stage all --date 2026-04-14

# 단계별
python -m scripts.run_market --stage data
python -m scripts.run_market --stage analysis
python -m scripts.run_market --stage narrative
python -m scripts.run_market --stage persist
python -m scripts.run_market --stage image

# STEP 7: PIL 조립 (dialog 주입 후)
python -m scripts.run_resume --episode ICG-2026-04-14-001

# STEP 8: 발행 (수동 게이트)
python -m scripts.run_publish --episode ICG-2026-04-14-001 --channels telegram
```

## 환경변수

`.env.example` 참조. GitHub Secrets 등록 기준:

| 변수 | 용도 |
|------|------|
| `ANTHROPIC_API_KEY` | Claude API |
| `GEMINI_API_SUB_PAY_KEY` | Gemini API |
| `SUPABASE_URL` | Supabase URL |
| `SUPABASE_KEY` | Supabase service_role key |
| `NOTION_API_KEY` | Notion 통합 토큰 |
| `FRED_API_KEY` | St. Louis Fed |
| `LUNAR_CRUSH_API_KEY` | LunarCrush 소셜 |
| `X_API_KEY` / `X_API_SECRET` | X 앱 자격증명 |
| `X_ACCESS_TOKEN` / `X_ACCESS_TOKEN_SECRET` | X 사용자 토큰 |
| `TELEGRAM_BOT_TOKEN` | Telegram Bot |
| `TELEGRAM_FREE_CHANNEL_ID` | TG 무료 채널 |
| `TELEGRAM_PAID_CHANNEL_ID` | TG 유료 채널 |
| `DRY_RUN` | `true` = 모의 발행 |

## 테스트

```bash
python -m pytest tests/ -v
```

## 핵심 원칙

- **Battle 결과 불변**: `battle_calc.py` 결정론적 수식 출력 → Claude가 수정 불가
- **Canon Lock**: `config/characters.yaml` SHA256 검증 — REF 이미지 변조 차단
- **SECURITY NEGATIVE BLOCK v1.1**: 모든 Gemini 프롬프트 자동 주입
- **DisclaimerMissing**: 면책 고지 미포함 시 발행 차단
- **수동 발행 게이트**: `publish_sns.yml` + `confirm=YES` + `production` environment 승인

## Supabase 스키마

`icg` 스키마 (10 테이블):
`daily_snapshots`, `daily_analysis`, `daily_news`, `daily_alerts`,
`episode_context`, `published_comics`, `comic_novels`, `api_cache`,
`episode_assets`, `run_logs`

## 문서

Notion ICG Hub: `3429208c-bdc3-81c9-b60b-f3f32341e963`
