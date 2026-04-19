# ICG Video Track — Phase V1 Infrastructure

> **버전**: v1.0.0 (2026-04-19)
> **소속**: Investment Comic Gemini (ICG) 프로젝트
> **역할**: 24초 뉴스형 히어로 vs 빌런 예고편 자동 생성 트랙
> **모델**: Google Veo 3.1 Lite (1080p, 9:16, 8s × 3cut)
> **발행 주기**: 주 1회 토요일 KST 09:00

## 📁 디렉토리 구조

```
investment-comic-gemini/ (기존 레포 루트)
├── .github/workflows/
│   └── run_video_trailer.yml     ← 신규: 토요일 cron 트리거
├── scripts/
│   └── run_video_trailer.py      ← 신규: stage 분기 메인
├── engine/video/                 ← 신규 패키지 전체
│   ├── __init__.py
│   ├── veo_client.py             ← Veo 3.1 Lite API 래퍼
│   ├── frame_extractor.py        ← FFmpeg 프레임 추출
│   ├── ffmpeg_composer.py        ← concat + 최종 렌더링
│   ├── audio_overlay.py          ← TTS + BGM + SFX 믹싱
│   ├── subtitle_renderer.py      ← ASS 자막 + burn-in
│   └── i2v_chain.py              ← 3컷 I2V 체이닝 오케스트레이터
├── engine/publish/               ← 기존 패키지에 신규 파일만 추가 (⚠️ __init__.py 기존 유지)
│   ├── telegram_gate.py          ← [신규] PAUSE 게이트 (마스터 개인 TG 승인)
│   ├── telegram_video_publisher.py ← [신규] TG 무료/유료 채널 영상 발행 (이미지용 telegram_publisher.py와 별개)
│   ├── x_video_publisher.py      ← [신규] X 영상 chunked upload (이미지용 x_publisher.py와 별개)
│   └── youtube_shorts_publisher.py ← [신규] YouTube Shorts API
├── config/prompts/
│   └── video_scenario.j2         ← 신규: Claude 시나리오 템플릿 (CHARACTER LOCK 포함)
├── assets/characters/            ← 신규: 캐릭터 REF 이미지 (향후 추가)
│   └── .gitkeep
├── output/videos/                ← 런타임 생성 산출물 (gitignore)
│   └── .gitkeep
└── requirements-video.txt        ← 신규: 영상 트랙 전용 의존성
```

## ⚠️ Strict Isolation 원칙

영상 트랙은 기존 **이미지 트랙(ICG 이미지 파이프라인)과 완전 격리**로 운영됩니다.

- 기존 코드/DB/워크플로/프롬프트 파괴적 변경 **0건**
- `engine/image/*`, `engine/assembly/*` 호출 **금지**
- 데이터는 공유 (icg.daily_snapshots, icg.daily_analysis 읽기만)
- 출력은 독립 (icg.video_assets 신규 테이블)

## 🔀 기존 레포 자산과의 관계 (2026-04-19 검증 완료)

### 재사용 가능 (import OK — Strict Isolation 허용)

| 기존 모듈 | 영상 트랙에서의 용도 |
|-----------|-------------------|
| `engine/common/supabase_client.py` | DB 연결 (공용) |
| `engine/common/logger.py` | 로거 (공용) |
| `engine/common/retry.py` | 재시도 데코레이터 |
| `engine/common/notion_loader.py` | Notion API (공용) |
| `engine/data/market_fetcher.py` | 시장 데이터 수집 |
| `engine/data/fred_fetcher.py` | FRED 지표 수집 |
| `engine/analysis/reader.py` | Supabase 스냅샷 조회 |
| `engine/narrative/scenario_selector.py` | Scenario 선택 로직 |
| `engine/narrative/battle_calc.py` | Battle 계산 |
| `assets/characters/*.png` | **REF 이미지 12장 이미 존재** → Nano Banana 생성 불필요 |

### 호출 금지 (Strict Isolation)

| 금지 모듈 | 이유 |
|----------|------|
| `engine/image/*` | 이미지 생성 (Gemini 2.5 Flash Image) — 영상 트랙과 분리 |
| `engine/assembly/*` | PIL 슬라이드 조립 — 영상 트랙은 FFmpeg 사용 |

