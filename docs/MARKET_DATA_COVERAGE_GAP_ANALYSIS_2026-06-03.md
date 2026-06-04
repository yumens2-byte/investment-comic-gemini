# 시장데이터 기반 코믹스 생성용 분석데이터/판단데이터 커버리지 갭 분석

작성일: 2026-06-03  
대상: `investment-comic-gemini`의 STEP 2 데이터 수집, STEP 3 분석/판단, Narrative Context Pilot

## 1. 현재 파이프라인이 실제로 보는 데이터

현재 STEP 2는 5개 fetcher를 통해 `icg.daily_snapshots`에 아래 필드를 저장한다.

| 영역 | 현재 필드 | 수집 모듈 | 코믹스/판단에서 쓰이는 방식 |
| --- | --- | --- | --- |
| 금리/거시 | `fed_funds_rate`, `us10y`, `yield_curve` | `fred_fetcher` | Debt Titan, 금리 긴장, 수익률곡선 단서 |
| 변동성 | `vix` | `fred_fetcher` | SHOCK 판정, Volatility Hydra, 방어 모드 |
| 원자재 | `oil_wti` | `fred_fetcher` | Oil Shock Titan, 유가 쇼크 |
| 달러/신용 | `dollar_index`, `hy_spread` | `fred_fetcher` | 달러 압력, Liquidity Leviathan/신용 스트레스 |
| 주식 지수 | `spy_change`, `nasdaq_change` | `market_fetcher` | Algorithm Reaper, 리스크 레벨 일부 |
| 환율 | `usdkrw` | `market_fetcher` | FX 장면 심볼/원화 긴장 |
| 암호화폐 | `btc_usd`, `crypto_basis_spread/state`, `btc_social_sentiment/state` | `market_fetcher`, `crypto_fetcher`, `sentiment_fetcher` | BTC/크립토 레버리지·군중 심리 |
| 군중 심리 | `fear_greed`, `fear_greed_label` | `feargreed_fetcher` | crowd emotion shift |

## 2. 핵심 결론

현재 데이터는 **매크로·지수·BTC 중심의 “시장 전체 분위기” 판단에는 충분한 최소 세트**를 갖추고 있다. 반면 사용자가 말한 “시장데이터 기반 코믹스”를 더 풍부하게 만들기에는 **섹터/산업/자산군별 서사 재료와 실제 판단 데이터가 부족**하다.

특히 다음 4개가 가장 큰 갭이다.

1. **섹터/산업 데이터가 아직 실수집되지 않는다.** Narrative Context Builder는 `sector_heatmap` 입력을 받을 수 있지만, STEP 2/3에서 실제로 넘기지 않는다.
2. **뉴스·경제일정 입력도 구조만 있고 실수집/주입이 없다.** `news_items`, `economic_events` 인자는 열려 있지만 `run_market.step_analysis()` 호출에서는 비어 있다.
3. **`daily_analysis`의 ETF/매수·축소 판단 필드는 비어 있는 placeholder다.** `etf_rank`, `etf_allocation`, `buy_watch`, `reduce_list`가 모두 빈 값으로 저장되어 실제 투자 판단 소재가 없다.
4. **일부 판단 로직은 데이터 정의와 불일치한다.** `SPY` 급락 판정은 “당일 SPY 수익률”이 아니라 “SPY 수익률의 전일 대비 변화율”을 보고 있으며, WTI도 주석상 3일 변화율이라고 되어 있지만 실제로는 latest two snapshots 기반 변화율이다.

## 3. 부족한 섹터/영역 상세 진단

### 3.1 주식 섹터/산업: 가장 큰 공백

현재 수집 대상은 SPY와 NASDAQ뿐이다. 따라서 “시장은 보합인데 에너지·반도체·금융·방산만 움직이는 날”을 캐릭터/장면/빌런으로 분리하기 어렵다.

추가 우선순위:

| 우선순위 | 추가 데이터 | 목적 | 추천 티커/소스 예시 |
| --- | --- | --- | --- |
| P0 | S&P 500 11개 섹터 ETF 등락률 | 섹터 히트맵, 섹터별 캐릭터 등장 | `XLK`, `XLF`, `XLE`, `XLV`, `XLI`, `XLY`, `XLP`, `XLU`, `XLB`, `XLRE`, `XLC` |
| P0 | 반도체/AI 프록시 | NASDAQ 내부 동인 구분 | `SMH`, `SOXX`, `NVDA`, `AVGO` 또는 ETF만 |
| P1 | 방산/전쟁 리스크 프록시 | War Dominion 소재 강화 | `ITA`, `XAR` |
| P1 | 은행/지역은행 | 신용·유동성 스트레스 구체화 | `KBE`, `KRE` |
| P1 | 바이오/헬스케어 | 방어주/정책 이벤트 분리 | `XLV`, `IBB` |

