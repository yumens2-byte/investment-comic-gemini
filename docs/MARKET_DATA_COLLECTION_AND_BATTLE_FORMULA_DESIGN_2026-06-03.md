# 시장데이터 추가 수집 및 스토리/승패 판단 계산식 상세 설계

작성일: 2026-06-03  
연결 문서: `docs/MARKET_DATA_COVERAGE_GAP_ANALYSIS_2026-06-03.md`  
목표: 부족한 시장 데이터 수집 설계를 구체화하고, 그 데이터를 스토리 선택·캐릭터 등장·승패 계산에 연결하는 상세 설계 초안을 정의한다.

## 1. 설계 목표

1. **시장 원인 설명력 강화**: 현재 매크로/지수/BTC 중심 스냅샷을 섹터·breadth·신용·금리·FX·원자재·뉴스/일정까지 확장한다.
2. **스토리 결정의 근거화**: “왜 오늘 이 장면/캐릭터/빌런인가?”를 `top_evidence`, `scene_symbols`, `risk_drivers`, `sector_rank`로 설명한다.
3. **승패 계산의 데이터 정합성 강화**: Claude가 승패를 임의로 바꾸지 않도록 `battle_result`는 deterministic formula로 고정하고, LLM은 해석만 하게 한다.
4. **투자 조언 회피**: `buy_watch`/`reduce_list` 대신 기본 명칭은 `watch_areas`/`caution_areas`로 두고, 코믹스/관찰용 판단임을 명확히 한다.
5. **점진 도입**: JSONB 기반 확장으로 빠르게 운영 연결 후, 필요 시 별도 테이블로 정규화한다.

## 2. 현재 구조에서 연결해야 할 지점

| 단계 | 현재 책임 | 상세 설계에서 추가할 것 |
| --- | --- | --- |
| STEP 2 `step_data()` | FRED/yfinance/F&G/crypto/sentiment 수집 후 `daily_snapshots` upsert | 섹터, breadth, 확장 금리·신용·FX·원자재, 뉴스/일정 fetcher 추가 |
| STEP 3 `delta_engine.compute()` | snapshot scalar 필드 전일 대비 delta 계산 | JSONB 신호를 `signal_pack`으로 정규화하고 핵심 delta를 추출 |
| STEP 3 `event_classifier.classify()` | WTI/VIX/DGS10/SPY 중심 이벤트 판정 | composite `risk_score`, `shock_score`, `sector_pressure_score` 기반 판정 |
| STEP 3 `scenario_selector` | VIX/WTI 기반 LOW/MEDIUM/HIGH | multi-domain risk score 기반 LOW/MEDIUM/HIGH |
| STEP 3 `battle_calc` | 캐릭터 base + 일부 시장 보너스 → balance | hero/villain market alignment 점수, evidence confidence, sector domain bonus 추가 |
| STEP 4 `story_planner` | `narrative_context_pack`의 evidence로 8패널 beat 생성 | panel별 evidence role, sector scene, next catalyst hook 강화 |

## 3. 추가 수집 데이터 설계

### 3.1 공통 데이터 모델: `MarketSignal`

모든 신규 fetcher는 내부적으로 아래 형태로 정규화한다. DB에는 JSONB로 저장하되, 테스트와 계산식은 이 구조를 기준으로 한다.

```json
{
  "id": "sector:XLK",
  "domain": "sector",
  "name": "Technology",
  "symbol": "XLK",
  "value": -1.2,
  "unit": "pct",
  "change_pct": -1.2,
  "relative_pct": -0.4,
  "z_score": -1.1,
  "state": "laggard",
  "story_role": "AI tower pressure",
  "scene_symbol": "Technology red sector board",
  "source": "yfinance",
  "as_of": "2026-06-03",
  "confidence": 0.92
}
```

필수 필드:

