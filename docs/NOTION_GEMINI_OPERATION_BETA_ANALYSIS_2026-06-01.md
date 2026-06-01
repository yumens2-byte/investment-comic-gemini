# Notion Gemini 영역 정리본 — ICG 운영 베타 시스템 분석

- 작성일: 2026-06-01
- 대상 시스템: 미장코믹스 / Investment Comic Gemini(ICG)
- 분석 범위: 현재 저장소 기준 `run_market` 이미지 트랙, Claude 서사 생성, Gemini 이미지 생성, PIL 조립, SNS 발행, 운영 워크플로우, 테스트 커버리지
- 추가 분석 범위: 스토리 풍부화를 위한 시장/뉴스/이벤트 데이터 확장 가능성, Claude 서사 고도화 설계, Notion 업로드용 운영 설계 정리
- 정리 목적: 운영 베타 중인 시장 데이터 기반 히어로·중립·빌런 스토리/이미지 제작 시스템의 동작 원리와 문제점 검토 및 스토리 품질 향상 로드맵 제안

> 본 문서는 Notion의 **gemini 영역**에 그대로 붙여넣기 위한 운영 분석 정리본이다. 현재 실행 환경에는 Notion API 토큰이 주입되어 있지 않아 직접 Notion 페이지를 생성/수정하지 못했으며, repo 문서로 우선 보관한다.

---

## 1. 결론 요약

### 1.1 전체 판단

ICG는 현재 운영 베타 단계에서 **시장 데이터 수집 → 이벤트 분류 → 캐릭터/전투 계산 → Claude 스토리 JSON 생성 → Gemini 패널 이미지 생성 → PIL 슬라이드 조립 → Telegram/X 발행**까지의 end-to-end 구조가 잘 분리되어 있다. 특히 Battle 계산 결과를 코드에서 결정하고 Claude는 이를 해석만 하도록 제한한 점, Pydantic 스키마 검증과 Canon 검증을 두는 점, GitHub Actions를 단계별로 분리한 점은 운영 안전성 측면에서 강점이다.

다만 “시장 데이터 기반”이라는 제품 핵심 주장과 “운영 베타 자동화” 관점에서는 다음 문제가 우선적으로 보인다.

### 1.2 우선순위 높은 문제

| 우선순위 | 영역 | 문제 | 영향 | 권고 |
|---|---|---|---|---|
| P0 | 날짜/시장 데이터 | 일부 fetcher가 `target_date`를 실질적으로 사용하지 않고, `_today()` 주석은 KST라고 되어 있으나 코드상 `date.today()`에 의존한다. | 휴장일·시차·수동 날짜 재실행 시 해당 날짜 데이터가 아니라 실행 시점 최신값이 저장될 수 있음. | KST timezone 명시, target_date 기반 observation end/date validation 추가 |
| P0 | Gemini 비용/재시도 | Gemini 이미지 비용이 항상 0으로 기록되고, episode total_cost도 누적되지 않는다. 재시도별 프롬프트/REF 조정도 실제 tenacity attempt와 연결되지 않는다. | 베타 운영 비용 모니터링 불가, 실패 대응 전략이 기대대로 작동하지 않을 가능성 | usage_metadata 파싱, panel cost 반환/누적, before_sleep 기반 attempt 전달 |
| P0 | 에피소드 식별/DB key | `episode_assets` upsert/patch 충돌키가 `(episode_date,event_type)` 중심인데 episode_id는 `episode_no`까지 포함한다. | 같은 날짜 같은 event_type 재실행/강제 실행 시 덮어쓰기 또는 잘못된 row patch 위험 | episode_id 또는 `(episode_date,episode_no)` 중심으로 state machine 정렬 |
| P1 | 데이터 품질 게이트 | yfinance, Fear&Greed, Crypto 등은 실패 시 None/Unknown으로 계속 진행한다. FRED key 누락만 치명 오류다. | 데이터가 충분히 없는 상태에서도 NORMAL/INTEL 등으로 오분류될 수 있음 | 필수 지표 최소 충족률/신선도 게이트 추가 |
| P1 | Notion 의존성 | 프롬프트/상수는 Notion에서 런타임 로드하되 캐시/파싱 실패 시 fallback이 섞여 있다. | Notion 구조 변경 시 운영 품질이 조용히 저하될 수 있음 | Notion 로드 결과 버전·해시·필수 섹션 검증 로그 추가 |
| P1 | 발행 자동화 | schedule 발행은 confirmation 없이 `all` 채널로 진행되며, 수동 workflow만 confirm=YES가 있다. | 품질 검수 전 자동 발행 리스크 | schedule 발행 전 latest status/gate 및 human approval 옵션 강화 |
| P1 | 스토리 정보량 | 현재 핵심 입력은 가격/금리/심리 지표 중심이며, 뉴스·경제일정·섹터/종목·정책 이벤트가 구조화되어 있지 않다. | 같은 시장 움직임이 반복될 때 서사의 원인/맥락/상징이 단조로워질 수 있음 | news/event/context layer를 STEP 2.5/3.1에 추가 |
| P1 | Claude 서사 설계 | Battle 결과는 고정되어 있으나 Claude가 사용할 갈등 원인, 뉴스 근거, 캐릭터 내면 변화, 장면 비트가 충분히 구조화되어 있지 않다. | 패널은 맞지만 “왜 오늘 이 전투가 벌어졌는지”의 드라마 밀도가 낮아질 수 있음 | Narrative Context Pack + Story Beat Plan + Critic pass 설계 |
| P2 | 스키마-프롬프트 불일치 | 프롬프트는 “exactly 8 panels”를 요구하지만 schema는 8~10개를 허용한다. | Claude가 9~10패널을 반환해도 검증 통과 가능 | schema max_length=8 또는 프롬프트/조립 정책 통일 |

---

## 2. 시스템 동작 원리

### 2.1 핵심 파이프라인

현재 메인 이미지 트랙은 `scripts.run_market`가 담당한다.

1. **STEP 2 — Data Ingest**
   - FRED: 금리, VIX, WTI, 달러 인덱스, HY spread, yield curve
   - yfinance: SPY, NASDAQ, BTC, USD/KRW
   - Fear & Greed: alternative.me
   - Crypto basis: Crypto.com public API
   - Social sentiment: LunarCrush 계열
   - 결과는 `icg.daily_snapshots`에 upsert

2. **STEP 3 — Analysis / Battle**
   - 최신 snapshot 2개를 읽어 delta 계산
   - delta와 arc context 기반 event_type 결정
   - 시장 이벤트에 맞는 hero/villain 선정
   - `SCENARIO_V2_ENABLED`가 켜져 있으면 NO_BATTLE / ALLIANCE / ONE_VS_ONE 분기
   - battle_result는 코드 계산으로 결정
   - `icg.daily_analysis` 및 `analysis_ctx_json`에 저장

3. **STEP 4 — Narrative**
   - Claude가 EpisodeScript JSON 생성
   - 코드가 episode_id/date/event_type을 오버라이드
   - Pydantic schema와 Canon 검증 통과 필요
   - 결과는 `daily_analysis.narrative_script_json`에 임시 저장

4. **STEP 5 — Persist**
   - `episode_assets`에 script_json, battle_json, scenario_type, heroes_json 저장
   - Notion tracker에는 전체 JSON이 아니라 요약 메타만 미러링
   - story_state / arc_state 갱신은 실패해도 파이프라인을 계속 진행

5. **STEP 6 — Image Generation**
   - narrative panels를 Gemini용 이미지 prompt로 변환
   - 캐릭터 REF 이미지를 패널별 multi-input으로 주입
   - Gemini 2.5 Flash Image 호출
   - 실패 패널은 `None`으로 저장해 후속 PIL 단계에서 text_card fallback 처리

6. **STEP 7 — PIL Assembly**
   - `run_resume.py`가 `episode_assets`를 읽어 패널 이미지와 텍스트를 1080×1350 슬라이드로 조립
   - slides_json과 `slides_run_id` 저장

