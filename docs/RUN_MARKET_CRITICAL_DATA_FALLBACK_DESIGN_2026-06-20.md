# run_market Critical 데이터 Fallback 상세 설계 (2026-06-20)

## 1. 결론: 최선 권장 방향

현재 `run_market`의 간헐 실패를 줄이는 최선 방향은 **CriticalDataGate는 유지하되, gate 직전에 검증 가능한 보조 데이터 계층을 추가하는 fail-safe 설계**다.

- **기본 원칙:** 핵심 데이터가 비어 있는 snapshot을 그대로 저장하지 않는다.
- **개선 원칙:** 일시적 외부 API 장애로 핵심 데이터가 비었을 때, 검증 가능한 대체 소스 또는 최근 정상 snapshot을 사용해 payload를 보정한다.
- **투명성 원칙:** 보정된 값은 반드시 `data_quality`/`fallback_trace`에 남겨 발행물·운영 로그·사후 감사에서 확인 가능하게 한다.
- **최종 차단 원칙:** 보조 계층까지 실패하면 기존처럼 `CriticalDataMissingError`로 중단한다.

즉, 기존 gate를 제거하거나 `CRITICAL_DATA_GATE_ENABLED=false`로 운영하는 방식은 권장하지 않는다. 대신 **API 1차 수집 → 소스별 fallback → stale snapshot fallback → CriticalDataGate** 순으로 단계를 세분화한다.

## 2. 현재 문제 요약

### 2.1 Critical 필드 단일 장애점

현재 critical 필드는 다음 8개다.

| 필드 | 주 소스 | 현재 fallback | 실패 시 영향 |
|---|---|---|---|
| `us10y` | FRED `DGS10` | 없음 | STEP 2 중단 |
| `vix` | FRED `VIXCLS` | 없음 | STEP 2 중단 |
| `oil_wti` | FRED `DCOILWTICO` | 없음 | STEP 2 중단 |
| `spy_change` | yfinance `SPY` | 없음 | STEP 2 중단 |
| `nasdaq_change` | yfinance `^IXIC` | 없음 | STEP 2 중단 |
| `btc_usd` | yfinance `BTC-USD` | Coinbase spot | Coinbase까지 실패 시 중단 |
| `usdkrw` | yfinance `USDKRW=X` | 없음 | STEP 2 중단 |
| `fear_greed` | alternative.me | 없음 | STEP 2 중단 |

### 2.2 보조 데이터와 필수 데이터의 설계 불균형

`sentiment_fetcher`는 TTL cache와 stale cache fallback을 가진 반면, critical인 `fear_greed`에는 cache fallback이 없다. BTC는 Coinbase fallback이 있지만 SPY/NASDAQ/USDKRW에는 대체 계층이 없다. 이 때문에 운영 실패 빈도는 실제 시장 데이터 품질보다 외부 API 일시 장애에 더 크게 좌우된다.

## 3. 목표 / 비목표

### 3.1 목표

1. `run_market --stage all`의 간헐 실패율을 낮춘다.
2. critical-null snapshot 저장은 계속 방지한다.
3. fallback 사용 여부와 freshness를 구조화해 DB와 log에 남긴다.
4. 과거 날짜 재실행 시에도 가능한 한 episode_date 기준으로 데이터를 복구한다.
5. fallback이 사용된 경우 narrative가 “최신 실시간 데이터”처럼 과장하지 않도록 품질 metadata를 전달한다.

### 3.2 비목표

1. 검증 불가능한 임의 값 생성은 하지 않는다.
2. 모든 외부 API 장애를 무조건 발행으로 전환하지 않는다.
3. `CRITICAL_DATA_GATE_ENABLED=false`를 상시 운영 모드로 만들지 않는다.
4. 유료 데이터 벤더 종속 설계는 1차 범위에서 제외한다.

## 4. 제안 아키텍처

```text
STEP 2 Data
  ├─ 1차 수집
  │   ├─ FRED
  │   ├─ yfinance
  │   ├─ alternative.me Fear & Greed
  │   ├─ Crypto.com
  │   └─ LunarCrush
  ├─ canonical payload 병합
  ├─ CriticalFallbackResolver 신규
  │   ├─ source fallback
  │   │   ├─ BTC: Coinbase 유지
  │   │   ├─ Fear & Greed: api_cache fresh/stale
  │   │   ├─ SPY/NASDAQ/USDKRW: recent snapshot 또는 보조 provider
  │   │   └─ FRED series: target_date lookback + recent snapshot
  │   ├─ freshness / age 검증
  │   ├─ fallback_trace 생성
  │   └─ 보정 payload 반환
  ├─ CriticalDataGate
  │   ├─ pass: upsert + quality metadata 저장
  │   └─ fail: CriticalDataMissingError
  └─ daily_snapshots upsert
```

