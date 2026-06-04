# 시장 데이터 재시도·Critical Gate 상세 설계 및 파일럿 테스트 계획 (2026-06-04)

## 1. 목표

미국장 기반 히어로 유니버스 자동 발행에서 시장 데이터가 비어 있거나 불완전할 때 다음 원칙을 보장한다.

1. **값이 안 들어오는 핵심 API/티커는 3회 시도한다.**
2. **3회 시도 후에도 critical 데이터가 없으면 신규 에피소드 생성/발행 흐름을 중단한다.**
3. **optional 데이터 누락은 발행을 막지 않되 품질 로그와 문서에 남긴다.**
4. **잘못된 critical-null snapshot이 최신 데이터로 저장되어 후속 stage를 오염시키지 않도록 gate를 upsert 전에 둔다.**

## 2. 이해관계자 3자 결정 기록

| 이해관계자 | 관점 | 쟁점 | 결정 |
|---|---|---|---|
| 운영/발행 책임자 | 자동 발행 안정성 | 데이터 일부가 비어도 발행해야 하는가 | critical 누락은 브랜드/신뢰 리스크가 더 커서 기본 중단 |
| 데이터 품질 책임자 | 지표 무결성 | null snapshot을 DB에 저장해도 되는가 | critical null은 후속 `latest snapshot` 오염 위험이 있어 upsert 전 차단 |
| 콘텐츠/서사 책임자 | 스토리 연속성 | sentiment/sector 같은 보조 데이터 누락 시 중단해야 하는가 | optional 누락은 스토리 풍부도만 낮추므로 발행 허용, 로그로 관측 |

## 3. Critical / Optional 데이터 계약

### 3.1 Critical 필드

자동 발행 판단과 이벤트 분류에 직접 영향을 주는 값이다. 하나라도 누락되면 `CriticalDataMissingError`로 STEP 2를 실패시킨다.

- `us10y`
- `vix`
- `oil_wti`
- `spy_change`
- `nasdaq_change`
- `btc_usd`
- `usdkrw`
- `fear_greed`

### 3.2 Optional 필드

스토리 풍부화 또는 보조 해석용이다. 누락 시 warning/quality summary로 남기고 발행 흐름은 유지한다.

- `crypto_basis_spread`, `crypto_basis_state`
- `btc_social_sentiment`, `btc_sentiment_state`
- sector heatmap 및 확장 JSONB 필드

## 4. 설계 변경

### 4.1 yfinance 3회 재시도

- `_download_ticker()`에 `@api_retry(max_attempts=3)`를 적용한다.
- HTTP/네트워크 예외뿐 아니라 빈 DataFrame, 2행 미만 응답도 retryable error로 취급한다.
- 전체 병렬 대기 시간은 45초로 조정해 3회 시도(12초 timeout + backoff)를 중간에 끊지 않도록 한다.
- 최종 실패 시 `_fetch_ticker_safe()`가 기존 계약대로 `None` 필드를 반환한다.

### 4.2 Critical Gate

- `build_snapshot_payload()`로 fetcher 산출물을 canonical payload로 합친다.
- `enforce_critical_quality()`가 `summarize_quality()` 결과의 `critical_missing`을 검사한다.
- critical 누락이 있으면 `CriticalDataMissingError`를 발생시킨다.
- `scripts.run_market.step_data()`는 gate 통과 후에만 `daily_snapshots`에 upsert한다.
- `CRITICAL_DATA_GATE_ENABLED=false`는 emergency override로만 사용한다.

## 5. 실행 순서

```text
STEP 2 Data
  ├─ FRED / yfinance / FearGreed / Crypto / Sentiment 수집
  ├─ build_snapshot_payload()
  ├─ CriticalDataGate (default ON)
  │   ├─ pass: quality log 기록 후 upsert
  │   └─ fail: STEP 2 실패 → STEP 3~8 신규 생성 흐름 중단
  └─ daily_snapshots upsert
```

## 6. 파일럿 테스트 설계

### 6.1 단위 파일럿

- optional 누락만 있는 payload는 통과해야 한다.
- critical 누락 payload는 `CriticalDataMissingError`를 발생시켜야 한다.
- 각 critical field가 단독으로 비었을 때 모두 차단되는지 parametrize로 검증한다.

### 6.2 전주(7일) 시뮬레이션 테스트

- 7개 synthetic daily payload를 만든다.
- 3일차에는 optional sentiment만 누락시켜 통과를 기대한다.
- 6일차에는 `vix`를 누락시켜 해당 일자만 차단을 기대한다.
- 기대 결과: 1,2,3,4,5,7일차 통과 / 6일차 차단.

## 7. 현재 한계 및 권고

1. 이미 `assembled` 상태로 남아 있는 과거 에피소드는 별도 `publish_sns.yml` 스케줄에서 발행될 수 있다. 신규 생성 gate와 별개로 publish 단계의 날짜별 data-quality lock을 추가하는 것이 다음 최적화다.
2. FRED API key 누락은 재시도 대상이 아니라 설정 오류이므로 즉시 실패가 맞다.
3. `CRITICAL_DATA_GATE_ENABLED=false` 사용 시 run log에 override를 남기지만, 운영 승인 플로우는 아직 없다. 장기적으로는 GitHub environment approval 또는 Supabase audit row가 필요하다.