7. **STEP 8 — Publish SNS**
   - `run_publish.py`가 assembled/image_generated 에피소드를 Telegram/X로 발행
   - `PUBLISH_NON_MAJOR`가 없으면 비메이저 이벤트는 자동 스킵
   - published 상태와 `published_comics` 테이블로 중복 발행을 이중 방어

### 2.2 히어로·중립·빌런 구조

- **Hero/Villain Canon**은 `config/characters.yaml`에 있으며, Battle 계산과 REF 이미지 로딩에서 ID 검증을 수행한다.
- **중립 시나리오**는 별도 “neutral 캐릭터군”보다는 `NO_BATTLE` 시나리오와 `PEACEFUL_GROWTH` outcome에 가깝다.
- 시장이 조용하거나 긍정적이면 NO_BATTLE이 선택될 수 있고, 이 경우 villain panel 등장이 금지된다.
- ALLIANCE는 2명의 hero가 1명의 villain을 상대하는 구조이며, Claude prompt에서 패널별 연합 형성/공격/결말 연출을 요구한다.

### 2.3 운영 자동화 구조

- `run_market.yml`: STEP 2~6 실행. schedule과 workflow_dispatch 지원.
- `resume_episode.yml`: STEP 7 PIL 조립. schedule과 workflow_dispatch 지원.
- `publish_sns.yml`: STEP 8 SNS 발행. 수동 실행 시 `confirm=YES` 필요, schedule은 최신 발행 가능 에피소드 자동 선택.
- `ci.yml`: ruff + pytest 실행.

---

## 3. 잘 설계된 부분

### 3.1 LLM에게 승패를 맡기지 않는 구조

Battle 결과는 코드의 순수 함수가 결정하고, Claude prompt에는 “Outcome is fixed”가 들어간다. 이후 Claude 출력은 schema/canon validator를 통과해야 한다. 이는 금융/시장 콘텐츠에서 LLM이 임의로 시장 판단을 바꾸는 리스크를 줄이는 좋은 설계다.

### 3.2 단계별 재시작 가능한 Hybrid 구조

analysis 결과와 narrative 결과를 `daily_analysis`에 JSON으로 저장해 narrative/persist/image 단계를 별도 프로세스에서 재개할 수 있다. GitHub Actions 단계 분리와도 잘 맞는다.

### 3.3 Canon / REF 이미지 검증

REF 이미지 경로와 SHA256 기반 Canon lock 구조가 있고, 알 수 없는 캐릭터 ID는 예외로 중단한다. 캐릭터 정체성 유지가 중요한 만화 생성 시스템에서는 필수적인 장치다.

### 3.4 발행 중복 방어

발행 전 `episode_assets.status == published`를 확인하고, 추가로 `published_comics` 이력 테이블을 확인한다. FORCE_REPUBLISH가 없으면 중복 발행을 막는다.

### 3.5 테스트 커버리지

현재 unit/integration 테스트 450개가 통과한다. Battle, scenario selector, prompt integration, schema, PIL composer, story state, publish gate 등 핵심 로직에 테스트가 존재한다.

---

## 4. 상세 문제점 및 개선안

### 4.1 날짜/시차/대상일 데이터 정합성

#### 관찰

- `_today()` 문서 문자열은 KST 오늘이라고 되어 있지만 구현은 `date.today()`이다.
- FRED fetcher는 `target_date`를 받지만 내부 `_fetch_series()`에서 `date.today()`를 observation_end로 사용한다.
- yfinance fetcher도 `target_date`를 받지만 실제로는 period 기반 최신 데이터를 조회한다.
- GitHub Actions는 `TZ=Asia/Seoul`을 지정하지만, 로컬/수동 실행/다른 런타임에서는 보장되지 않는다.

#### 영향

- `--date 2026-05-31`처럼 과거 날짜를 재실행해도 FRED/yfinance가 실행 시점 최신값을 저장할 수 있다.
- 미국 시장 데이터는 장 마감/휴장/시차 영향이 큰데, 단순 “오늘 날짜”로 snapshot을 만들면 실제 시장일과 episode_date가 어긋날 수 있다.
- 베타 운영 리포트에서 “해당 날짜 시장 데이터 기반”이라는 설명과 실제 데이터 기준일이 다를 수 있다.

#### 권고

1. 모든 fetcher에서 `target_date`를 실제 observation_end 또는 조회 범위 기준으로 사용한다.
2. `zoneinfo.ZoneInfo("Asia/Seoul")` 기반 KST today를 명시한다.
3. snapshot row에 각 지표의 `source_observed_at` 또는 `source_date`를 추가한다.
4. 미국 휴장/주말에는 자동으로 직전 거래일 데이터를 사용하고, episode_date와 market_date를 분리한다.

---

### 4.2 데이터 품질 게이트 부족

#### 관찰

- yfinance는 개별 티커 실패 시 `None`으로 두고 계속 진행한다.
- Fear & Greed와 Crypto basis도 실패 시 None/Unknown으로 계속 진행한다.
- `snapshot_writer`는 None을 그대로 저장하고 non-null count만 로그에 남긴다.
- delta 계산은 curr_val이 None인 지표를 제외한다.
- event_classifier는 누락 지표를 0.0으로 취급한다.

#### 영향

- VIX/WTI/DGS10/SPY 같은 핵심 지표가 누락되어도 BATTLE/SHOCK가 아닌 NORMAL로 흐를 수 있다.
- “조용한 시장”인지 “데이터 부족”인지 구분되지 않는다.
- major event gate가 비용 통제 용도로 동작할 때, 데이터 부족으로 expensive stage가 스킵될 수 있다.

#### 권고

1. 필수 지표군을 정의한다: `vix`, `oil_wti`, `us10y`, `spy_change`, `nasdaq_change`.
2. 필수 지표 충족률이 기준 미만이면 event_type을 `DATA_INSUFFICIENT` 또는 `ABORTED`로 기록하고 narrative/image를 막는다.
3. daily_snapshots에 `data_quality_score`, `missing_required_fields`, `source_freshness_json`을 저장한다.
4. `event_classifier`에서 누락과 0.0을 구분해 로그/분기한다.

---

### 4.3 Gemini 이미지 생성 비용/재시도 로직 결함

#### 관찰

- `gemini_client.generate_panel()`은 `prompt_tokens`, `output_tokens`를 항상 0으로 둔다.
- `generate_episode()`는 `total_cost`를 0.0으로 초기화하지만 panel별 cost를 누적하지 않는다.
- `_generate_one`에 tenacity retry decorator가 붙어 있는데, `generate_panel()`은 `getattr(_generate_one, "_retry_count", 0)`로 retry attempt를 읽으려 한다. 현재 retry.py는 이런 attribute를 설정하지 않는다.

#### 영향

- 운영 베타에서 Gemini 비용이 `$0.0000`으로 기록되어 실제 비용 추적이 불가능하다.
- 2회차 identity 강화, 3회차 REF 단순화 전략이 실제 retry attempt와 연결되지 않을 가능성이 높다.
- 실패 원인별 조정 전략을 검증하기 어렵다.

#### 권고

1. Gemini SDK 응답의 usage metadata를 파싱해 input/output token을 저장한다.
2. `generate_panel()`이 `(path, cost)`를 반환하거나 log record에서 cost를 합산하도록 구조를 바꾼다.
3. tenacity의 `before_sleep`/`retry_state.attempt_number` 또는 수동 루프로 retry attempt를 명시 전달한다.
4. panel별 prompt hash, ref hash, failure category를 `gemini_run.log`에 기록한다.

---

### 4.4 episode_id / episode_assets row 정합성 위험

#### 관찰

- episode_id는 `ICG-YYYY-MM-DD-NNN` 구조이며 `_make_episode_id()`는 같은 날짜 마지막 row의 status에 따라 재사용/증가한다.
- 하지만 Supabase helper의 episode_assets unique key는 `(episode_date,event_type)`이다.
- patch도 episode_date + event_type으로 업데이트한다.

#### 영향