현재 `story_context_builder`는 이미 섹터 심볼을 장면 소재로 변환하는 함수가 있으므로, 수집/주입만 연결하면 효과가 빠르다.

### 3.2 시장 폭/내부 체력: “지수는 올랐지만 속은 약한 날”을 못 잡음

현재 SPY/NASDAQ만 보면 대형주 쏠림, breadth 악화, 위험 회피성 상승을 구분하기 어렵다.

추가 후보:

- 상승/하락 종목 수 또는 Advance/Decline Line
- 52주 신고가/신저가
- Equal-weight vs cap-weight 차이: `RSP` vs `SPY`
- Russell 2000: `IWM`
- 고베타/저변동성: `SPHB`, `SPLV`

서사 효과:

- “대장주 몇 명만 성벽을 지탱하는 장면”
- “군중은 환호하지만 뒷골목 섹터는 무너지는 장면”
- `NO_BATTLE`과 `TACTICAL`의 구분 개선

### 3.3 스타일/팩터: 성장주·가치주·방어주 로테이션 부족

현재 NASDAQ과 SPY만으로는 성장/가치/퀄리티/모멘텀/방어 로테이션을 구분하기 어렵다.

추가 후보:

- Growth/Value: `IWF`, `IWD`
- Momentum/Quality/Low Volatility: `MTUM`, `QUAL`, `USMV`
- Equal-weight tech or mega-cap concentration 프록시

서사 효과:

- “AI 탑이 빛나지만 가치주 광산은 조용한 날” 같은 장면 분화
- 히어로별 등장 근거 다변화

### 3.4 채권/금리: 10Y와 10Y-2Y만으로는 부족

현재 금리 판단은 10년물, Fed Funds, 10Y-2Y에 집중된다. 단기금리·실질금리·장기물 변동을 나누지 못한다.

추가 후보:

- 2Y 금리, 30Y 금리
- 10Y 실질금리/TIPS: `DFII10` 또는 ETF `TIP`
- MOVE Index 또는 채권 변동성 프록시
- FedWatch 확률 또는 SOFR futures는 P2

서사 효과:

- Debt Titan이 “단기 정책금리형”인지 “장기 재정불안형”인지 구분
- Gold/Bond 방어 캐릭터 판단 정확도 개선

### 3.5 신용/유동성: HY OAS 하나만으로는 늦게 반응할 수 있음

현재 `hy_spread`만으로 Liquidity Leviathan을 판단한다. HY OAS는 중요하지만, 시장 선행 신호로는 IG 스프레드·은행·크레딧 ETF 가격이 더 빠르게 움직일 때가 있다.

추가 후보:

- IG OAS, HY ETF: `LQD`, `HYG`, `JNK`
- 은행/지역은행 ETF: `KBE`, `KRE`
- TED spread/SOFR stress 성격 지표

서사 효과:

- “신용 다리 균열” 장면을 조기에 포착
- SYSTEM_COLLAPSE 또는 HERO_DEFEAT 판정 근거 강화

### 3.6 FX/글로벌: USDKRW만으로는 달러 강세의 원인 분해가 어렵다

현재 FX는 달러 인덱스와 USDKRW만 있다. 엔화·위안·유로·신흥국 스트레스는 반영되지 않는다.

추가 후보:

- USDJPY, EURUSD, USDCNH
- EM FX ETF 또는 원자재 통화 프록시
- 한국시장 연동을 강화하려면 KOSPI/KOSDAQ, EWY

서사 효과:

- “환율 게이트”가 원화 고유 이슈인지 글로벌 달러 강세인지 구분
- 한국 독자 대상 맥락 강화

### 3.7 원자재: WTI만으로는 인플레이션/전쟁/성장 둔화를 구분하기 어렵다

현재 원자재는 WTI뿐이다.

추가 후보:

- Gold: `GC=F` 또는 `GLD`
- Copper: `HG=F` 또는 `CPER`
- Natural Gas: `NG=F`
- Broad commodities: `DBC`, `PDBC`

서사 효과:

- Gold Bond/방어 모드와 전쟁 리스크 분리
- 구리 약세 + 유가 강세처럼 “스태그플레이션형” 장면 생성

### 3.8 암호화폐: BTC 중심이라 알트/온체인/리스크 선호 구분이 제한됨

현재 BTC 가격, BTC basis, BTC social sentiment만 있다.

추가 후보:

- ETH 가격/ETHBTC
- Total crypto market cap 또는 `SOL`, `COIN`, `MSTR` 등 프록시
- Funding rate/open interest/liquidation 데이터
- Stablecoin dominance, DeFi TVL은 P2

서사 효과:

- BTC 단독 이슈와 전체 위험선호 회복을 구분
- Liquidity Leviathan/crypto leverage stress의 설득력 강화

### 3.9 옵션/변동성 구조: VIX 레벨만으로는 공포의 성격 구분이 부족

현재 VIX만 있다.

추가 후보:

- VIX term structure: `VIX3M`, `VIX9D`, VIX futures contango/backwardation
- Put/Call Ratio
- Skew Index

서사 효과:

- 단기 이벤트 공포와 구조적 공포 분리
- SHOCK/TACTICAL/AFTERMATH 분기 개선

### 3.10 뉴스/경제일정/이벤트: 구조는 있으나 실제 주입이 없음

`build_narrative_context_pack()`은 news, economic events, sector heatmap 입력을 받을 수 있다. 하지만 `run_market.step_analysis()`에서는 현재 `delta`, `battle_result`, `event_type`, `scenario_type`, `ending_tone`, `arc_context`만 넘긴다. 즉, 뉴스/일정/섹터 데이터는 테스트 fixture에서는 동작하지만 운영 경로에서는 비어 있다.

추가 우선순위:

- P0: 주요 경제일정(CPI, PCE, FOMC, 고용, ISM, GDP, 소매판매)
- P0: 공식/검증 뉴스 요약 1~3건
- P1: 기업실적 캘린더와 주요 메가캡 earnings
- P1: 지정학 이벤트 태그

## 4. 판단데이터/분석데이터의 구조적 부족

### 4.1 `daily_analysis` 투자 판단 필드가 비어 있음

현재 `analysis_writer.upsert()`는 `etf_rank`, `etf_allocation`, `buy_watch`, `reduce_list`를 빈 값으로 저장한다. 따라서 “판단데이터” 관점에서는 regime/risk/signal/battle score만 존재하고, 실제 섹터·ETF·관심/축소 목록은 생성되지 않는다.

추천:

- `sector_rank`: 섹터 ETF 수익률·모멘텀·리스크 점수
- `asset_rank`: 주식/채권/금/달러/BTC 상대강도
- `watchlist_reason`: 숫자 기반 사유
- `reduce_reason`: 리스크 기반 사유
- 단, 코믹스 서비스라면 “투자 조언” 표현을 피하고 “관찰 후보/주의 영역”으로 명명

### 4.2 event classifier의 일부 조건이 데이터 의미와 맞지 않음

- `market_fetcher`는 `spy_change`에 SPY 가격이 아니라 최근 close 기준 일간 변화율을 저장한다.
- `delta_engine`은 다시 `spy_change`의 전일 대비 변화율을 계산해 `delta["SPY"]["pct"]`에 넣는다.
- `event_classifier`는 `SPY 일간 -3% 이하`라는 주석과 달리 `delta["SPY"]["pct"]`를 사용한다.

따라서 지수 급락 이벤트가 의도보다 과소/과대 판정될 수 있다. `SPY`/`NASDAQ`은 `curr`를 당일 등락률로 보고, 이벤트 판정은 `curr <= -3.0`처럼 해야 의미가 맞다.

### 4.3 WTI “3일 변화율” 주석과 실제 계산이 불일치

`event_classifier.get_market_context_for_battle()`은 `wti_pct_3d`를 `delta["WTI"]["pct"]`에서 가져온다. 그러나 `delta_engine`은 최신 2개 snapshot만 비교한다. 현재로서는 3일 변화율이 아니라 직전 snapshot 대비 변화율이다.

추천:

- 3일 전 snapshot을 별도 조회해서 `WTI_3D_PCT`를 만들거나,
- 주석과 변수명을 `wti_pct`로 낮춰 실제 의미에 맞춘다.

### 4.4 risk_level이 VIX와 WTI 중심이라 시장 판단 폭이 좁음

`compute_risk_level_from_delta()`는 VIX와 WTI 레벨만 사용한다. HY spread, DGS10, SPY/NASDAQ 급락, USDKRW, BTC stress가 risk_level에 들어가지 않는다.

추천 점수식:

```text
risk_score =
  VIX level/percentile
+ SPY/NASDAQ drawdown
+ HY spread widening
+ DGS10 move and real yield
+ USDKRW/DXY stress
+ sector breadth deterioration
+ crypto leverage stress
```

점수에 따라 LOW/MEDIUM/HIGH를 산출하면 ALLIANCE/NO_BATTLE/ONE_VS_ONE 분기가 더 안정적이다.