- `id`: `domain:symbol` 또는 `domain:event_id`
- `domain`: `sector`, `breadth`, `rates`, `credit`, `fx`, `commodity`, `crypto`, `news`, `calendar`
- `value`/`change_pct`: 계산식 입력값
- `state`: 스토리/판단 레이블
- `story_role`, `scene_symbol`: Narrative Context Pack으로 직접 전달할 연출 소재
- `confidence`: 수집 지연/결측/캐시 fallback 반영

### 3.2 P0 Fetcher: 섹터 히트맵

신규 모듈: `engine/data/sector_fetcher.py`

| 항목 | 설계 |
| --- | --- |
| 수집 대상 | `XLK`, `XLF`, `XLE`, `XLV`, `XLI`, `XLY`, `XLP`, `XLU`, `XLB`, `XLRE`, `XLC` |
| 수집 방식 | yfinance 병렬 다운로드, `period=5d`, `auto_adjust=True` |
| 산출값 | 섹터별 `change_pct`, `relative_pct = sector_change - spy_change`, rank, state |
| 저장 위치 | `daily_snapshots.sector_heatmap JSONB` 우선 |
| 스토리 연결 | 상위/하위 2개 섹터를 `scene_symbols`, `top_evidence` 후보로 전달 |

`state` 판정 초안:

| 조건 | state | 의미 |
| --- | --- | --- |
| `relative_pct >= +1.0` and `change_pct > 0` | `leader` | 시장 대비 강한 주도 섹터 |
| `relative_pct >= +0.5` | `relative_safe` | 방어/상대 강세 |
| `relative_pct <= -1.0` and `change_pct < 0` | `laggard` | 약세 주도 섹터 |
| `abs(change_pct) >= 2.0` | `volatile` | 장면 소재로 우선 채택 |
| else | `neutral` | 배경 데이터 |

### 3.3 P0 Fetcher: 경제일정/이벤트 캘린더

신규 모듈: `engine/data/economic_calendar_fetcher.py`

| 항목 | 설계 |
| --- | --- |
| 수집 대상 | CPI, PCE, FOMC, NFP, 실업률, ISM, GDP, 소매판매, Treasury auction |
| 저장 위치 | `daily_snapshots.event_calendar JSONB` |
| 기간 | D-1 ~ D+7 |
| 중요도 | 1~5. CPI/FOMC/NFP/PCE는 5 |
| 스토리 연결 | `foreshadow` 및 NEXT_HOOK panel에 주입 |

이벤트 구조:

```json
{
  "name": "CPI",
  "date": "2026-06-10",
  "release_time": "08:30 ET",
  "importance": 5,
  "domain": "inflation",
  "story_use": "inflation_gate",
  "confidence": 0.9
}
```

### 3.4 P0 Fetcher: 뉴스 요약/공식 이벤트

신규 모듈: `engine/data/news_fetcher.py`

| 항목 | 설계 |
| --- | --- |
| 수집 대상 | 공식기관/주요 매체 headline 1~5건, 안전 요약 |
| 필터 | 시장 관련성, 중복 제거, 투자 추천 표현 제거 |
| 저장 위치 | `daily_snapshots.news_items JSONB` 또는 `daily_news_items` |
| 스토리 연결 | `top_evidence`에 최소 1건 포함 가능 |

뉴스 구조:

```json
{
  "id": "news:fed-watch-20260603",
  "source": "official/news",
  "source_url": "https://example.com/...",
  "headline": "...",
  "safe_summary_ko": "연준 발언 대기 속 금리 경계감이 커졌다.",
  "relevance_score": 0.88,
  "story_use": "policy_uncertainty",
  "confidence": 0.85
}
```

### 3.5 P1 Fetcher: 시장 내부 체력/Breadth

신규 모듈: `engine/data/breadth_fetcher.py`

| 데이터 | 추천 프록시 | 용도 |
| --- | --- | --- |
| Equal weight relative | `RSP` vs `SPY` | 대형주 쏠림 감지 |
| Small cap | `IWM` | 위험선호/내부 체력 |
| High beta vs low vol | `SPHB` vs `SPLV` | 공격/방어 로테이션 |
| 신고가/신저가 | API 가능 시 | 시장 폭 고도화 |