### 파일명 충돌 회피 (중요)

기존 레포에 **이미지 슬라이드용 발행 모듈**이 이미 존재합니다. 영상 트랙에서는 **별도 파일명**으로 분리했습니다.

| 기존 (이미지 트랙, 수정 금지) | 신규 (영상 트랙) |
|----------------------------|------------------|
| `engine/publish/telegram_publisher.py` (슬라이드 media group 발행) | `engine/publish/telegram_video_publisher.py` (영상 발행) |
| `engine/publish/x_publisher.py` (슬라이드 발행) | `engine/publish/x_video_publisher.py` (영상 chunked upload) |
| `engine/publish/__init__.py` (빈 파일 유지) | ❌ **zip에 포함되지 않음 — 기존 파일 보존** |
| `engine/publish/history_writer.py` | 수정 없음, 필요 시 영상 트랙도 재사용 가능 |

## 🎨 기존 REF 이미지 활용 (Phase V2 I2V 체이닝 테스트용)

Veo 3.1 Lite I2V 체이닝 테스트 시 **새로 생성할 필요 없이 아래 이미지 즉시 사용**:

| 컷 | 필요 캐릭터 | 파일 경로 | 비고 |
|----|-----------|---------|------|
| 컷1 | Iron Securities Nuna (앵커) | `assets/characters/hero_iron_securities_nuna.png` | T2V 생성 후 참고용 |
| 컷2 빌런 | Algorithm Reaper | `assets/characters/villain_algorithm_reaper.png` | Veo I2V 시작 프레임 후보 |
| 컷2/3 히어로 | EDT Form 0 / Form 1 | `assets/characters/hero_edt_form0.png`<br>`assets/characters/hero_edt_form1.png` | Veo I2V 또는 Reference Image |
| 기타 빌런 6종 | Debt Titan / Oil Shock / Liquidity / Volatility / War Dominion / Algorithm Reaper | `assets/characters/villain_*.png` | 향후 다양한 시나리오용 |

**Nano Banana REF 이미지 생성 비용 절약**: $0 (이미 존재)

## 🚀 배포 순서

### 1. 파일 업로드 (14개 — ⚠️ `__init__.py` 제외)

아래 14개 파일을 `investment-comic-gemini` 레포의 동일 경로에 업로드.

**🚫 절대 업로드 금지**: `engine/publish/__init__.py` (zip에서도 제외됨, 기존 빈 파일 그대로 유지)

**✅ 업로드 대상 14개**:

```
.github/workflows/run_video_trailer.yml
scripts/run_video_trailer.py
engine/video/__init__.py
engine/video/veo_client.py
engine/video/frame_extractor.py
engine/video/ffmpeg_composer.py
engine/video/audio_overlay.py
engine/video/subtitle_renderer.py
engine/video/i2v_chain.py
engine/publish/telegram_gate.py           # 신규 파일 (__init__.py 덮어쓰기 금지!)
engine/publish/telegram_video_publisher.py
engine/publish/x_video_publisher.py
engine/publish/youtube_shorts_publisher.py
config/prompts/video_scenario.j2
requirements-video.txt
README_VIDEO_TRACK.md
```

### 2. GitHub Secrets 등록 (5개 필수 + 3개 선택)

| Secret | 용도 | 필수 |
|--------|------|------|
| `GEMINI_API_PAY_KEY` | Veo Paid Tier 호출 | 필수 |
| `TELEGRAM_BOT_TOKEN` | 봇 토큰 (Gate + 채널 발행 공용) | 필수 |
| `MASTER_CHAT_ID` | PAUSE 게이트 대상 (마스터 개인) | 필수 |
| `TELEGRAM_FREE_CHANNEL_ID` | 무료 채널 (@EDT_INVESTMENT 등) | 필수 |
| `TELEGRAM_PAID_CHANNEL_ID` | 유료 채널 | 필수 |
| `VIDEO_BUDGET_USD_MONTHLY` | Budget Cap 값: `80` | 선택 (기본값 80) |
| `YOUTUBE_CLIENT_ID` | Shorts 업로드 | Phase V5부터 |
| `YOUTUBE_CLIENT_SECRET` | Shorts 업로드 | Phase V5부터 |
| `YOUTUBE_REFRESH_TOKEN` | Shorts 업로드 | Phase V5부터 |

