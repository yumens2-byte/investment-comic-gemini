# 미국장 기반 히어로 유니버스 자동 X 발행 플로우 전수 점검 (2026-06-04)

## 1. 점검 범위

- 대상 시스템: 미국장/매크로 데이터 수집 → 이벤트 분류 → 히어로/빌런/전투 산식 → Claude 내러티브 → Gemini 이미지 → PIL 슬라이드 조립 → X/Telegram 발행 자동화.
- 핵심 진입점:
  - `scripts/run_market.py`: STEP 2~6 데이터/분석/서사/저장/이미지 생성.
  - `scripts/run_resume.py`: STEP 7 PIL 조립.
  - `scripts/run_publish.py`: STEP 8 SNS 발행.
  - `.github/workflows/run_market.yml`, `resume_episode.yml`, `publish_sns.yml`: 스케줄/수동 실행 오케스트레이션.
- 검증 명령: `python -m pytest tests/ -q` 기준 전체 테스트 통과.
- 추가 재검토: 데이터 미수집 시 3회 재시도 적용 여부와 critical data 누락 시 발행 중단 구성을 별도 확인했다.

## 2. 전체 흐름 요약

| 단계 | 담당 | 현재 동작 | 흐름 상태 |
|---|---|---|---|
| STEP 2 데이터 수집 | `step_data()` | FRED, yfinance, Fear & Greed, crypto basis, LunarCrush, 선택적 sector 확장 데이터를 모아 `daily_snapshots`에 upsert | yfinance/F&G/Crypto/FRED 주요 호출은 3회 재시도, critical 누락 시 중단 게이트 적용 |
| STEP 3 분석/Battle | `step_analysis()` | 최신 snapshot 2개로 delta 산출, event type 분류, 캐릭터 선택, battle 계산, `daily_analysis`와 `analysis_ctx_json` 저장 | 동작하나 날짜 지정 stage에서 최신 snapshot을 읽는 블랙박스 존재 |
| STEP 4 내러티브 | `step_narrative()` | DB 복원 ctx 또는 직전 ctx로 Claude 스토리 생성, 품질 게이트 검증 | 동작 |
| STEP 5 적재 | `step_persist()` | `episode_assets`, Notion 미러, story/arc 상태 갱신 | 동작하나 status/event key 혼선 위험 |
| STEP 6 이미지 | `step_image()` | Gemini 이미지 생성 후 `panels_json`, `artifact_run_id`, status=`image_generated` 저장 | 동작 |
| STEP 7 조립 | `run_resume.py` | 이미지 artifact 복원 후 PIL 슬라이드 조립, status=`assembled`, `slides_run_id` 저장 | 동작하나 artifact 없을 때 fallback 가시성 낮음 |
| STEP 8 발행 | `run_publish.py` | assembled row의 slides를 X/Telegram 발행, 이력 기록 | 동작하나 episode_id 지정 시 row 선택 불일치 위험 |

## 3. 주요 발견사항

### P0 — 명시 episode_id 발행 시 다른 row가 발행될 수 있음

- `scripts/run_publish.py`는 `--episode`에서 날짜만 파싱하고, 실제 `episode_assets` 조회는 `episode_date` 기준 최신 row 1개만 가져온다.
- 같은 날짜에 episode_no가 2개 이상 있거나 event_type별 row가 섞이면, 사용자가 `ICG-YYYY-MM-DD-001`을 지정해도 최신 created row가 발행될 수 있다.
- 영향: 자동 X/Telegram 발행에서 의도와 다른 에피소드/슬라이드를 발행하는 가장 큰 운영 리스크.
- 근거:
  - episode_id 파싱은 날짜만 사용한다.
  - row 조회는 `.eq("episode_date", episode_date)`만 적용하고 `episode_no`/`event_type` 필터가 없다.
  - `episode_id`는 이후 로그/이력용 문자열로만 사용된다.