## 5. 상세 설계

### 5.1 신규 모듈: `engine/data/critical_fallback_resolver.py`

#### 책임

- snapshot payload에서 critical 누락 필드를 찾는다.
- 필드별 fallback policy를 적용한다.
- 값을 보정한 payload와 `data_quality` metadata를 반환한다.
- fallback 실패 시 기존 gate가 실패하도록 값을 비워 둔다.

#### 공개 함수

```python
def resolve_critical_fallbacks(
    *,
    snapshot_date: str,
    payload: dict,
    source_status: dict | None = None,
) -> tuple[dict, dict]:
    """Return resolved payload and structured data_quality metadata."""
```

#### 반환 metadata 예시

```json
{
  "critical_fallback_version": "2026-06-20.v1",
  "status": "resolved_with_fallback",
  "missing_before": ["fear_greed", "usdkrw"],
  "missing_after": [],
  "fallbacks": [
    {
      "field": "fear_greed",
      "strategy": "api_cache_stale",
      "source": "alternative.me",
      "as_of": "2026-06-19",
      "age_days": 1,
      "value_type": "exact_cached",
      "confidence": 0.82
    },
    {
      "field": "usdkrw",
      "strategy": "previous_snapshot",
      "source": "daily_snapshots",
      "as_of": "2026-06-19",
      "age_days": 1,
      "value_type": "stale_close",
      "confidence": 0.70
    }
  ],
  "blocked_fields": []
}
```

### 5.2 Fallback policy matrix

| 필드 | 1순위 fallback | 2순위 fallback | 최대 허용 stale | 비고 |
|---|---|---|---:|---|
| `btc_usd` | Coinbase spot | 최근 정상 snapshot | 2일 | Coinbase 기존 유지 |
| `fear_greed` | fresh cache | stale cache 또는 최근 정상 snapshot | 3일 | 주말/휴일 영향 작음 |
| `usdkrw` | 최근 정상 snapshot | 보조 FX provider 검토 | 2영업일 | 환율은 stale 표시 필수 |
| `spy_change` | 최근 정상 snapshot의 `spy_change` | SPY close 기반 재계산 | 1영업일 | 시장 방향성에 민감 |
| `nasdaq_change` | 최근 정상 snapshot의 `nasdaq_change` | NASDAQ close 기반 재계산 | 1영업일 | 시장 방향성에 민감 |
| `us10y` | FRED target_date lookback 확대 | 최근 정상 snapshot | 3영업일 | 금리 레벨 기반 분기에 중요 |
| `vix` | FRED target_date lookback 확대 | 최근 정상 snapshot | 1영업일 | 변동성 급등 감지에 중요 |
| `oil_wti` | FRED target_date lookback 확대 | 최근 정상 snapshot | 3영업일 | WTI shock 분기에 중요 |

### 5.3 stale fallback 허용 규칙

#### 기본 허용

- 직전 정상 snapshot이 존재하고 `snapshot_date`와의 차이가 policy 한도 이내면 fallback 가능하다.
- 값이 fallback된 필드는 `fallback_trace`에 반드시 기록한다.
- fallback된 critical 값이 하나라도 있으면 `data_quality.status`는 `complete`가 아니라 `resolved_with_fallback`으로 둔다.

#### 차단 조건

- 허용 stale 일수를 초과한 경우
- 이전 snapshot 값도 null/Unknown인 경우
- episode_date보다 미래 snapshot에서 가져오려는 경우
- `spy_change`/`nasdaq_change`가 휴장일 stale인지, 실제 거래일 데이터인지 판단 불가하고 1영업일을 초과한 경우
- fallback 후에도 critical 누락이 남은 경우

### 5.4 Fear & Greed cache 설계

`feargreed_fetcher`에 `sentiment_fetcher`와 유사한 cache 계층을 추가한다.

- cache key: `feargreed:alternative_me:latest`
- fresh TTL: 12시간
- stale 허용: 3일
- 저장 값:

```json
{
  "fear_greed": 48,
  "fear_greed_label": "Neutral",
  "provider_timestamp": "...",
  "fetched_at": "..."
}
```

API 실패 시 처리 순서:

1. fresh cache 사용
2. API 호출
3. API 성공 시 cache 저장
4. API 실패 시 stale cache 사용
5. stale cache도 없으면 `None` 반환

### 5.5 FRED target_date 정합성 보정