- 같은 날짜에 같은 event_type으로 두 번째 episode를 만들면 이전 row를 덮어쓸 수 있다.
- 이벤트 타입이 바뀌거나 fallback 조회가 개입하면 narrative/image/assembly/publish 단계가 서로 다른 row를 바라볼 위험이 있다.
- 운영 장애가 “이미 published인데 image stage가 다른 no로 진행” 같은 형태로 나타날 수 있다.

#### 권고

1. `episode_assets`의 주 키를 `episode_id` 또는 `(episode_date, episode_no)` 기준으로 재정렬한다.
2. 모든 load/patch/publish 함수에 event_type 대신 episode_id를 전달한다.
3. `(episode_date,event_type)`은 조회 보조 인덱스로만 사용한다.
4. 상태 전이 state machine을 명시한다: `draft → narrative_done → image_generated → assembled → published`.

---

### 4.5 Notion 런타임 의존성 관리

#### 관찰

- narrative system prompt는 repo에서 제거되고 Notion에서 로드하도록 되어 있다.
- event classifier thresholds도 Notion loader에서 가져오고 실패 시 기본값으로 fallback한다.
- Notion mirror는 API key가 없거나 실패해도 pipeline을 중단하지 않는다.

#### 영향

- Notion 문서 구조가 바뀌면 prompt/상수 파싱 품질이 저하될 수 있다.
- fallback 기본값이 조용히 적용되면 운영자는 “Notion 설정대로 돈다”고 생각하지만 실제로는 repo 기본값으로 돌 수 있다.
- 현재 분석 실행 환경처럼 Notion API 토큰이 없으면 직접 gemini 영역 업데이트가 불가능하다.

#### 권고

1. Notion loader 결과에 `notion_page_id`, `loaded_at`, `content_hash`, `required_sections_ok`를 로그/DB에 저장한다.
2. 운영 모드에서는 필수 prompt/constant 로드 실패를 warning이 아니라 hard fail로 올리는 옵션을 둔다.
3. Notion 미러링은 create-only가 아니라 Episode ID 기준 upsert/update를 구현한다.
4. 분석/운영 문서 자동 업로드를 위해 별도 `scripts/publish_notion_report.py`를 추가하는 것을 권장한다.

---

### 4.6 발행 게이트와 human approval

#### 관찰

- `run_market.yml`은 schedule 실행 시 major event gate로 expensive stage 비용을 통제한다.
- `publish_sns.yml`은 workflow_dispatch에서는 confirm=YES를 요구하지만, schedule에서는 자동으로 channels=all을 선택한다.
- `run_publish.py`는 비메이저 이벤트 발행을 기본 스킵하되 `PUBLISH_NON_MAJOR=true`면 우회한다.

#### 영향

- schedule 발행은 사람이 품질 확인을 하지 않아도 최신 assembled episode를 발행할 수 있다.
- Gemini 이미지 일부가 text_card fallback이어도 assembled 후 발행될 수 있다.
- 브랜드/투자 콘텐츠 품질 리스크가 존재한다.

#### 권고

1. schedule publish 전 `quality_gate_json`을 확인한다.
2. 이미지 성공률, disclaimer 존재, panel count, text length, no villain in NO_BATTLE 등을 publish 직전 재검증한다.
3. 운영 베타 동안은 Telegram 무료 채널 자동 발행, X/paid 채널은 manual approval로 분리한다.
4. fallback panel이 2개 이상이면 자동 발행을 차단한다.

---

### 4.7 Schema와 prompt 정책 불일치

#### 관찰

- prompt는 정확히 8개 패널을 요구한다.
- Pydantic schema는 8~10개 패널을 허용한다.

#### 영향

- Claude가 9~10개 패널을 반환해도 검증 통과 가능하다.
- PIL 조립과 SNS 업로드 정책이 8장 기준이라면 예외 케이스가 생긴다.

#### 권고

- “운영 표준이 8장”이면 schema를 `min_length=8, max_length=8`로 고정한다.
- 10장을 허용할 계획이라면 prompt, PIL layout, X thread split, Telegram caption 정책을 모두 8~10장 호환으로 명시한다.

---


## 5. 스토리 풍부화를 위한 시장/뉴스 데이터 확장 설계

### 5.1 현재 입력의 한계

현재 STEP 2는 FRED, yfinance, Fear & Greed, Crypto basis, LunarCrush BTC sentiment를 수집하고, STEP 3은 이 snapshot의 전일 대비 delta와 arc context를 기반으로 event_type/scenario/battle_result를 결정한다. 이 구조는 “시장 수치 기반 전투 결과”에는 강하지만, 다음과 같은 스토리 재료가 부족하다.

- **원인 서사 부족**: VIX가 올랐다는 사실은 알지만, 그날 시장이 무엇을 두려워했는지에 대한 뉴스 요약이 없다.
- **예고/복선 부족**: 내일/이번 주 예정된 CPI, FOMC, 고용, 실적, 국채입찰 같은 이벤트 캘린더가 prompt에 구조화되어 있지 않다.
- **섹터/종목 디테일 부족**: S&P/Nasdaq/BTC/USD-KRW 중심이라 반도체, AI, 에너지, 금융, 방산 등 장면 배경을 바꿀 근거가 약하다.
- **정책/규제 이벤트 부족**: Fed 발언, SEC filing/8-K, Treasury 일정, 지정학 이벤트가 빌런의 “등장 이유”로 연결되지 않는다.
- **뉴스 신뢰도/중복 관리 부족**: 단순 headline 추가만 하면 LLM hallucination과 sensationalism이 증가할 수 있으므로 출처, 시간, dedup, relevance score가 필요하다.

### 5.2 추가 수집 후보와 우선순위

| 우선순위 | 데이터 레이어 | 후보 소스 | 스토리 활용 | 저장 위치 제안 | 비고 |
|---|---|---|---|---|---|
| P0 | 경제 이벤트 캘린더 | Trading Economics Calendar API, FRED release calendar 보강 | “내일 CPI 관문”, “FOMC 문 앞의 긴장” 같은 다음 hook 생성 | `daily_context.economic_events_json` | 이벤트명, actual/forecast/previous, importance, release_time 필요 |
| P0 | 시장 뉴스/헤드라인 | Alpha Vantage NEWS_SENTIMENT, NewsAPI Everything, GDELT DOC/Context | 오늘 움직임의 원인 후보 3개, headline-to-villain mapping | `daily_context.news_digest_json` | 본문 저장 금지, title/url/source/published_at/summary만 저장 |
| P0 | 섹터/테마 breadth | SPDR sector ETF, Nasdaq 100 top movers, Mag7/AI basket | 배경 도시/전장 선택: AI 타워, 오일 항구, 은행 지하금고 | `daily_context.sector_heatmap_json` | yfinance로 MVP 가능 |
| P1 | 옵션/변동성 구조 | VIX term structure, put/call ratio, MOVE index | Volatility Hydra의 강도, 공포의 질감 | `daily_context.vol_surface_json` | 무료 소스 안정성 확인 필요 |
| P1 | 정책/공식 발언 | Fed speeches/calendar, Treasury auction, BLS/BEA release | Debt Titan/Policy NPC의 대사 근거 | `daily_context.policy_events_json` | 공식 소스 우선 |
| P1 | SEC/기업 이벤트 | SEC EDGAR submissions/company facts, earnings calendar | Algorithm Reaper/AI 버블/실적 충격 에피소드 | `daily_context.corporate_events_json` | SEC API는 filings/XBRL 중심, 뉴스 대체재 아님 |
| P2 | 글로벌/지정학 | GDELT global event/news tone, oil/geopolitical keywords | War Dominion/Oil Shock Titan 등장 근거 | `daily_context.geo_risk_json` | 금융 직접성 낮으므로 보조 신호로 사용 |