상태 판정:

```text
breadth_score = clamp(
  50
  + 10 * sign(rsp_spy_spread_pct)
  + 8  * sign(iwm_change_pct - spy_change)
  + 6  * sign(high_beta_low_vol_spread),
  0, 100
)
```

- `breadth_score >= 65`: `broad_participation`
- `45 <= breadth_score < 65`: `mixed`
- `breadth_score < 45`: `narrow_or_weak`

### 3.6 P1 Fetcher: 금리/신용 확장

신규 모듈 후보:

- `engine/data/rates_fetcher.py`: 2Y, 30Y, real yield, MOVE proxy
- `engine/data/credit_fetcher.py`: IG OAS, LQD/HYG/JNK, KRE/KBE

금리/신용 shock 입력값:

```text
rates_pressure =
  z(DGS10_1d_change) * 0.35
+ z(DGS2_1d_change)  * 0.25
+ z(real_yield)      * 0.25
+ yield_curve_inversion_penalty * 0.15

credit_pressure =
  z(HY_OAS)          * 0.35
+ z(IG_OAS)          * 0.25
+ negative_return(HYG) * 0.20
+ negative_return(KRE) * 0.20
```

### 3.7 P1 Fetcher: FX/원자재 확장

신규 모듈 후보:

- `engine/data/fx_fetcher.py`: USDJPY, EURUSD, USDCNH, EWY 또는 KOSPI proxy
- `engine/data/commodity_fetcher.py`: Gold, Copper, NatGas, broad commodity ETF

스토리 역할:

| 영역 | 스토리 역할 |
| --- | --- |
| USDJPY/USDCNH | 글로벌 달러 스트레스와 아시아 통화 압력 |
| EWY/KOSPI | 한국 독자 맥락 보강 |
| Gold | 방어/전쟁/실질금리 반응 |
| Copper | 성장 기대/중국 경기 프록시 |
| NatGas | 에너지 쇼크 보조 신호 |

## 4. 저장 스키마 상세 설계

### 4.1 빠른 도입안: `daily_snapshots` JSONB 컬럼 추가

마이그레이션 초안:

```sql
ALTER TABLE icg.daily_snapshots
  ADD COLUMN IF NOT EXISTS sector_heatmap JSONB,
  ADD COLUMN IF NOT EXISTS market_breadth JSONB,
  ADD COLUMN IF NOT EXISTS rates_detail JSONB,
  ADD COLUMN IF NOT EXISTS credit_detail JSONB,
  ADD COLUMN IF NOT EXISTS fx_detail JSONB,
  ADD COLUMN IF NOT EXISTS commodity_detail JSONB,
  ADD COLUMN IF NOT EXISTS event_calendar JSONB,
  ADD COLUMN IF NOT EXISTS news_items JSONB,
  ADD COLUMN IF NOT EXISTS signal_quality JSONB;
```

장점: 기존 upsert 구조를 크게 바꾸지 않고 빠르게 연결 가능.  
단점: 장기 백테스트/쿼리에는 별도 테이블보다 불리하다.

### 4.2 정규화 확장안: 별도 신호 테이블

```sql
CREATE TABLE IF NOT EXISTS icg.daily_market_signals (
  signal_date DATE NOT NULL,
  signal_id TEXT NOT NULL,
  domain TEXT NOT NULL,
  symbol TEXT,
  name TEXT,
  value NUMERIC,
  change_pct NUMERIC,
  relative_pct NUMERIC,
  z_score NUMERIC,
  state TEXT,
  story_role TEXT,
  scene_symbol TEXT,
  source TEXT,
  confidence NUMERIC,
  raw JSONB,
  created_at TIMESTAMPTZ DEFAULT now(),
  PRIMARY KEY (signal_date, signal_id)
);
```