- 권고:
  1. `_parse_episode()`를 `(episode_date, episode_no)` 반환으로 확장.
  2. `--episode` 제공 시 `episode_date + episode_no`로 row를 조회.
  3. `--date`만 제공하는 자동 모드에서는 status=`assembled` 최신 1개만 선택.

### P0 — 재생성 차단이 `NORMAL` event_type만 확인함

- `scripts/run_market.py`의 중복/재생성 방어는 `get_current_status(episode_date, "NORMAL")`만 확인한다.
- 실제 메이저 이벤트는 `BATTLE`, `SHOCK`, `AFTERMATH`, `EMERGENCE` 등으로 저장될 수 있어, 이미 발행된 BATTLE row가 있어도 NORMAL row가 없으면 재생성 차단이 우회된다.
- 영향: published 에피소드가 재생성되거나 episode_no가 꼬이는 silent failure 가능.
- 권고:
  1. 날짜 단위 published 존재 여부 조회 함수 추가.
  2. 가능하면 `episode_id`/`episode_no` 단위 상태 검증으로 통일.
  3. `episode_assets` unique key(`episode_date,event_type`)와 `episode_no` 발행 의미를 명확히 분리.

### P1 — stage 단독 실행 날짜 결정이 snapshot 최신일 기준이라 episode 최신일과 어긋날 수 있음

- `_latest_date(stage)`는 `analysis/narrative/persist/image` 단독 실행 시 `daily_snapshots` 최신 날짜를 기준으로 삼는다.
- 그러나 narrative/persist/image는 `analysis_ctx_json` 또는 `script_json`이 있는 episode/analysis row가 기준이어야 한다.
- 영향: 휴장일, 데이터만 수집된 날, 메이저 게이트로 expensive stage가 스킵된 날 이후에 stage 단독 재실행 시 “최신 snapshot은 있지만 ctx/script는 없는 날짜”를 잡아 흐름이 멈출 수 있다.
- 권고:
  - `analysis`: snapshot 최신일 허용.
  - `narrative`: `daily_analysis.analysis_ctx_json` 존재 최신일.
  - `persist/image`: `episode_assets.script_json` 또는 `daily_analysis.narrative_script_json` 존재 최신일.

### P1 — STEP 3 분석은 target date가 아니라 최신 snapshot 2개를 읽음

- `step_analysis(episode_date)`는 `episode_date`를 받지만 내부에서는 `reader.get_latest(2)`만 호출한다.
- 날짜를 명시해 과거일 analysis를 재실행해도 실제 입력 데이터는 DB 최신 2개가 된다.
- 영향: 백필/재처리에서 날짜와 시장 데이터가 어긋나 “블랙박스처럼 다른 이야기”가 생성될 수 있다.
- 권고:
  - `reader.get_by_date(episode_date)`와 직전 snapshot 조회를 사용.
  - 기존 `get_latest(2)`는 날짜 미지정 all/data 후속 기본값에만 제한.

### P1 — 스케줄 주석과 실제 cron이 불일치함

- `run_market.yml`, `resume_episode.yml`, `publish_sns.yml` 모두 주석은 월/수 또는 특정 요일처럼 보이지만 cron은 `1-6`으로 월~토 UTC 실행이다.
- KST 변환 시 `run_market`/`resume`/`publish` 모두 화~일 KST에 해당한다.
- 영향: 운영자가 “월/수 발행”으로 이해할 수 있으나 실제로는 주 6회 자동 작업이 돈다. 비용/중복/휴장일 정책 블랙박스화의 원인이다.
- 권고:
  - 주석을 실제 cron에 맞게 수정하거나 cron을 의도한 요일로 조정.
  - 휴장/주말 강제 실행 정책은 gate 로그에 명시.

### P1 — FRED_API_KEY 누락은 전체 데이터 수집을 hard-stop시킴