공식 문서 기준으로, FRED observations API는 observation_start/end를 제공하므로 현재 날짜 정합성 문제를 해결할 수 있고, NewsAPI Everything은 기사 검색/분석용 endpoint이며, Alpha Vantage는 market news & sentiment API를 제공한다. SEC는 EDGAR submissions와 XBRL data API를 제공하고, Trading Economics는 near real-time economic calendar와 actual/previous/consensus 정보를 제공한다. 참고 링크: [FRED series observations](https://fred.stlouisfed.org/docs/api/fred/series_observations.html), [NewsAPI Everything](https://newsapi.org/docs/endpoints/everything), [Alpha Vantage NEWS_SENTIMENT](https://www.alphavantage.co/documentation/), [SEC EDGAR APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces), [Trading Economics Calendar](https://tradingeconomics.com/api/calendar.aspx), [GDELT DOC 2.0](https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/amp/).

### 5.3 권장 아키텍처: Data → Context → Narrative 분리

추가 데이터를 바로 Claude prompt에 넣으면 prompt가 길어지고, 뉴스 과잉으로 스토리가 산만해질 수 있다. 따라서 “수집”과 “서사 컨텍스트 압축”을 분리한다.

#### STEP 2.5 — Context Fetch

신규 모듈 후보:

```text
engine/data/news_fetcher.py
engine/data/economic_calendar_fetcher.py
engine/data/sector_breadth_fetcher.py
engine/data/policy_event_fetcher.py
engine/data/corporate_event_fetcher.py
```

각 fetcher는 raw API 결과를 그대로 prompt에 넣지 않고, 다음 공통 스키마로 정규화한다.

```json
{
  "source": "alpha_vantage|newsapi|gdelt|trading_economics|sec",
  "source_url": "https://...",
  "published_at": "2026-06-01T13:30:00Z",
  "topic": "inflation|rates|oil|ai|earnings|geopolitics|crypto",
  "entities": ["Fed", "NVDA", "WTI"],
  "relevance_score": 0.0,
  "sentiment_score": 0.0,
  "market_link": "VIX|WTI|DGS10|NASDAQ|BTC",
  "story_use": "cause|foreshadow|background|villain_trigger|hero_signal",
  "safe_summary_ko": "한 문장 한국어 요약",
  "headline": "원문 제목 또는 짧은 제목",
  "dedup_key": "hash"
}
```

#### STEP 3.1 — Context Scoring

신규 모듈 후보:

```text
engine/analysis/context_scorer.py
engine/analysis/news_event_classifier.py
engine/analysis/story_context_builder.py
```

역할:

1. 시장 delta와 뉴스 topic을 연결한다.
2. event_type과 villain_id에 맞는 뉴스만 남긴다.
3. 같은 사건의 중복 헤드라인을 제거한다.
4. Claude에 넣을 `narrative_context_pack`을 800~1,200 token 이내로 압축한다.

#### STEP 4 — Claude Prompt 주입

`render_user_prompt()`에 다음 필드를 추가한다.

```python
narrative_context_pack: dict | None = None
story_beat_plan: dict | None = None
```

Claude prompt에는 raw news가 아니라 아래와 같은 압축 팩만 넣는다.

```yaml
Narrative Context Pack:
  market_cause: "10Y yield rebound and mega-cap tech weakness drove risk-off tone"
  top_evidence:
    - metric: "DGS10"
      value: "4.8% above threshold"
      story_role: "Debt Titan pressure"
    - headline_summary: "Fed officials signaled rates may stay restrictive"
      source: "official/news"
      story_role: "villain motivation"
  foreshadow:
    - "CPI release in 2 days may decide whether the gate opens"
  scene_symbols:
    - "bond auction hall"
    - "red volatility siren"
  prohibited_claims:
    - "Do not claim a specific future market direction"
```

### 5.4 뉴스 데이터 사용 안전장치

- **출처 URL 필수**: 모든 headline_summary는 source_url을 가져야 한다.
- **본문 장문 저장 금지**: 저작권/라이선스 리스크를 줄이기 위해 title, short summary, url, source, timestamp만 저장한다.
- **시간 창 제한**: 기본은 episode_date 기준 24~36시간, 주말은 직전 거래일+주말 window.
- **Relevance threshold**: 관련도 낮은 뉴스는 prompt에 넣지 않는다.
- **No single-source rule**: 큰 원인 서사는 가능하면 2개 이상 출처 또는 1개 공식 출처로만 확정한다.
- **투자 조언 금지**: 뉴스가 있어도 caption/disclaimer 정책은 유지한다.
- **Hallucination 방지**: Claude에게 “제공된 context pack 외 구체 뉴스/수치 창작 금지”를 명시한다.

### 5.5 MVP 구현 순서

1. `sector_breadth_fetcher.py`를 yfinance 기반으로 먼저 추가한다. 외부 신규 API key 없이 장면 다양성을 높일 수 있다.
2. `economic_calendar_fetcher.py`를 추가해 다음 1~3영업일의 주요 이벤트를 hook에 반영한다.
3. `news_fetcher.py`는 Alpha Vantage 또는 NewsAPI 중 1개만 pilot으로 붙인다.
4. `story_context_builder.py`에서 top 3 context만 Claude에 전달한다.
5. `daily_context` 테이블 또는 `daily_analysis.context_pack_json` 컬럼을 추가한다.
6. A/B shadow run으로 기존 prompt vs context pack prompt의 품질을 비교한다.

---

## 6. Claude 서사 고도화 분석/설계

### 6.1 현재 Claude 생성 구조의 장점과 한계

현재 Claude는 `EpisodeScript` JSON을 생성하고, 코드가 episode_id/date/event_type을 오버라이드한 뒤 schema와 Canon 검증을 수행한다. 이 방식은 안정적이지만, 스토리를 풍부하게 만드는 데 필요한 “사전 극작 설계”가 부족하다.

현재 prompt는 event_type, delta, battle_result, scenario_type, ending_tone, arc_context, 캐릭터 belief/pair tension을 제공한다. 그러나 Claude가 8패널 안에서 다음 요소를 동시에 해결해야 한다.

- 시장 원인 설명
- 히어로/빌런 대립
- 캐릭터 감정 변화
- 전투 액션
- 다음 hook
- 투자 면책

이 때문에 출력은 형식은 맞지만, 시장 맥락과 캐릭터 드라마가 얕아질 수 있다.

### 6.2 권장 구조: 2-pass 또는 3-pass Narrative Engine

#### Option A — 2-pass 구조(MVP 권장)

1. **Pass 1: Story Planner**
   - 입력: battle_result, scenario_type, arc_context, narrative_context_pack
   - 출력: `StoryBeatPlan`
   - 목적: 8패널의 감정 곡선/시장 근거/장면 상징/대사 역할을 먼저 고정

2. **Pass 2: Script Writer**
   - 입력: StoryBeatPlan + Canon constraints
   - 출력: 기존 `EpisodeScript`
   - 목적: JSON schema에 맞춰 실제 패널 대사/내레이션 생성

장점: 구현 난이도가 낮고, 기존 schema와 Gemini/PIL pipeline을 유지할 수 있다.

#### Option B — 3-pass 구조(품질 우선)

1. **Planner**: 장면 비트와 시장 근거 설계
2. **Writer**: EpisodeScript 작성
3. **Critic/Rewriter**: 시장 근거 누락, disclaimer, 캐릭터 일관성, 반복 표현을 검사하고 수정

운영 베타에서는 비용을 고려해 schedule은 2-pass, 수동 고품질 발행은 3-pass를 권장한다.

### 6.3 신규 스키마 제안: StoryBeatPlan

```python
class StoryBeat(BaseModel):
    panel_idx: int
    dramatic_function: Literal[
        "HOOK", "MARKET_CAUSE", "CHARACTER_REACTION", "CONFLICT",
        "TURNING_POINT", "OUTCOME", "NEXT_HOOK", "DISCLAIMER"
    ]
    market_evidence_ids: list[str]
    required_character: list[str]
    emotional_shift: str
    visual_symbol: str
    dialogue_intent: str
    forbidden: list[str] = []

class StoryBeatPlan(BaseModel):
    episode_thesis: str
    market_cause_summary: str
    villain_motivation: str
    hero_inner_conflict: str
    panel_beats: list[StoryBeat]
    next_hook_seed: str
    factuality_guardrails: list[str]
```

이 스키마는 Claude가 바로 패널 JSON을 쓰기 전에 “오늘의 에피소드가 무엇에 관한 이야기인지”를 먼저 정하게 만든다.

### 6.4 Claude Prompt 개선안

#### 6.4.1 입력 블록 재구성

기존 prompt에 아래 순서의 블록을 추가/재배치한다.

1. **Immutable Facts**
   - episode_id/date/event_type/scenario_type/outcome/balance
   - “절대 변경 금지”

2. **Market Evidence Pack**
   - 핵심 수치 3개
   - 뉴스/이벤트 요약 3개 이하
   - 다음 이벤트 hook 1개

3. **Dramatic Assignment**
   - villain motivation
   - hero fear/lie/truth
   - pair tension 또는 crowd momentum

4. **Panel Beat Contract**
   - 1: Hook
   - 2: Market cause
   - 3: Villain pressure or neutral observation
   - 4: Hero conflict
   - 5: Turning point
   - 6: Outcome execution
   - 7: Next hook
   - 8: Disclaimer

5. **Factuality Guardrails**
   - 제공되지 않은 뉴스/수치 창작 금지
   - 미래 수익률/투자 추천 금지
   - market_ref는 제공 수치만 사용

#### 6.4.2 장면 풍부화 규칙

- 같은 villain이 2회 이상 연속 등장하면 배경/상징을 바꾼다.
- market_cause가 “rates”면 금고, 국채 경매장, 시계탑 이미지를 사용한다.
- market_cause가 “oil/geopolitics”면 항구, 파이프라인, 검은 파도 이미지를 사용한다.
- market_cause가 “AI/mega-cap tech”면 데이터센터, GPU 코어, 전광판 이미지를 사용한다.
- NO_BATTLE에서도 갈등이 완전히 사라지지 않도록 “작은 불안/다음 관문”을 panel 7 hook에 남긴다.
- 캐릭터 belief의 lie/truth는 최소 1개 panel에 반영하되, 설명문이 아니라 행동/대사로 표현한다.

### 6.5 품질 평가 루브릭

Claude 출력 후 자동/수동 평가에 아래 점수를 붙인다.

| 항목 | 점수 | 자동화 가능 여부 | 설명 |
|---|---:|---|---|
| Market Grounding | 0~5 | 부분 가능 | market_ref와 context evidence가 실제로 쓰였는가 |
| Narrative Coherence | 0~5 | LLM judge 필요 | 8패널 흐름이 원인→갈등→결과→hook으로 이어지는가 |
| Character Consistency | 0~5 | 부분 가능 | Canon ID, role, belief, form이 유지되는가 |
| Visual Variety | 0~5 | 부분 가능 | 반복 배경/구도/상징이 줄었는가 |
| Factual Safety | pass/fail | 자동 가능 | 미제공 수치/뉴스/투자 추천이 없는가 |
| Publish Readiness | pass/fail | 자동 가능 | disclaimer, panel count, text length, fallback 기준 통과 |

운영 기준 예시:

- 자동 발행: `Market Grounding >= 3`, `Factual Safety=pass`, `Publish Readiness=pass`, fallback panel 0~1개
- 수동 검수: grounding 2 이하 또는 fallback 2개 이상
- 재생성: Canon violation, disclaimer fail, 미제공 뉴스 창작, 투자 추천성 문구 발생

### 6.6 구현 파일 변경 제안

| 파일/모듈 | 변경 제안 |
|---|---|
| `engine/data/news_fetcher.py` | 신규. 뉴스/헤드라인 수집 및 정규화 |
| `engine/data/economic_calendar_fetcher.py` | 신규. CPI/FOMC/고용/실적 등 일정 수집 |
| `engine/data/sector_breadth_fetcher.py` | 신규. 섹터/테마 heatmap 생성 |
| `engine/analysis/story_context_builder.py` | 신규. 시장 delta + 뉴스 + 일정 → narrative_context_pack |
| `engine/narrative/story_planner.py` | 신규. StoryBeatPlan 생성 |
| `engine/narrative/schema.py` | `StoryBeatPlan`, `StoryBeat`, `NarrativeQualityReport` schema 추가 |
| `engine/narrative/claude_client.py` | 2-pass 옵션과 critic pass feature flag 추가 |
| `config/prompts/narrative_user.j2` | Narrative Context Pack, Panel Beat Contract, Factuality Guardrails 블록 추가 |
| `scripts/run_market.py` | STEP 2.5/3.1 삽입, feature flag `NARRATIVE_CONTEXT_ENABLED` 추가 |
| `migrations/*` | `daily_context` 테이블 또는 context JSON 컬럼 추가 |

### 6.7 Feature Flag 운영안

| Flag | 기본값 | 설명 | rollout |
|---|---|---|---|
| `NARRATIVE_CONTEXT_ENABLED` | false | 뉴스/일정/섹터 context pack을 Claude에 전달 | shadow → manual → schedule |
| `NEWS_FETCH_ENABLED` | false | 뉴스 API 호출 | manual only부터 시작 |
| `ECON_CALENDAR_ENABLED` | false | 경제일정 API 호출 | shadow부터 가능 |
| `SECTOR_BREADTH_ENABLED` | false | 섹터/테마 heatmap | 바로 shadow 가능 |
| `STORY_PLANNER_ENABLED` | false | 2-pass planner 활성화 | manual high-quality run부터 |
| `NARRATIVE_CRITIC_ENABLED` | false | critic/rewrite pass 활성화 | 비용 확인 후 제한 적용 |

### 6.8 최종 권장안

스토리를 가장 빠르게 풍부하게 만드는 MVP는 다음 조합이다.

1. **섹터/테마 heatmap**으로 장면 배경 다양화
2. **경제 이벤트 캘린더**로 panel 7 next_hook 강화
3. **뉴스 digest top 3**로 villain motivation과 market_cause 보강
4. **StoryBeatPlan 2-pass**로 8패널 구조를 먼저 고정
5. **Factuality Guardrails**로 뉴스 hallucination 방지

이 조합은 기존 Battle 계산과 Gemini 이미지 파이프라인을 크게 흔들지 않으면서, “오늘 시장에서 왜 이 캐릭터가 등장했고, 다음 에피소드로 무엇이 이어지는지”를 훨씬 명확하게 만든다.

---

## 7. 초등학생도 이해할 수 있는 최우선 추천 작업단계

> 최우선 목표는 두 가지다.  
> **첫째, 데이터 재료를 더 많이 모은다.**  
> **둘째, Claude가 그 재료로 더 재미있는 이야기를 쓰게 한다.**

### 7.1 한 줄 비유

지금 시스템은 “오늘 시장 숫자를 보고 만화를 그리는 로봇”이다. 더 좋은 만화를 만들려면 로봇에게 **숫자표만 주지 말고, 오늘 무슨 일이 있었는지 적힌 뉴스 카드와 내일 무슨 일이 올지 적힌 예고 카드**도 같이 줘야 한다.

### 7.2 가장 먼저 할 일 5단계

| 순서 | 작업 이름 | 아주 쉬운 설명 | 왜 필요한가 | 완료 기준 |
|---:|---|---|---|---|
| 1 | 데이터 날짜 맞추기 | 오늘 일기에는 오늘 일을 써야 한다. 어제 일을 오늘 일처럼 쓰면 안 된다. | 잘못된 날짜 데이터로 스토리를 만들면 시장 설명이 틀어진다. | `episode_date`, `market_date`, `source_date`가 로그/DB에 분리 저장된다. |
| 2 | 뉴스 카드 3장 모으기 | 오늘 시장이 왜 움직였는지 알려주는 뉴스 3개만 고른다. | 빌런이 왜 나타났는지 설명할 수 있다. | `news_digest_json`에 제목, 출처, 시간, 한 줄 요약, 관련 지표가 저장된다. |
| 3 | 다음 이벤트 카드 1~3장 모으기 | CPI, FOMC, 고용지표처럼 곧 오는 큰 이벤트를 적는다. | 마지막 패널에서 “다음 화 예고”를 더 자연스럽게 만들 수 있다. | `economic_events_json`에 이벤트명, 발표시각, 중요도, 예상/이전값이 저장된다. |
| 4 | 섹터/테마 색깔표 만들기 | 오늘 강한 업종과 약한 업종을 초록/빨강으로 본다. | 매번 같은 배경이 아니라 AI 타워, 오일 항구, 은행 금고처럼 장면이 다양해진다. | `sector_heatmap_json`에 섹터 ETF/테마 basket 변화율이 저장된다. |
| 5 | Claude에게 이야기 설계도 먼저 쓰게 하기 | 바로 만화를 쓰게 하지 말고, 먼저 “1컷~8컷에 무슨 일이 일어날지” 계획표를 쓰게 한다. | 이야기가 원인→갈등→결과→다음 예고로 더 또렷해진다. | `StoryBeatPlan`이 생성되고 그 계획을 기반으로 `EpisodeScript`가 생성된다. |

### 7.3 데이터 강화 작업단계

#### 1단계 — 날짜부터 정확하게 맞춘다

- `target_date`를 모든 데이터 수집기가 실제로 사용하게 한다.
- 미국 시장일과 한국 에피소드 날짜를 헷갈리지 않게 `episode_date`와 `market_date`를 나눈다.
- 각 데이터가 “언제 나온 값인지”를 `source_date`로 남긴다.

**초등학생 버전:** 숙제장 날짜와 실제 숙제한 날짜를 맞춘다.

#### 2단계 — 뉴스는 많이가 아니라 “좋은 것 3개”만 고른다

- 뉴스 API를 붙이더라도 Claude에게 기사 20개를 주지 않는다.
- 관련도 높은 뉴스 3개만 고른다.
- 각 뉴스는 제목, 출처 URL, 시간, 한 줄 요약, 관련 지표만 저장한다.
- 기사 본문을 길게 저장하지 않는다.

**초등학생 버전:** 발표할 때 책 한 권을 다 읽지 않고, 중요한 문장 3개만 카드에 적는다.

#### 3단계 — 경제 이벤트로 다음 화 예고를 만든다

- CPI, FOMC, 고용, 실적, 국채입찰 등 큰 이벤트를 수집한다.
- 오늘 시장이 조용해도 “내일 큰 시험이 있다”는 긴장감을 만들 수 있다.
- panel 7의 `next_hook`에 이벤트를 자연스럽게 넣는다.

**초등학생 버전:** 오늘 이야기가 끝나도 “내일 운동회가 있다”는 예고를 넣는다.

#### 4단계 — 섹터/테마로 그림 배경을 다양하게 만든다

- 반도체/AI가 약하면 데이터센터나 GPU 코어 배경을 쓴다.
- 에너지가 흔들리면 오일 항구나 파이프라인 배경을 쓴다.
- 금융이 흔들리면 은행 금고나 국채 경매장 배경을 쓴다.

**초등학생 버전:** 매번 같은 운동장에서 싸우지 말고, 오늘 주제에 맞는 장소로 간다.

### 7.4 스토리 강화 작업단계

#### 1단계 — Claude에게 원재료를 정리해서 준다

Claude에게 raw data를 잔뜩 주지 말고, 아래처럼 “이야기 도시락”을 만들어 준다.

```yaml
Narrative Context Pack:
  오늘의 원인: "금리가 다시 오르고 기술주가 약해져 시장이 긴장했다"
  중요한 증거:
    - "미국 10년물 금리가 기준선을 넘음"
    - "AI/반도체 섹터가 약세"
    - "이틀 뒤 CPI 발표 예정"
  오늘의 빌런 이유: "Debt Titan이 다시 힘을 얻음"
  그림 배경 후보: ["국채 경매장", "붉은 전광판", "금고 문"]
  금지할 말: ["제공되지 않은 뉴스 만들기", "투자 추천하기"]
```

#### 2단계 — 바로 대본을 쓰지 말고 8컷 계획표부터 만든다

| 컷 | 역할 | 해야 할 일 |
|---:|---|---|
| 1 | Hook | 오늘 시장의 분위기를 한 장면으로 보여준다. |
| 2 | 원인 | 시장이 왜 흔들렸는지 숫자/뉴스 1개로 보여준다. |
| 3 | 빌런/상황 | 빌런이 힘을 얻거나 중립 상황을 보여준다. |
| 4 | 히어로 감정 | 히어로가 두려움/갈등/결심을 보인다. |
| 5 | 전환점 | 전투나 판단이 바뀌는 순간을 만든다. |
| 6 | 결과 | 코드가 정한 battle outcome을 그대로 보여준다. |
| 7 | 다음 예고 | 다음 경제 이벤트나 남은 불안을 보여준다. |
| 8 | 면책 | 투자 참고 정보이며 투자 권유가 아님을 알린다. |

#### 3단계 — Claude가 쓴 대본을 검사한다

- 없는 뉴스나 없는 숫자를 지어냈는가?
- 빌런/히어로 Canon ID가 맞는가?
- 8컷 흐름이 자연스러운가?
- 투자 추천처럼 보이는 문구가 없는가?
- 마지막 면책 문구가 있는가?

#### 4단계 — 점수가 낮으면 다시 쓰게 한다

- 시장 근거가 부족하면 뉴스/지표를 더 명확히 넣어 다시 생성한다.
- 장면이 반복되면 섹터/테마 배경을 바꿔 다시 생성한다.
- 캐릭터 감정이 약하면 belief의 fear/lie/truth를 최소 1컷에 넣게 한다.

### 7.5 개발자가 바로 실행할 추천 순서

| 주차 | 목표 | 개발 작업 | 결과물 |
|---|---|---|---|
| 1주차 | 데이터 날짜 정확도 | `target_date`, `market_date`, `source_date` 정리 | 틀린 날짜 데이터 방지 |
| 2주차 | 배경 다양화 | `sector_breadth_fetcher.py` 추가 | AI/오일/은행 등 장면 배경 강화 |
| 3주차 | 다음 화 예고 강화 | `economic_calendar_fetcher.py` 추가 | CPI/FOMC/고용 이벤트 hook 강화 |
| 4주차 | 원인 서사 강화 | `news_fetcher.py` + `story_context_builder.py` 추가 | 오늘 시장 원인 top 3 제공 |
| 5주차 | Claude 스토리 강화 | `StoryBeatPlan` 2-pass 생성 추가 | 8컷 흐름이 더 선명한 대본 |
| 6주차 | 안전 검사 | factuality/quality gate 추가 | 없는 뉴스 창작·투자 추천 방지 |

### 7.6 이번 작업의 최우선 결론

가장 먼저 만들 것은 복잡한 새 이미지 기능이 아니다. 우선순위는 아래 순서다.

1. **정확한 날짜의 데이터**를 모은다.
2. **오늘 시장을 설명하는 뉴스 3개**를 고른다.
3. **다음 경제 이벤트 1~3개**를 고른다.
4. **섹터/테마 색깔표**로 장면 배경을 고른다.
5. Claude가 **8컷 이야기 계획표**를 먼저 쓰고, 그 다음 대본을 쓰게 한다.

이렇게 하면 미장코믹스는 단순히 “숫자가 움직여서 싸운다”가 아니라, **“오늘 시장에서 어떤 일이 있었고, 그래서 어떤 빌런이 나타났고, 히어로가 무엇을 깨달았고, 다음 화에 어떤 위기가 오는지”**를 보여주는 콘텐츠가 된다.

---


## 8. 현재 과거 데이터 연속성 / Supabase 운영 여부 답변

### 8.1 짧은 답변

- **Supabase로 운영하는 구조가 맞다.** 코드 기준으로 `SUPABASE_URL`, `SUPABASE_KEY`, `SUPABASE_SCHEMA=icg`를 사용해 `icg.daily_snapshots`, `icg.daily_analysis`, `icg.episode_assets`, `icg.arc_state`, `icg.run_logs` 등에 저장/조회한다.
- **과거 데이터 연속성은 “부분적으로” 동작한다.** 전일 대비 delta, 이전 story_state, arc_state, stage 재개용 JSON 저장은 있다.
- 하지만 **완전히 안정적인 과거 연속성이라고 보기는 어렵다.** 이유는 분석 단계가 target date의 직전 데이터를 정확히 찾기보다 `daily_snapshots` 최신 N개를 보는 구조이고, story_state는 “전날 날짜 1일 전”만 찾기 때문에 주말/휴장/누락일이 있으면 초기값으로 돌아갈 수 있기 때문이다.

### 8.2 Supabase로 운영 중인 근거

| 영역 | Supabase 테이블/스키마 | 현재 역할 |
|---|---|---|
| 원천 시장 스냅샷 | `icg.daily_snapshots` | STEP 2 데이터 수집 결과 저장 |
| 분석 결과 | `icg.daily_analysis` | event_type, battle result, delta, ctx, story_state 저장 |
| 에피소드 자산 | `icg.episode_assets` | script_json, battle_json, panel/slides 경로, status 저장 |
| 장기 아크 상태 | `icg.arc_state` | active_villain, arc_day, tension 등 단일 행 상태 저장 |
| 실행 로그 | `icg.run_logs` | 단계별 로그 저장. 실패 시 파일 로그로 degraded |
| 발행 이력 | `icg.published_comics` | 중복 발행 방어용 이력 조회 |

즉, 현재 운영 DB의 중심은 Supabase `icg` schema다. GitHub Actions도 운영 환경변수로 `SUPABASE_URL`, `SUPABASE_KEY`, `SUPABASE_SCHEMA=icg`를 주입한다.

### 8.3 현재 연속성이 되는 부분

#### 1) 시장 데이터 전일 대비 연속성

- `daily_snapshots`에서 최신 2개 row를 가져온다.
- 현재 row와 이전 row를 비교해 VIX, WTI, DGS10, SPY 등 delta를 만든다.
- 이 delta가 event_type, battle_result, Claude prompt에 들어간다.

**쉬운 말:** 오늘 점수와 바로 전 점수를 비교해서 “얼마나 변했는지”를 본다.

#### 2) 스토리 상태 연속성

- `SCENARIO_V2_ENABLED=true`일 때 `story_state_json`을 전날 `daily_analysis`에서 읽는다.
- 게스트 캐릭터 등장, cooldown, arc_episode 같은 스토리 상태에 사용한다.
- persist 이후 오늘 `story_state_json`을 다시 저장한다.

**쉬운 말:** 어제 만화에서 누가 나왔는지 기억하고, 오늘 또 나올지 결정한다.

#### 3) 아크 상태 연속성

- `ARC_STATE_V3_ENABLED=true`일 때 `icg.arc_state` 단일 행을 읽는다.
- active villain, arc_day, arc_tension, villain_signature 등을 다음 에피소드에 이어 쓴다.
- persist 이후 갱신된 arc_state를 다시 Supabase에 저장한다.

**쉬운 말:** 시즌 전체의 큰 줄거리 상태를 공책 한 장에 계속 이어 쓴다.

#### 4) 멀티 스테이지 재개 연속성

- analysis 이후 `analysis_ctx_json`을 `daily_analysis`에 저장한다.
- narrative 이후 `narrative_script_json`을 `daily_analysis`에 저장한다.
- persist/image 단계가 따로 실행되어도 DB에서 ctx/script를 복원할 수 있다.

**쉬운 말:** 중간에 멈춰도 “저장된 세이브 파일”을 불러와 다음 단계부터 이어 한다.

### 8.4 현재 연속성의 약한 부분

| 약점 | 현재 동작 | 위험 |
|---|---|---|
| 특정 날짜 분석 | analysis가 기본적으로 최신 snapshot 2개를 읽는다. | 과거 날짜 재실행 시 그 날짜 기준 직전 데이터가 아니라 DB 최신 데이터가 섞일 수 있다. |
| 휴장/주말 story_state | story_state는 `episode_date - 1일`만 조회한다. | 금요일 다음 월요일처럼 중간 날짜가 비면 story_state가 없다고 보고 초기값으로 돌아갈 수 있다. |
| feature flag 의존 | story_state는 `SCENARIO_V2_ENABLED`, arc_state는 `ARC_STATE_V3_ENABLED`가 켜져야 강하게 동작한다. | flag가 꺼진 운영일에는 장기 연속성이 약해진다. |
| episode row 식별 | `episode_assets`는 `(episode_date,event_type)` 중심으로 upsert/patch한다. | 같은 날짜 같은 event_type 재실행 시 이전 에피소드가 덮일 수 있다. |
| 데이터 신선도 | snapshot 값은 저장되지만 source_date/freshness가 충분히 분리되어 있지 않다. | “오늘 에피소드”가 실제로 어느 시장일 값을 썼는지 추적이 어렵다. |

### 8.5 결론

현재 시스템은 Supabase 기반으로 운영되고 있고, 과거 데이터와 스토리를 이어가려는 장치도 이미 있다. 다만 운영 베타 기준으로는 **“연속성이 있다”가 아니라 “연속성의 뼈대는 있으나 날짜/휴장/재실행 케이스에서 깨질 수 있다”**고 판단하는 것이 맞다.

### 8.6 데이터/스토리 강화를 위한 연속성 우선 보완 작업

초기 최우선은 새 뉴스 API보다도 아래 4개다.

1. **날짜 기준 조회 수정**
   - `get_latest(2)`만 쓰지 말고, `episode_date` 이하의 최신 2개 snapshot을 조회한다.
   - 예: `snapshot_date <= episode_date order by snapshot_date desc limit 2`.

2. **story_state 조회 수정**
   - `episode_date - 1일`만 보지 말고, `analysis_date < episode_date` 중 가장 최신 story_state를 찾는다.
   - 이렇게 해야 주말/휴장 후에도 금요일 스토리가 월요일로 이어진다.

3. **episode_id 중심 저장으로 변경**
   - `episode_assets` patch/upsert 기준을 `(episode_date,event_type)`에서 `episode_id` 또는 `(episode_date,episode_no)`로 바꾼다.
   - 그래야 같은 날짜 재실행/강제 실행에도 에피소드가 덮이지 않는다.

4. **source_date / freshness 저장**
   - 각 데이터가 실제로 어느 날짜 값인지 저장한다.
   - Claude prompt에도 “오늘 에피소드 날짜”와 “시장 데이터 기준일”을 구분해서 전달한다.

이 4개가 해결되면, 이후 뉴스 카드/경제 이벤트 카드/섹터 색깔표를 붙였을 때 스토리도 훨씬 안정적으로 이어진다.

---

## 9. 운영 베타 체크리스트

### 9.1 매일 실행 전

- [ ] `FRED_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_SUB_PAY_KEY`, `SUPABASE_URL`, `SUPABASE_KEY`, `NOTION_API_KEY` 존재 확인
- [ ] Notion prompt/constant page 로드 성공 여부 확인
- [ ] 미국 시장 휴장일/주말 여부 확인
- [ ] `SCENARIO_V2_ENABLED`, `EPISODE_TYPE_V3_ENABLED`, Phase 2.3 flags 값 확인

### 9.2 STEP 2~3 이후

- [ ] 필수 지표 누락 여부 확인
- [ ] event_type이 데이터 부족으로 인해 NORMAL이 된 것은 아닌지 확인
- [ ] battle_result outcome과 balance 확인
- [ ] scenario_type 반복 여부 확인

### 9.3 STEP 4 이후

- [ ] EpisodeScript schema validation 통과
- [ ] disclaimer panel과 caption_x_final 확인
- [ ] NO_BATTLE 시 villain 미등장 확인
- [ ] 시장 수치가 market_ref에 최소 1~2개 이상 반영되었는지 확인

### 9.4 STEP 6 이후

- [ ] panel image 성공률 확인
- [ ] Gemini cost가 0으로 기록되면 현재는 비용 추적 결함으로 간주
- [ ] REF 이미지 누락/Canon violation 로그 확인
- [ ] fallback panel 수 확인

### 9.5 STEP 7~8 전

- [ ] 슬라이드 8장 생성 확인
- [ ] 텍스트 잘림/한글 폰트 렌더링 확인
- [ ] publish 전 quality gate 통과 확인
- [ ] schedule 자동 발행 대상 채널 확인

---

## 10. 개선 로드맵

### Phase A — 즉시 안정화(P0)

1. 날짜 처리 수정
   - KST 명시
   - target_date 기반 fetch
   - market_date/source_date 저장

2. Gemini 비용/재시도 수정
   - usage_metadata 파싱
   - total_cost 누적
   - retry attempt 전달 방식 수정

3. episode_assets key 정렬
   - episode_id 중심 patch/load
   - state transition guard 추가

### Phase B — 품질 게이트(P1)

1. 데이터 품질 점수 도입
2. publish 전 quality gate 추가
3. Notion loader 필수 섹션 검증과 content hash 저장
4. fallback panel 허용 기준 운영 변수화

### Phase C — 운영 관측성(P1~P2)

1. Supabase dashboard query 세트 추가
2. run log에 prompt version / notion hash / model / cost / token 기록
3. daily/weekly 운영 리포트 자동 생성
4. Notion gemini 영역 자동 업로드 스크립트 추가

---


## 11. 개발 착수 파일럿 — 분석/스토리 고도화 1차 구현

### 11.1 이번 파일럿에서 착수한 단위

| 그룹 | 목표 | 구현 내용 | Feature Flag |
|---|---|---|---|
| 데이터→스토리 컨텍스트 | 시장 수치를 Claude가 바로 쓰기 좋은 이야기 재료로 압축 | `engine/analysis/story_context_builder.py` 추가. delta, optional news/event/sector 입력을 `Narrative Context Pack`으로 변환 | `NARRATIVE_CONTEXT_ENABLED` |
| 8컷 설계도 | Claude가 바로 대본을 쓰기 전에 8컷 흐름을 먼저 고정 | `engine/narrative/story_planner.py` 추가. `StoryBeatPlan`을 결정론적으로 생성 | `STORY_PLANNER_ENABLED` |
| 스키마 | 파일럿 결과를 검증 가능한 형태로 고정 | `StoryBeat`, `StoryBeatPlan` Pydantic schema 추가 | 코드 상시 사용 |
| 프롬프트 주입 | Claude에게 데이터 카드와 8컷 설계도를 전달 | `narrative_user.j2`, `prompt_tpl.py`, `claude_client.py`에 context/plan 전달 추가 | context/plan 존재 시 |
| 파이프라인 연결 | 기존 운영 흐름을 깨지 않고 pilot만 켤 수 있게 연결 | `scripts/run_market.py` STEP 3에서 context/plan 생성 후 STEP 4로 전달 | flag OFF 시 기존 동작 |

### 11.2 파일럿 동작 방식

1. `NARRATIVE_CONTEXT_ENABLED=true`이면 STEP 3에서 `Narrative Context Pack`을 만든다.
2. `STORY_PLANNER_ENABLED=true`이면 같은 STEP 3에서 `StoryBeatPlan`도 만든다.
3. 생성된 결과는 `ctx`에 들어가고, 기존처럼 `analysis_ctx_json`에 저장된다.
4. STEP 4에서 Claude prompt에 `Narrative Context Pack`과 `StoryBeatPlan`을 넣는다.
5. flag가 꺼져 있으면 기존 운영 흐름과 동일하게 동작한다.

### 11.3 파일럿 테스트 결과

- 단위 파일럿 테스트: context builder, story planner, prompt rendering을 각각 검증한다.
- 전수 테스트: 기존+파일럿 452개 테스트 전체 통과를 확인한다.
- Lint: ruff 통과를 확인한다.

### 11.4 다음 반복 루프

문제가 발견되면 아래 순서로 반복한다.

1. 분석/설계 보완
2. 상세설계 보완
3. 권고사항 즉시 개발 착수
4. 단위별 파일럿 테스트
5. 개발 완료 후 전수 테스트
6. 실패 시 다시 1번으로 회귀

---


## 12. 운영반영 전 전수점검 — 누락/유실 프로세스 확인

### 12.1 점검 결론

운영반영 전 데이터/스토리 파일럿의 흐름을 전수 점검한 결과, 코드 내부의 저장/복원 흐름은 다음 경로로 이어진다.

1. STEP 3에서 `Narrative Context Pack` / `StoryBeatPlan` 생성
2. `ctx`에 저장
3. `daily_analysis.analysis_ctx_json`에 저장
4. 별도 narrative stage 실행 시 `analysis_ctx_json`에서 복원
5. STEP 4에서 Claude prompt로 전달

다만 운영반영 전 점검에서 **GitHub Actions 입력/환경변수 연결 누락**이 발견되어 보완했다. 즉, 코드에는 feature flag가 있었지만 workflow_dispatch와 Repository Variables를 통해 켜는 통로가 부족했다.

### 12.2 보완 완료 항목

| 점검 항목 | 위험 | 조치 |
|---|---|---|
| Workflow flag 입력 | 운영자가 `NARRATIVE_CONTEXT_ENABLED`, `STORY_PLANNER_ENABLED`를 수동/변수로 켜기 어려움 | `run_market.yml`에 `narrative_context`, `story_planner` 입력 추가 |
| Workflow env 전달 | GitHub Actions에서 pilot flag가 분석 단계에 전달되지 않을 수 있음 | `NARRATIVE_CONTEXT_ENABLED`, `STORY_PLANNER_ENABLED` env 추가 |
| 로그 확인 | 운영 실행 시 어떤 pilot flag가 켜졌는지 확인 어려움 | STEP 4 로그에 두 flag 출력 추가 |
| DB 저장 유실 | context/plan이 stage 분리 실행 시 사라질 수 있음 | `ctx`에 넣고 기존 `analysis_ctx_json` 저장/복원 경로 사용 |
| Notion 템플릿 미반영 | Notion runtime 템플릿이 아직 새 block을 모르면 Claude에 전달 누락 가능 | `claude_client.py` fallback append로 보완 |
| JSON 직렬화 | Supabase JSON 저장 시 Pydantic 객체가 들어가면 실패 가능 | `StoryBeatPlan.model_dump()` 저장 + JSON 직렬화 테스트 추가 |

### 12.3 운영반영 전 남은 주의사항

- 운영 기본값은 계속 `false`이므로, pilot은 의도적으로 켜기 전까지 기존 동작을 바꾸지 않는다.
- `STORY_PLANNER_ENABLED=true`만 켜고 `NARRATIVE_CONTEXT_ENABLED=false`이면 planner가 생성되지 않는다. 두 기능을 같이 켜는 것을 권장한다.
- 이번 파일럿은 아직 실제 뉴스 API 수집을 붙이지 않았다. optional `news_items`, `economic_events`, `sector_heatmap` 입력을 받을 수 있는 구조만 먼저 열었다.
- 운영 첫 반영은 `stage=analysis` shadow run으로 `analysis_ctx_json`에 context/plan이 저장되는지 확인한 뒤 narrative까지 확장하는 순서를 권장한다.

---

## 13. 테스트/검증 현황

- 전체 테스트: `python -m pytest tests/ -q` → 452 passed
- Lint: `ruff check . --line-length=100` → All checks passed

테스트 결과는 현재 코드의 기존 기대 동작이 안정적으로 유지됨을 보여준다. 다만 위 문제 중 상당수는 “테스트 미통과 버그”라기보다 **운영 데이터 정합성, 비용 관측성, 자동 발행 리스크**에 해당하므로 별도 운영/통합 테스트가 필요하다.

---

## 14. Notion 반영 메모

현재 세션에는 `NOTION_API_KEY`와 `NOTION_TRACKER_DS`가 설정되어 있지 않아 Notion에 직접 작성하지 못했다. Notion gemini 영역에는 아래 제목으로 등록하는 것을 권장한다.

- 제목: `ICG 운영 베타 시스템 분석 — 동작 원리 및 리스크 점검 (2026-06-01)`
- 위치: `미장코믹스 / gemini 영역`
- 태그: `운영베타`, `Gemini`, `시장데이터`, `스토리생성`, `이미지생성`, `리스크점검`
- 우선 액션: P0 3건(날짜 정합성, Gemini 비용/재시도, episode_id key 정렬) + 데이터/스토리 최우선 5단계 + 연속성 보완 4건 + 개발 착수 파일럿 + 운영반영 전 flag/env 누락 보완