권장 순서: **JSONB → 2주 운영 검증 → 필요 시 `daily_market_signals` 병행 적재**.

### 4.3 `daily_analysis` 판단데이터 확장

마이그레이션 초안:

```sql
ALTER TABLE icg.daily_analysis
  ADD COLUMN IF NOT EXISTS risk_drivers JSONB,
  ADD COLUMN IF NOT EXISTS sector_rank JSONB,
  ADD COLUMN IF NOT EXISTS asset_rank JSONB,
  ADD COLUMN IF NOT EXISTS watch_areas JSONB,
  ADD COLUMN IF NOT EXISTS caution_areas JSONB,
  ADD COLUMN IF NOT EXISTS formula_trace JSONB;
```

`formula_trace`는 운영 디버깅용이다.

```json
{
  "risk_score": 67,
  "shock_score": 58,
  "story_pressure_score": 72,
  "hero_power_formula": {"base": 78, "alignment": 8, "arc": 2},
  "villain_power_formula": {"base": 74, "market_pressure": 16, "sector_domain": 6},
  "confidence_penalty": -3
}
```

## 5. Story Decision Formula 설계

### 5.1 Composite Risk Score

기존 `risk_level`은 VIX/WTI 중심이므로, 신규 설계에서는 0~100 `risk_score`를 먼저 계산한다.

```text
risk_score = clamp(
  0.20 * volatility_score
+ 0.20 * equity_breadth_score
+ 0.15 * rates_score
+ 0.15 * credit_score
+ 0.10 * fx_score
+ 0.10 * commodity_score
+ 0.05 * crypto_score
+ 0.05 * news_calendar_score,
  0, 100
)
```

권장 레벨:

| risk_score | risk_level | 기본 의미 |
| --- | --- | --- |
| 0~34 | LOW | NO_BATTLE/INTEL 가능 |
| 35~64 | MEDIUM | ONE_VS_ONE/Tactical 가능 |
| 65~100 | HIGH | BATTLE/SHOCK/ALLIANCE 가능 |

### 5.2 Domain Pressure Score

스토리 원인을 도메인별로 분해한다.

```text
pressure(domain) =
  magnitude_score(domain) * 0.45
+ change_speed_score(domain) * 0.25
+ cross_asset_confirmation(domain) * 0.20
+ evidence_confidence(domain) * 0.10
```

예시:

- `volatility`: VIX level, VIX pct, VIX term structure
- `rates`: DGS10, DGS2, real yield, yield curve
- `credit`: HY/IG OAS, HYG/LQD/KRE
- `sector`: sector relative under/overperformance
- `fx`: DXY, USDKRW, USDJPY, USDCNH

상위 3개 domain이 `narrative_context_pack.top_evidence`와 `market_cause`를 만든다.

### 5.3 Episode Type Formula

```text
if data_confidence < 0.55:
    episode_type = INTEL
elif shock_score >= 75:
    episode_type = SHOCK
elif risk_score >= 65 and max_domain_pressure >= 70:
    episode_type = BATTLE
elif previous_episode_was_battle and arc_tension >= 45:
    episode_type = AFTERMATH
elif risk_score <= 34 and days_since_last >= 2:
    episode_type = INTEL
elif 45 <= risk_score < 65:
    episode_type = TACTICAL
else:
    episode_type = NORMAL
```

`shock_score` 예시:

```text
shock_score = max(
  volatility_shock,
  oil_shock,
  rates_shock,
  credit_shock,
  fx_shock,
  sector_crash_shock,
  news_event_shock
)
```

### 5.4 Scenario Formula

```text
if episode_type in {NORMAL, INTEL} and risk_score < 35:
    scenario = NO_BATTLE
elif episode_type in {BATTLE, SHOCK} and risk_score >= 65 and cross_asset_confirmation >= 2:
    scenario = ALLIANCE
else:
    scenario = ONE_VS_ONE
```