현재 FRED fetcher는 `target_date`를 받지만 실제 조회는 현재 날짜 기준이다. 이를 다음처럼 변경한다.

- `target_date`가 있으면 `end = parse_date(target_date)`
- `target_date`가 없으면 기존처럼 오늘 날짜
- 기본 lookback은 10일 유지
- FRED 개별 series가 비면 fallback resolver에서 최근 정상 snapshot을 검토

이 변경으로 과거 날짜 재실행과 weekend/holiday 재처리의 재현성이 개선된다.

### 5.6 source_status / diagnostics

각 fetcher가 최종 결과와 함께 source status를 반환하는 것이 이상적이나, 1차 구현에서는 backward compatibility를 위해 별도 optional 구조로 시작한다.

```python
source_status = {
    "fred": {
        "DGS10": {"status": "ok", "attempts": 1},
        "VIXCLS": {"status": "empty", "attempts": 3},
    },
    "yfinance": {
        "SPY": {"status": "timeout", "attempts": 3},
    },
    "feargreed": {
        "status": "api_failed_cache_stale_used",
    },
}
```

1차 구현에서는 logger 기반 diagnostics와 `fallback_trace`만으로 시작하고, 2차에서 fetcher 반환 타입 확장을 검토한다.

## 6. DB 저장 설계

### 6.1 권장 컬럼

`daily_snapshots`에 JSONB 컬럼을 추가한다.

```sql
alter table icg.daily_snapshots
add column if not exists data_quality jsonb;
```

이미 유사한 `signal_quality` 확장 필드가 있으나, `signal_quality`는 분석 신호 품질에 가깝고 `data_quality`는 원천 데이터 수집/보정 감사에 가깝다. 둘을 분리하는 것이 바람직하다.

### 6.2 컬럼 추가가 어려운 경우의 임시안

- `extended_data["signal_quality"]`에 `data_collection` 하위 key로 저장한다.
- 단, 장기적으로는 `data_quality` 전용 컬럼을 권장한다.

## 7. 코드 변경 계획

### 7.1 Phase 1 — 안전한 fallback 최소 구현

| 파일 | 변경 |
|---|---|
| `engine/data/critical_fallback_resolver.py` | 신규. critical 누락 탐지, recent snapshot fallback, metadata 생성 |
| `engine/data/feargreed_fetcher.py` | api_cache fresh/stale fallback 추가 |
| `engine/data/fred_fetcher.py` | `target_date` 기준 lookback 반영 |
| `scripts/run_market.py` | `build_snapshot_payload()` 이후 resolver 호출, `data_quality`를 extended payload에 병합 |
| `engine/data/snapshot_writer.py` | `data_quality`를 extended field로 허용 또는 별도 처리 |
| `tests/test_critical_fallback_resolver.py` | policy 단위 테스트 추가 |
| `tests/test_feargreed_fetcher.py` | cache fallback 테스트 추가 |
| `tests/test_fred_fetcher.py` | target_date lookback 테스트 추가 |

### 7.2 Phase 2 — source provider 다변화

- SPY/NASDAQ/USDKRW에 보조 provider 추가 검토
- provider별 quota, 비용, 인증 방식 확정
- source_status 구조화 반환 도입

### 7.3 Phase 3 — publish gate 연동

- fallback된 critical 값이 많은 경우 publish 단계에서 자동 발행 대신 review 상태로 전환
- 예: `critical_fallback_count >= 3` 또는 `vix`/`spy_change` 동시 stale이면 publish block

## 8. run_market 통합 순서

현재 순서:

```python
snapshot_payload = build_snapshot_payload(...)
enforce_critical_quality(snapshot_payload)
upsert(...)
```

변경 후:

```python
snapshot_payload = build_snapshot_payload(...)
resolved_payload, data_quality = resolve_critical_fallbacks(
    snapshot_date=episode_date,
    payload=snapshot_payload,
)
extended_data["data_quality"] = data_quality

enforce_critical_quality(resolved_payload)
upsert(...resolved fetcher dicts or resolved payload...)
```

주의점: 현재 `upsert()`는 fetcher별 dict를 받아 내부에서 payload를 재조립한다. resolver가 payload를 직접 보정하면, 다시 fetcher dict로 역분해해야 하는 문제가 생긴다. 따라서 다음 중 하나를 선택해야 한다.

### 선택안 A — `upsert_payload()` 추가 권장

```python
def upsert_payload(snapshot_date: str, payload: dict) -> None:
    upsert_snapshot(snapshot_date, payload)
```

- 장점: resolver 결과를 그대로 저장 가능
- 단점: 기존 테스트 일부 조정 필요