- FRED는 API key가 없으면 `RuntimeError`를 발생시키며, `step_data()`는 첫 호출인 `fred_fetcher.fetch_all()` 예외를 전체 STEP 2 실패로 전파한다.
- 다른 fetcher들은 None fallback을 쓰고 있어 장애 정책이 일관되지 않다.
- 영향: yfinance/FearGreed 등으로 최소 판단 가능한 날도 FRED secret 장애 하나로 전체 자동화가 멈춘다.
- 권고:
  - 운영 모드에서는 FRED 필드를 None으로 채우고 품질 게이트에서 `critical_missing`을 판단.
  - strict 모드는 `DATA_STRICT=true` 같은 별도 flag로 분리.

### P2 — optional 고도화 모듈 실패가 경고 후 계속 진행되어 “그날 왜 덜 풍부했는지” 추적이 어렵다

- SignalPack, RiskScoreV3, NarrativeContext, character/arc 일부 경로는 실패 시 warning 후 legacy fallback으로 진행한다.
- 이는 발행 지속성에는 좋지만, 결과물이 갑자기 단순해졌을 때 어떤 고도화가 빠졌는지 최종 payload/발행 이력에서 한눈에 보기 어렵다.
- 권고:
  - `daily_analysis` 또는 `episode_assets`에 `pipeline_degradation_json`을 저장.
  - fallback 발생 시 stage, module, exception class, severity를 구조화.

### P2 — 발행 게이트는 메이저 event_type만 자동 발행하므로 일반장 콘텐츠는 “정상 스킵”된다

- `run_publish.py`의 `MAJOR_EVENT_TYPES`에 없는 `NORMAL`, `INTEL`, `TACTICAL` 등은 `PUBLISH_NON_MAJOR=true`가 아니면 발행하지 않는다.
- 현재 시스템 목적이 “자동 X발행”이라면, 사용자는 “파이프라인이 안 흘러간다”고 느낄 수 있다.
- 권고:
  - 운영 대시보드/로그에 `SKIPPED_BY_MAJOR_GATE` 상태를 명확히 저장.
  - NORMAL/INTEL도 경량 포맷으로 발행할지 정책 결정.

## 4. 블랙박스/안 흘러가는 영역 체크리스트

| 영역 | 위험도 | 증상 | 확인 포인트 |
|---|---:|---|---|
| episode_id ↔ DB row 매칭 | P0 | 지정한 에피소드와 다른 콘텐츠 발행 | `run_publish.py` row 조회 조건 |
| published 재생성 방어 | P0 | 발행된 BATTLE 재생성 가능 | `get_current_status(date, "NORMAL")` |
| 날짜 재처리 | P1 | 과거 날짜 재실행인데 최신 시장 데이터 사용 | `step_analysis()`의 `get_latest(2)` |
| stage 단독 실행 | P1 | narrative/persist/image가 ctx/script 없음으로 중단 | `_latest_date()` 기준 |
| 스케줄 운영 | P1 | 월/수로 알았는데 주 6회 실행 | workflow cron과 주석 불일치 |
| 데이터 수집 | P1 | FRED secret 장애로 전체 STEP 2 중단 | `fred_fetcher.fetch_all()` hard-stop |
| fallback 관측성 | P2 | 결과 품질 저하 원인 파악 어려움 | warning-only fallback |
| non-major 발행 | P2 | 정상 생성됐지만 자동 발행 안 됨 | `MAJOR_EVENT_TYPES` gate |

## 5. 우선 조치 제안

1. **P0 패치 1:** `run_publish.py`에서 `--episode` 지정 시 `episode_no`까지 조회하도록 수정.
2. **P0 패치 2:** `run_market.py`의 published guard를 날짜 전체 또는 episode_no 기준으로 수정.
3. **P1 패치 3:** `step_analysis()`를 `episode_date` 기준 snapshot 조회로 바꾸고 백필 테스트 추가.
4. **P1 패치 4:** stage별 `_latest_date()` 기준을 실제 필요한 산출물 존재 기준으로 분리.
5. **P1 패치 5:** workflow cron 주석/실제 요일 정합성 수정.
6. **P2 패치 6:** fallback/degradation 구조화 로그를 DB에 저장.