`cross_asset_confirmation`은 같은 방향 위험 신호가 몇 개 도메인에서 확인되는지 센다.

예시:

- VIX 상승 + SPY 하락 + HY 확대 = 3
- WTI 급등 + Gold 상승 + 방산 강세 = 3
- DXY 상승 + USDKRW 상승 + EWY 약세 = 3

### 5.5 Character Selection Formula

캐릭터 선택은 “이벤트 타입”만이 아니라 `domain_pressure` 기반으로 바꾼다.

| dominant_domain | villain | primary_hero | 보조 히어로 후보 |
| --- | --- | --- | --- |
| rates | Debt Titan | Iron Securities Nuna | Gold Bond Muscle |
| oil/commodity inflation | Oil Shock Titan | Exposure Futures Girl | EDT |
| credit/liquidity | Liquidity Leviathan | Gold Bond Muscle | Iron Securities Nuna |
| volatility | Volatility Hydra | EDT | Gold Bond Muscle |
| equity/sector crash | Algorithm Reaper | EDT | Exposure Futures Girl |
| war/geopolitical | War Dominion | Exposure Futures Girl | Gold Bond Muscle |
| fx/global | Currency Gate antagonist 또는 Algorithm Reaper | Iron Securities Nuna | EDT |

선정 점수:

```text
character_fit_score(char) =
  0.45 * domain_affinity(char, dominant_domain)
+ 0.20 * counter_affinity(char, villain)
+ 0.15 * recent_appearance_balance(char)
+ 0.10 * arc_relevance(char)
+ 0.10 * evidence_confidence
```

## 6. Victory/Loss Battle Formula 상세 설계

### 6.1 기본 원칙

1. 승패는 코드의 deterministic formula가 확정한다.
2. Claude/LLM은 `battle_result.outcome`을 변경하지 않는다.
3. 모든 가산/감산은 `formula_trace`에 남긴다.
4. 데이터 confidence가 낮으면 극단 결과를 완화한다.

### 6.2 Hero Power Formula v3 초안

```text
hero_power =
  base_power
+ domain_counter_bonus
+ defensive_alignment_bonus
+ breadth_support_bonus
+ sector_tailwind_bonus
+ arc_tension_bonus
+ form_bonus
+ evidence_confidence_bonus
- data_staleness_penalty
```

세부 항목:

| 항목 | 범위 | 설명 |
| --- | ---: | --- |
| `base_power` | 60~90 | 캐릭터 canon base |
| `domain_counter_bonus` | 0~18 | 히어로가 dominant villain/domain에 상극일 때 |
| `defensive_alignment_bonus` | 0~12 | 위험 회피장에서 방어형 히어로 보너스 |
| `breadth_support_bonus` | -6~+8 | 시장 내부 체력이 히어로를 지지하는 정도 |
| `sector_tailwind_bonus` | -6~+10 | 히어로 관련 섹터의 상대 강세/약세 |
| `arc_tension_bonus` | 0~6 | 기존 긴장도 보너스 유지 |
| `form_bonus` | 0~20 | EPISODE_TYPE_V3/form 시스템 유지 |
| `evidence_confidence_bonus` | 0~4 | 근거 데이터가 충분할 때 |
| `data_staleness_penalty` | 0~-8 | 핵심 데이터 결측/오래된 캐시 |

예시:

```text
EDT vs Volatility Hydra:
base 78
+ domain_counter_bonus 14   # volatility counter
+ breadth_support_bonus -2  # breadth weak
+ arc_tension_bonus 2
+ evidence_confidence_bonus 3
= hero_power 95
```

### 6.3 Villain Power Formula v3 초안

```text
villain_power =
  base_power
+ domain_pressure_bonus
+ shock_momentum_bonus
+ sector_domain_bonus
+ cross_asset_confirmation_bonus
+ news_event_catalyst_bonus
+ villain_signature_bonus
- information_deficit_penalty
- data_confidence_penalty
```