## 5. 실행 우선순위 제안

### P0: 즉시 효과가 큰 보강

1. **Sector Heatmap Fetcher 추가**
   - yfinance로 11개 섹터 ETF 일간 등락률 수집
   - `daily_snapshots.sector_heatmap JSONB` 또는 별도 `daily_sector_snapshots` 저장
   - `build_narrative_context_pack(..., sector_heatmap=...)`에 주입

2. **경제일정 Fetcher 추가**
   - CPI/PCE/FOMC/NFP/ISM 등 1주일 캘린더
   - `foreshadow`에 자동 반영

3. **SPY/NASDAQ 급락 판정 수정**
   - `delta["SPY"]["curr"]`를 당일 등락률로 사용
   - `delta["SPY"]["pct"]`는 “등락률의 변화율”로 별도 설명

4. **`daily_analysis` 판단 placeholder 채우기**
   - 최소: `sector_rank`, `risk_drivers`, `watch_areas`, `reduce_areas`
   - 투자 조언이 아니라 코믹스/관찰용 레이블로 저장

### P1: 코믹스 서사 밀도를 높이는 보강

1. Breadth/market internals: `RSP/SPY`, `IWM`, advance/decline
2. 금리 세분화: 2Y, 30Y, real yield, MOVE
3. 신용 세분화: IG OAS, LQD/HYG/JNK, 은행 ETF
4. FX 세분화: USDJPY, EURUSD, USDCNH, EWY/KOSPI
5. 원자재 세분화: Gold, Copper, NatGas

### P2: 고급 판단/연출

1. 옵션 구조: VIX9D/VIX3M, put/call, skew
2. Crypto 온체인/파생: funding, OI, liquidation
3. earnings/calendar/news graph
4. 경제 서프라이즈/컨센서스 대비 실제치

## 6. 추천 데이터 스키마 초안

### 6.1 `daily_snapshots` JSONB 확장안

```json
{
  "sector_heatmap": {
    "as_of": "2026-06-03",
    "sectors": [
      {"symbol": "XLK", "name": "Technology", "change_pct": -1.2, "rank": 8},
      {"symbol": "XLE", "name": "Energy", "change_pct": 1.6, "rank": 1}
    ]
  },
  "market_breadth": {
    "rsp_spy_spread_pct": -0.4,
    "iwm_change_pct": -1.1,
    "breadth_state": "narrow_leadership"
  },
  "event_calendar": [
    {"name": "CPI", "date": "2026-06-10", "importance": 5, "story_use": "inflation_gate"}
  ]
}
```

### 6.2 `daily_analysis` 판단 확장안

```json
{
  "risk_drivers": [
    {"driver": "VIX", "score": 18, "reason": "VIX above 25"},
    {"driver": "HY_SPREAD", "score": 12, "reason": "credit spread widening"}
  ],
  "sector_rank": [
    {"symbol": "XLE", "rank": 1, "state": "leader"},
    {"symbol": "XLK", "rank": 10, "state": "laggard"}
  ],
  "watch_areas": ["Energy", "Gold", "Short-duration bonds"],
  "caution_areas": ["High beta tech", "Regional banks"]
}
```

## 7. 후속 상세 설계

부족 데이터 수집, Story Decision Formula, Victory/Loss Battle Formula의 구체 설계는 `docs/MARKET_DATA_COLLECTION_AND_BATTLE_FORMULA_DESIGN_2026-06-03.md`에 분리했다. 해당 문서는 P0/P1/P2 fetcher, `MarketSignal` 정규화 모델, `risk_score`, `domain_pressure`, `hero_power`/`villain_power`, `formula_trace` 저장 전략까지 구현 착수 단위로 정의한다.

## 8. 최종 판단

현재 시스템은 **거시 이벤트 중심 코믹스**에는 작동하지만, **섹터별 시장 움직임을 캐릭터/장면/판단으로 분해하는 단계에는 아직 부족**하다. 가장 먼저 보강할 영역은 다음 순서가 적절하다.

1. **섹터 ETF 11종 + 섹터 히트맵**
2. **경제일정/뉴스 요약의 실제 주입**
3. **SPY/NASDAQ·WTI 판정 로직의 데이터 의미 정렬**
4. **ETF/섹터 rank 및 watch/caution 판단 필드 채우기**
5. **breadth·신용·금리·FX·원자재 세분화**

이 순서로 진행하면 코믹스의 “오늘 왜 이 캐릭터가 등장했는지”가 더 명확해지고, `market_ref`도 단순 수치 나열에서 섹터·이벤트·자산군 간 갈등 구조로 발전할 수 있다.
