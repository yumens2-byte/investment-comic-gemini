# Market Talk 원천 메타데이터 잔여 조건 상세설계

## 문제와 변경 범위

2026-10-09 운영 사전 점검에서 `icg.daily_snapshots.data_quality.source_status`가
빈 객체여서 Market Talk가 `SOURCE_SESSION_REQUIRED`로 보류되었다.
기존 수집기는 숫자만 반환하고 FRED 관측 날짜, yfinance 일봉 날짜 및
alternative.me 응답 timestamp를 버렸으며 STEP_2는 resolver의 source_status를 전달하지 않았다.

메인 수집기 변경을 독립 PR로 제출한다. Market Talk PR #109의 side-only 변경
규칙을 유지한다. Supabase 스키마 변경 없이 기존 data_quality JSONB를 사용한다.
기존 값 계산, critical fallback 정책, 모델 비용 및 게시 동작을 변경하지 않는다.

## 계약

각 필드의 출처는 `data_quality.source_status.<field>`에 저장한다.

| 키 | 의미 |
|---|---|
| status | ok / missing / invalid_value / metadata_missing / stale_cache / previous_snapshot |
| provider, instrument | 실제 선택된 제공자와 원천 티커 또는 시리즈 |
| unit | vix·fear_greed=index, us10y·등락률=percent, oil_wti=USD_per_barrel |
| market_session_date | 응답에서 선택한 실제 관측 날짜. snapshot_date로 대체하지 않음 |
| fetched_at | 타임존이 있는 응답 수집 시각 |
| observed_at | 제공자 timestamp가 있으면 해당 시각, 날짜만 제공되면 응답 관측 시각 |
| observed_at_kind | provider_timestamp / response_received |
| source_time_precision | timestamp / date |
| source_timestamp | 제공자가 제공한 정확한 timestamp가 있을 때만 저장 |
| previous_session_date, calculation | 등락률의 직전 일봉 날짜와 close_to_close_percent 계산 방식 |
| market_domain | alternative.me의 fear_greed는 crypto. 미국 주식 CNN 지수로 해석하지 않음 |

FRED 날짜와 yfinance 일봉 날짜는 종가 확정 시각 또는 발표 시각의 증거가 아니다.
이를 임의의 장 마감 시각으로 변환하지 않는다. Market Talk는 원천 날짜의
지연 허용 범위와 VIX/SPY/Nasdaq 날짜 일치 조건을 별도로 검사한다.
현재 일봉 데이터만으로 거래소의 종가 확정 여부를 단정하지 않는다.

## 제공자 처리

1. FRED: dropna 후 선택된 값의 index 날짜를 보존한다. DGS10는 percent 그대로 사용한다.
2. yfinance: 동일 응답에서 값과 마지막 유효 일봉 날짜를 추출한다. 등락률에는
   직전 유효 일봉 날짜도 기록한다. 병렬 작업은 반환값을 메인 스레드에서 병합한다.
3. 매크로 override: 값이 실제 존재할 때만 FRED 값과 출처를 함께 교체한다.
   실패한 override의 출처로 정상 FRED 값을 덮어쓰지 않는다.
4. alternative.me: Unix timestamp를 UTC aware datetime으로 변환한다.
   원천 timestamp를 캐시에 함께 저장하고 fresh cache에서도 원래 시각을 보존한다.
   metadata 없는 구형 fresh cache는 메타데이터 모드에서 API 재수집을 시도한다.
   API 실패 후 stale cache를 사용하면 stale_cache로 기록한다.
5. critical fallback: 이전 스냅샷 값 선택 시 previous_snapshot 상태와 원래 실패
   시도를 보존한다. 해당 값을 현재 제공자의 정상 관측으로 표시하지 않는다.
6. 기존 숫자 반환 API는 유지하고 optional keyword source_status로 증거를 전달한다.
   STEP_2에서 resolver에 넘긴 뒤 기존 upsert 경로로 저장한다.

## 검증과 운영 조건

- 단위: 날짜 누락, 비유한 값, 타임존, 마지막 유효 FRED 날짜, 단일 일봉,
  등락률 원천 날짜, override 성공·실패, timestamp 누락·오류, fresh·stale·구형 캐시,
  previous_snapshot 출처와 입력 불변성을 fixture로 확인한다.
- 통합: 실제 STEP_2에서 provider fixture를 거쳐 upsert에 전달된 source_status를 확인한다.
- 회귀: 메인 tests 전체 및 ruff, side/main 변경 혼합 금지 규칙을 검사한다.
- 실제 운영 조건: 메인 수집기 반영 후 새 스냅샷의 6개 필드 출처가 모두 유효하고,
  #109의 validate_source가 통과해야 한다. 이 결과 없이 Market Talk 오픈하지 않는다.
  기존 빈 메타데이터를 백필하거나 수집 시각만으로 원천 날짜를 추정하지 않는다.
- Market Talk DB migration, runtime contract 및 게시 검증은 #109의 별도 운영 절차다.
  이 PR 자체는 Facebook 게시나 Market Talk 오픈을 수행하지 않는다.

## 원천 문서

- FRED observations API: https://fred.stlouisfed.org/docs/api/fred/series_observations.html
- yfinance download: https://ranaroussi.github.io/yfinance/reference/yfinance.functions.html
- alternative.me crypto Fear & Greed API: https://alternative.me/crypto/fear-and-greed-index/#api