세부 항목:

| 항목 | 범위 | 설명 |
| --- | ---: | --- |
| `base_power` | 60~90 | 빌런 canon base |
| `domain_pressure_bonus` | 0~24 | dominant domain pressure 직접 반영 |
| `shock_momentum_bonus` | 0~16 | 하루 변화율/단기 급등락 |
| `sector_domain_bonus` | 0~12 | 관련 섹터 붕괴/급등 |
| `cross_asset_confirmation_bonus` | 0~10 | 여러 자산군이 같은 위험을 확인 |
| `news_event_catalyst_bonus` | 0~8 | 공식 이벤트/뉴스 촉매 |
| `villain_signature_bonus` | 0~18 | 기존 Phase 2.3 signature 유지 |
| `information_deficit_penalty` | 0~-10 | EMERGENCE 정보 부족 패널티 유지 |
| `data_confidence_penalty` | 0~-8 | 근거가 빈약하면 극단 결과 억제 |

예시:

```text
Debt Titan:
base 76
+ domain_pressure_bonus 18  # rates_pressure high
+ shock_momentum_bonus 6    # DGS10 rapid move
+ cross_asset_confirmation_bonus 5 # USD/KRW + equity pressure
+ news_event_catalyst_bonus 4 # FOMC/CPI hook
= villain_power 109
```

### 6.4 Balance → Outcome Threshold

기존 threshold와 호환하되, v3에서는 confidence gate를 먼저 적용한다.

```text
raw_balance = hero_power - villain_power
adjusted_balance = raw_balance + narrative_stability_adjustment
```

기본 threshold:

| adjusted_balance | outcome |
| ---: | --- |
| `>= +30` | `HERO_VICTORY` |
| `+10 ~ +29` | `HERO_TACTICAL_VICTORY` |
| `-5 ~ +9` | `DRAW` |
| `-10 ~ -6` | `VILLAIN_TEMP_VICTORY` |
| `-30 ~ -11` | `HERO_DEFEAT` |
| `<= -31` | `SYSTEM_COLLAPSE` |

Confidence gate:

```text
if data_confidence < 0.55 and outcome in {HERO_VICTORY, SYSTEM_COLLAPSE}:
    outcome = nearest_non_extreme(outcome)
```

- `HERO_VICTORY` → `HERO_TACTICAL_VICTORY`
- `SYSTEM_COLLAPSE` → `HERO_DEFEAT`

목적: 결측/캐시 데이터로 극단적 승패가 나오는 것을 방지한다.

### 6.5 Story Pressure → Panel Beat 연결

`story_pressure_score`는 이야기가 얼마나 전투적으로 전개될지를 정한다.

```text
story_pressure_score =
  0.40 * risk_score
+ 0.25 * max_domain_pressure
+ 0.15 * shock_score
+ 0.10 * arc_tension
+ 0.10 * news_calendar_score
```

패널 배치:

| score | 패널 톤 | 연출 |
| ---: | --- | --- |
| 0~34 | 관찰/정보 | dashboard, neutral guest, calm dialogue |
| 35~64 | 전술 충돌 | one villain pressure, limited battle |
| 65~84 | 대형 전투 | multi-evidence conflict, alliance 가능 |
| 85~100 | 위기/클리프행어 | system siren, ominous ending |

`story_planner` 확장안:

- Panel 1: dominant domain hook
- Panel 2: top 2 evidence reveal
- Panel 3: selected villain motivation
- Panel 4: hero counter thesis
- Panel 5: sector/breadth twist
- Panel 6: fixed outcome resolution
- Panel 7: next economic event hook
- Panel 8: disclaimer

## 7. Pipeline 연결 설계

### 7.1 신규 모듈 흐름

