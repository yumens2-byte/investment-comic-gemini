# ICG 로직/설계 고도화 리뷰 (2026-04-18)

> 범위: 공개 코드 기준 점검 + Notion 링크 접근 불가에 따른 대체 리뷰

## 1) 현재 아키텍처 요약

- 파이프라인은 `run_market.py` 기준으로 데이터 수집(2) → 분석/시나리오(3) → 내러티브/이미지/퍼시스트 단계로 구성된다.
- STEP 3에서 `SCENARIO_V2_ENABLED` 플래그 기반으로 기존 1:1 전투와 v2 시나리오(ONE_VS_ONE / NO_BATTLE / ALLIANCE)를 선택한다.
- 민감 프롬프트/상수는 `notion_loader.py`를 통해 런타임에 Notion에서 로드한다.

## 2) 강점

1. **Feature Flag 기반 점진 배포**
   - v2 로직을 환경변수로 격리하여 운영 리스크를 줄인 점이 좋다.
2. **시나리오 책임 분리**
   - `scenario_selector.py`가 risk/scenario/ending tone을 단일 책임으로 관리해 유지보수가 쉽다.
3. **Notion-코드 분리 전략**
   - 민감한 프롬프트와 상수를 repo 밖(Notion)으로 분리한 방향은 보안·운영 측면에서 적절하다.

## 3) 미국 정보 기반 세계관 자동화 관점의 개선 우선순위

### P0 (필수)

1. **기준 시점(Timezone/Target Date) 일관화**
   - 현재 일부 fetcher가 `target_date` 인자를 받지만 내부적으로 `date.today()`를 사용한다.
   - 백필(backfill), 재현성(reproducibility), 미국 장마감 기준 스토리 일관성이 깨질 수 있다.
   - 개선안:
     - `target_date`를 모든 데이터 fetcher의 실질 기준일로 사용.
     - 거래일 캘린더(US/Eastern, 휴장일) 기반으로 "스토리 기준일"을 명시.

2. **Notion 로더 파싱 안정성 강화**
   - 현재 JSON 추출이 정규식/브레이스 스캔 혼합이라 블록 포맷 변경에 취약할 수 있다.
   - 개선안:
     - 블록 타입(code) + language(json) 우선 파싱.
     - 필수 키 스키마 검증(Pydantic/TypedDict).
     - 파싱 실패 시 버전/페이지ID 포함 경고 + 안전한 기본값.

3. **미국 매크로 이벤트 캘린더 결합**
   - CPI, FOMC, NFP, PCE, 실적 시즌(빅테크) 같은 이벤트를 "서사 트리거"로 명시적으로 연결하면 세계관 밀도가 급상승한다.
   - 개선안:
     - `macro_event_fetcher` 추가 (향후 경제캘린더 API 연동).
     - `event_classifier` 입력에 `macro_tags` 추가.

### P1 (중요)

4. **정량 리스크 모델 고도화 (현재 VIX/WTI 2축 → 멀티팩터)**
   - 지금 risk_level은 `VIX`, `WTI`만 사용한다.
   - 개선안:
     - DXY, HY Spread, US10Y 변화율, SPY drawdown, BTC 변동성 등을 가중합한 점수화.
     - 룰 기반 + 간단한 캘리브레이션(최근 6개월)으로 임계값 자동 조정.

5. **Arc Memory(연속성) 실제 데이터화**
   - 현재 `arc_context`는 고정값에 가깝다.
   - 개선안:
     - 최근 N화 outcome, villain 연속 등장 횟수, 승패 스트릭을 DB에서 조회.
     - `tension`을 stateful하게 업데이트해 "시즌형 서사" 생성.

6. **캐릭터 선택 설명가능성(Explainability) 로그**
   - 운영 관점에서 "왜 이 히어로/빌런이 선택됐는지" 추적이 중요.
   - 개선안:
     - `selection_reason` 필드를 `daily_analysis`에 저장.
     - Notion Tracker에 요약 컬럼(예: Trigger Metric, Risk Score) 추가.

### P2 (확장)

7. **미국 섹터/테마 빌런 확장**
   - 예: `Semiconductor Surge`, `AI Bubble`, `Regional Bank Stress` 등 테마형 빌런.
   - 이벤트 타입을 market regime + sector regime로 2단계 분리.

8. **품질/비용 SLO 운영**
   - 현재 비용/런타임 기록은 있으나 목표치(SLO) 중심 운영 지표는 약함.
   - 개선안:
     - 에피소드당 비용 상한, 생성 성공률, 재시도율 대시보드화.

## 4) Notion 설계서 점검 체크리스트 (접근 가능 시 즉시 대조 권장)

- 데이터 사전(Data Dictionary): 컬럼 단위 타입·단위·소스·업데이트 시각이 표준화되어 있는가?
- 임계값 관리: 이벤트/리스크 임계값이 "버전 + 변경 이력"으로 관리되는가?
- 프롬프트 버저닝: 내러티브/이미지 프롬프트에 semantic version이 있는가?
- 실패 복구: 각 STEP의 재시작 입력/출력 계약이 문서화되어 있는가?
- 스토리 QA: 금지어, 금융 사실성, 캐릭터 일관성 자동 검사 규칙이 있는가?

## 5) 즉시 실행 가능한 2주 로드맵 (제안)

- Week 1:
  - `target_date` 일관화 + US 거래일 유틸 추가
  - risk score v2 (멀티팩터) 구현 및 로그 저장
  - arc memory 최소 버전(최근 7화 통계)
- Week 2:
  - macro event 태그 연동
  - Notion 로더 JSON 스키마 검증
  - 분석 결과 설명 필드(why-selected) 저장/미러링

## 6) 한계 및 메모

- 제공된 Notion 링크는 현재 세션에서 직접 내용을 열람하지 못해, 코드와 README 기반으로 리뷰했다.
- Notion 원문(특히 임계값 테이블/프롬프트 블록/DB 스키마)을 열람할 수 있으면 항목별로 "적합/부적합/수정안" 형태의 정밀 갭 분석이 가능하다.