## 6. 데이터 재시도/critical 발행 중단 재검토

### 6.1 현재 재시도 적용 현황

| 데이터/생성 소스 | 현재 재시도 | 최종 실패 처리 | 판단 |
|---|---:|---|---|
| 공통 API 데코레이터 | 기본 3회, 지수 백오프 | `reraise=True` 기본값으로 최종 예외 전파 | 공통 정책 존재 |
| FRED 거시 지표 | 시리즈별 3회 | 각 시리즈 실패는 None, 단 `FRED_API_KEY` 누락은 STEP 2 hard-stop | 부분 충족 |
| yfinance 핵심 시장 지표(SPY/Nasdaq/BTC/USDKRW) | 데이터 부족/일시 장애를 3회 재시도하도록 보강 | 3회 실패 후 해당 값 None | 보강 완료 |
| Fear & Greed | 3회 | None 반환 | 충족 |
| Crypto.com basis | mark/index 각각 3회 | Unknown/None 반환 | 충족 |
| LunarCrush sentiment | 2회 + 캐시/stale cache fallback | Unknown/None 반환 | optional 데이터라 허용 가능 |
| Gemini 이미지 | 패널별 3회 | text-card fallback | 발행 지속성 중심 |
| Claude 내러티브 | 3회, 3회차 fallback model | 최종 `NarrativeValidationError` | 충족 |

### 6.2 Critical 데이터 누락 시 발행 중단 구성

- critical 필드는 `us10y`, `vix`, `oil_wti`, `spy_change`, `nasdaq_change`, `btc_usd`, `usdkrw`, `fear_greed`로 분류되어 있다.
- 기존에는 `snapshot_writer`가 critical 누락을 warning으로만 남기고 계속 진행했기 때문에, critical 데이터가 빠져도 STEP 3~8이 진행될 수 있었다.
- 재검토 후 `enforce_critical_quality()`를 추가해 critical 필드가 누락되면 `CriticalDataMissingError`를 발생시키도록 했다.
- `scripts.run_market.step_data()`는 snapshot upsert 전에 `CRITICAL_DATA_GATE_ENABLED=true` 기본값으로 이 게이트를 호출한다. 따라서 핵심 데이터가 3회 재시도 후에도 비어 있으면 잘못된 critical-null snapshot을 저장하지 않고 STEP 2가 실패하며, 같은 run의 분석/서사/이미지 생성 및 신규 발행 산출물 생성은 중단된다.
- 상세 설계와 3자 의사결정 기록은 `docs/MARKET_DATA_RETRY_CRITICAL_GATE_DESIGN_2026-06-04.md`에 분리했다.
- 운영상 emergency override가 필요하면 `CRITICAL_DATA_GATE_ENABLED=false`로 우회할 수 있지만, 자동 발행 기본 정책은 중단이다.

### 6.3 남은 주의점

- 별도 스케줄인 `publish_sns.yml`은 이미 assembled 상태인 과거 에피소드를 발행할 수 있다. critical data gate는 신규 episode 생성 run을 중단하는 장치이지, 과거 assembled backlog 발행까지 날짜별로 차단하는 전역 publish lock은 아니다.
- LunarCrush sentiment, crypto basis, sector heatmap은 스토리 풍부화용 optional 성격이라 현재 critical halt 대상은 아니다.
- FRED secret 자체가 누락된 경우는 재시도 대상이 아니라 설정 오류로 즉시 중단된다.

## 7. 현재 테스트 결과

- `python -m pytest tests/ -q`: 전체 테스트 통과.
- 이번 재검토에서는 yfinance 3회 재시도 보강, upsert 전 critical data gate 추가, 파일럿/전주 시뮬레이션 테스트를 함께 반영했다.