### 3. Supabase 테이블 확인

`icg.video_assets` 테이블 이미 생성 완료 (2026-04-19). 확인 SQL:

```sql
SELECT column_name, data_type FROM information_schema.columns
WHERE table_schema = 'icg' AND table_name = 'video_assets'
ORDER BY ordinal_position;
```

### 4. 첫 실행 (dry_run)

GitHub Actions → `Run Video Trailer (ICG Video Track)` → Run workflow → `dry_run: true`

기대 로그:
```
[run_video_trailer] v1.0.0 시작
[run_video_trailer] DRY_RUN=true — no external API calls
[1V] scheduler / holiday / budget check
[2V] load snapshot + analysis (read-only)
[2V] target date: 2026-04-19
[3V] scenario selection
[3V] scenario: ONE_VS_ONE
...
[PAUSE] awaiting master approval — workflow ends here
[run_video_trailer] stage=gate_notify 완료
```

## 📋 Phase V1 체크리스트

- [x] Supabase `icg.video_assets` 테이블 생성 (18컬럼)
- [x] 기존 레포 구조 검증 완료 (충돌 파일 2건 해결)
- [ ] 14개 파일 GitHub 업로드 (⚠️ `engine/publish/__init__.py` 제외)
- [ ] GitHub Secrets 5개 등록 (GEMINI_API_PAY_KEY, TELEGRAM_BOT_TOKEN, MASTER_CHAT_ID, TELEGRAM_FREE_CHANNEL_ID, TELEGRAM_PAID_CHANNEL_ID)
- [ ] workflow_dispatch dry_run 실행 성공
- [ ] 로그에서 `[run_video_trailer] v1.0.0 시작` 확인
- [ ] 각 stage가 오류 없이 스킵/로그 출력 확인
- [ ] 기존 이미지 트랙 `run_market.yml` 정상 동작 재확인 (회귀 테스트)
- [ ] Phase V2 착수 승인 대기

## 🎬 Phase V1→V6 로드맵

| Phase | 내용 | 기간 |
|-------|------|------|
| **V1** | 인프라 (현재) — 스켈레톤 + DB + Secrets | Week 1 |
| V2 | Veo 연동 실증 — veo_client.py 구현 | Week 2 |
| V3 | I2V 체이닝 검증 — i2v_chain.py 연동 | Week 3 |
| V4 | 조립 완성 — FFmpeg + TTS + 자막 | Week 4 |
| V5 | 발행 레이어 — X/Shorts + Telegram 게이트 | Week 5 |
| V6 | 안정화 — 주 1회 정기 운영 전환 | Week 6+ |

## 💰 비용 예상 (v1.1 확정)

| 항목 | 주 1회 × 4주 |
|------|------------|
| Veo 성공 | $7.68/월 |
| Worst Case (재시도 4배) | $30.72/월 |
| TTS | ~$0.40/월 |
| Claude 시나리오 | ~$0.08/월 |
| **총 예산** | **$80/월 (여유 61%)** |

## 🔗 관련 문서 (Notion)

- [21 Master Spec v1.1](https://www.notion.so/3479208cbdc38120be57ed95796fea20)
- [21a Pipeline Branch](https://www.notion.so/3479208cbdc3812f94ffd1f4f087a121)
- [21b Veo Prompt Spec](https://www.notion.so/3479208cbdc381fdacf2f57293b83c76)
- [21c Character Reference for Veo](https://www.notion.so/3479208cbdc381e9b726e306abc83720)
- [21d FFmpeg Assembly](https://www.notion.so/3479208cbdc38160adcfec1904265fc7)
- [21e X Video + YouTube Shorts](https://www.notion.so/3479208cbdc3812cb66cc47ddcf4563d)
- [21f Code Skeletons (이 문서)](https://www.notion.so/3479208cbdc381d69799d8a9a45cf3a2)
- [21g Veo Test Prompts v1+v2](https://www.notion.so/3479208cbdc3814289b1c090031c103c)

## 📝 라이선스

Investment OS + ICG 내부 자산. 외부 공개 금지.