```text
STEP 2
  sector_fetcher.fetch_all()
  economic_calendar_fetcher.fetch_all()
  news_fetcher.fetch_all()
  breadth_fetcher.fetch_all()
  rates_fetcher.fetch_all()
  credit_fetcher.fetch_all()
  fx_fetcher.fetch_all()
  commodity_fetcher.fetch_all()
    ↓
  snapshot_writer.upsert(... extended_data)
    ↓
STEP 3
  signal_pack_builder.build(curr_row, prev_row)
  risk_score_engine.compute(signal_pack)
  event_classifier_v3.classify(signal_pack, arc_context)
  story_context_builder.build_narrative_context_pack(... news/events/sector)
  battle_calc_v3.battle(... signal_pack, risk_trace)
  analysis_writer.upsert(... formula_trace, risk_drivers, sector_rank)
```

### 7.2 권장 파일 추가/변경

| 파일 | 작업 |
| --- | --- |
| `engine/data/sector_fetcher.py` | P0 섹터 ETF 수집 |
| `engine/data/economic_calendar_fetcher.py` | P0 이벤트 캘린더 수집 |
| `engine/data/news_fetcher.py` | P0 안전 뉴스 요약 수집/캐시 |
| `engine/analysis/signal_pack_builder.py` | scalar + JSONB snapshot을 계산식 입력으로 정규화 |
| `engine/analysis/risk_score_engine.py` | composite risk/domain pressure 계산 |
| `engine/analysis/analysis_writer.py` | `risk_drivers`, `sector_rank`, `watch_areas`, `caution_areas`, `formula_trace` 저장 |
| `engine/analysis/story_context_builder.py` | 운영 경로에서 news/events/sector 반영 강화 |
| `engine/narrative/battle_calc.py` | v3 formula를 feature flag로 추가 |
| `scripts/run_market.py` | STEP 2/3 신규 데이터 전달 연결 |
| `tests/test_*` | fetcher fallback, score formula, outcome gate 테스트 |

### 7.3 Feature Flag

| Flag | 기본값 | 의미 |
| --- | --- | --- |
| `MARKET_DATA_EXTENDED_ENABLED` | `false` | 신규 fetcher 실행 |
| `SIGNAL_PACK_V1_ENABLED` | `false` | JSONB 신호 정규화 사용 |
| `RISK_SCORE_V3_ENABLED` | `false` | composite risk score 사용 |
| `BATTLE_FORMULA_V3_ENABLED` | `false` | 신규 승패 계산식 사용 |
| `STORY_CONTEXT_EXTENDED_ENABLED` | `false` | news/events/sector 운영 주입 |

## 8. 단계별 착수 계획

### Phase A: P0 데이터 수집 연결

1. `sector_fetcher` 구현 및 단위 테스트
2. `daily_snapshots.sector_heatmap` 마이그레이션
3. `snapshot_writer` 예상 필드/품질 로그 확장
4. `run_market.step_data()`에 feature flag로 연결
5. `story_context_builder`에 운영 `sector_heatmap` 주입

완료 조건:

- 섹터 데이터 결측 시 기존 파이프라인 중단 없음
- `narrative_context_pack.scene_symbols`에 섹터 board가 들어감
- 테스트 fixture 없이 운영 ctx에서 sector signal 확인 가능

### Phase B: 뉴스/경제일정 연결

1. `economic_calendar_fetcher` 구현
2. `news_fetcher` 또는 수동/캐시 기반 news ingestion 구현
3. `run_market.step_analysis()`에서 `news_items`, `economic_events` 전달
4. Story grounding gate가 news evidence를 허용하는지 테스트

완료 조건:

- NEXT_HOOK에 CPI/FOMC/NFP 등 이벤트가 자동 반영
- `top_evidence`에 검증 뉴스 1건이 들어갈 수 있음

### Phase C: Risk Score v3

1. `signal_pack_builder` 구현
2. `risk_score_engine` 구현
3. `scenario_selector.compute_risk_level_from_delta()`와 병행 운영
4. `formula_trace.risk_score` 저장

완료 조건:

- LOW/MEDIUM/HIGH가 VIX/WTI뿐 아니라 breadth/credit/fx를 반영
- 기존 v2 결과와 side-by-side 로그 비교 가능

### Phase D: Battle Formula v3

1. `calc_hero_power_v3`, `calc_villain_power_v3` 추가
2. `confidence_gate` 추가
3. `formula_trace` 저장
4. legacy/v3 outcome 비교 테스트

완료 조건:

- 동일 입력이면 항상 동일 outcome
- 데이터 confidence가 낮을 때 극단 outcome 완화
- `battle_result`와 `story_beat_plan`이 동일 outcome을 유지

## 9. 테스트 전략

| 테스트 | 목적 |
| --- | --- |
| `test_sector_fetcher_fallback` | yfinance 실패 시 None/Unknown이 아니라 부분 결과 허용 |
| `test_signal_pack_builder_normalizes_jsonb` | 섹터/news/events JSONB를 MarketSignal로 정규화 |
| `test_risk_score_uses_multiple_domains` | VIX 낮아도 credit/breadth 악화 시 MEDIUM/HIGH 가능 |
| `test_battle_formula_v3_confidence_gate` | 결측 데이터에서 SYSTEM_COLLAPSE 완화 |
| `test_story_context_extended_includes_sector_news_events` | 운영 ctx가 섹터/뉴스/일정을 prompt까지 전달 |
| `test_no_investment_advice_labels` | watch/caution 표현이 매수/매도 지시로 변질되지 않음 |

## 10. 우선 구현 범위 제안

가장 먼저 착수할 구현 단위는 아래 3개가 적절하다.

1. **`sector_fetcher` + `sector_heatmap` JSONB + story context 주입**
   - 코믹스 장면 다양성 개선 효과가 가장 빠르다.
2. **`risk_score_engine` side-by-side 계산**
   - 기존 승패를 깨지 않고 판단식 개선 데이터를 쌓을 수 있다.
3. **`formula_trace` 저장**
   - 이후 승패가 왜 나왔는지 디버깅할 수 있어 운영 신뢰도가 올라간다.

이 3개를 먼저 넣은 뒤, 뉴스/경제일정과 battle v3를 순차 적용하는 것이 안정적이다.
## 11. 2026-06-03 파일럿 착수 완료 범위

이번 착수에서는 전체 설계 중 운영 리스크가 낮고 효과 검증이 빠른 P0 일부를 feature flag 기반으로 구현했다.

| 구현 항목 | 파일 | 상태 | 비고 |
| --- | --- | --- | --- |
| 섹터 히트맵 수집 | `engine/data/sector_fetcher.py` | 완료 | `MARKET_DATA_EXTENDED_ENABLED=true`일 때 STEP 2에서 실행 |
| MarketSignal 정규화 | `engine/analysis/signal_pack_builder.py` | 완료 | `SIGNAL_PACK_V1_ENABLED=true`일 때 STEP 3에서 생성 |
| Composite Risk Score | `engine/analysis/risk_score_engine.py` | 완료 | `RISK_SCORE_V3_ENABLED=true`일 때 side-by-side 계산 및 risk_level 사용 |
| Story context 운영 주입 | `scripts/run_market.py` | 완료 | `STORY_CONTEXT_EXTENDED_ENABLED=true`일 때 `sector_heatmap`, `news_items`, `event_calendar` 전달 |
| 분석 관측성 저장 | `engine/analysis/analysis_writer.py` | 완료 | `formula_trace`, `risk_drivers`, `sector_rank`, `watch_areas`, `caution_areas` 선택 저장 |
| DB 확장 | `migrations/2026_06_03_market_data_extended_pilot.sql` | 완료 | JSONB-first + optional normalized table |

아직 미착수인 뉴스/경제일정 fetcher, breadth/rates/credit/fx/commodity fetcher, Battle Formula v3 power 계산은 다음 PR에서 Phase B~D 순서로 진행한다.