### 선택안 B — resolver가 fetcher dict들을 직접 mutate

- 장점: 기존 `upsert()` 시그니처 유지
- 단점: fallback metadata와 값 변경 추적이 복잡해짐

**권장:** 선택안 A. 데이터 품질 계층이 canonical payload 단위로 동작하기 때문이다.

## 9. 품질 게이트 정책

### 9.1 STEP 2 통과 조건

- `critical_missing_after == []`
- fallback된 필드의 `age_days`가 policy 한도 이내
- `blocked_fields == []`

### 9.2 STEP 2 실패 조건

- fallback 후에도 critical 누락 존재
- critical field fallback source가 허용 범위를 벗어남
- FRED API key 누락처럼 설정 오류가 명확함

### 9.3 운영 override

`CRITICAL_DATA_GATE_ENABLED=false`는 유지하되, 다음 metadata를 강제로 남긴다.

```json
{
  "critical_gate_override": true,
  "override_reason": "env CRITICAL_DATA_GATE_ENABLED=false",
  "missing_at_override": ["..."]
}
```

## 10. 테스트 계획

### 10.1 단위 테스트

1. optional 누락만 있으면 fallback 없이 pass metadata 생성
2. `fear_greed` 누락 + fresh cache 존재 → cache 값 보정
3. `fear_greed` 누락 + stale cache 2일 → 보정
4. `fear_greed` 누락 + stale cache 5일 → 보정 거부
5. `usdkrw` 누락 + 전일 정상 snapshot → 보정
6. `vix` 누락 + 3영업일 초과 snapshot → 보정 거부
7. future snapshot은 fallback 후보에서 제외
8. fallback 후 `enforce_critical_quality()` 통과/실패 케이스 검증

### 10.2 통합 테스트

1. `step_data()`에서 primary fetcher 일부가 None을 반환하도록 monkeypatch
2. resolver가 payload를 보정하는지 확인
3. upsert payload에 `data_quality`가 포함되는지 확인
4. fallback 불가능 시 `CriticalDataMissingError`가 발생하는지 확인

### 10.3 회귀 테스트

- 기존 `tests/test_workflow_run_market.py`
- 기존 `tests/test_run_market_quality.py`
- 신규 fallback tests
- `python -m py_compile` 대상에 신규 모듈 포함

## 11. 운영 로그 예시

### 11.1 fallback 성공

```text
[CriticalFallback] missing_before=['fear_greed'] resolved=['fear_greed'] blocked=[]
[CriticalDataGate] 통과 missing=0 optional=2 fallback_count=1 status=resolved_with_fallback
```

### 11.2 fallback 실패

```text
[CriticalFallback] missing_before=['vix'] resolved=[] blocked=['vix: stale source too old age_days=4 max=1']
CRITICAL market data missing (STEP_2 date=2026-06-20): ['vix']
```

## 12. 리스크와 완화책

| 리스크 | 설명 | 완화 |
|---|---|---|
| stale 값으로 시장 급변을 놓침 | VIX/SPY 변화가 큰 날 stale fallback이 왜곡 가능 | stale 허용일을 짧게 두고 publish gate에서 review 전환 |
| fallback metadata 누락 | 값만 보정되면 감사 불가 | resolver 단위 테스트로 trace 필수 검증 |
| DB schema 미반영 | `data_quality` 컬럼이 없으면 upsert 실패 | 임시로 `signal_quality.data_collection`에 저장 가능 |
| 과거 snapshot 오염 | 잘못된 snapshot에서 fallback | future 제외, critical non-null only, age limit 적용 |
| 코드 복잡도 증가 | fetcher별 책임 혼재 | resolver를 canonical payload 후처리로 격리 |

## 13. 구현 우선순위

1. `upsert_payload()` 추가 및 canonical payload 저장 경로 확보
2. `critical_fallback_resolver.py` 신규 작성
3. Fear & Greed cache fallback 추가
4. FRED `target_date` 반영
5. `run_market.step_data()`에 resolver 연결
6. tests 추가
7. workflow/run log에 fallback summary 출력

## 14. 완료 기준

- critical 필드가 일시적으로 비어도 허용 정책 내 fallback으로 STEP 2가 통과한다.
- fallback 불가능한 critical 누락은 기존처럼 STEP 2에서 차단된다.
- 저장된 snapshot에 fallback metadata가 포함된다.
- 기존 품질 테스트와 신규 fallback 테스트가 모두 통과한다.
- 운영자가 run log만 보고 어떤 필드가 어떤 source로 보정됐는지 확인할 수 있다.
