# 연재 서사 P0 상세설계 및 개발 착수 기준

- 작성일: 2026-08-28
- 상위 요구사항: `SERIAL_NARRATIVE_CHARACTER_VILLAIN_REQUIREMENTS_2026-08-28.md`
- 구현 범위: 캐릭터 편중 방지, 구조화 thread, 빌런 독자 카드, 패널 상태 전이 검증

## 1. 구현 경계

P0는 기존 스키마와 발행 데이터를 깨지 않는 additive 방식으로 구현한다. 신규 계약은
`SERIAL_NARRATIVE_P0_ENABLED` 플래그 아래 파이프라인에 연결하고, 기존 호출자는 새
인자를 전달하지 않아도 동일 결과를 얻는다.

```text
continuity bundles
  ├─ recent_hero_ids / lead_counts / consecutive_lead
  └─ structured_threads
       ↓
CharacterCastingService (NO_BATTLE 우선 적용)
       ↓
StoryBeatPlan + VillainReaderCard + serial_contract
       ↓
EpisodeScript
       ↓
PanelPerformanceSpec transition validation
```

## 2. 모듈별 책임

| 모듈 | 변경 책임 |
|---|---|
| `engine/narrative/serial_contracts.py` | 노출 이력 계산, 회전 주연 선정, canon mirror 검증, 빌런 카드, thread 원장 |
| `engine/narrative/schema.py` | `VillainReaderCard`, `SerialEpisodeContract`와 StoryBeatPlan 선택 필드 |
| `engine/narrative/continuity.py` | 기존 문자열 thread를 안정적인 ID 계약으로 승격하고 최근 배역 이력 집계 |
| `engine/narrative/character_selector.py` | 기존 규칙의 시장 적합도 후보를 유지하며 선택적 최근 이력 감점 적용 |
| `engine/narrative/story_planner.py` | episode archetype, 실질 payoff, 빌런 정보 전달 계약 생성 |
| `engine/image/performance_validator.py` | 패널 간 위치·소품·부상·환경 상태 불연속 검증 |
| `scripts/run_market.py` | feature flag, continuity 선조회, 품질 trace 저장 및 strict gate |

## 3. 하위 호환 전략

- `select_for_no_battle(delta)`의 반환형은 유지한다.
- 최근 이력이 없거나 플래그가 꺼지면 기존 선택 결과를 유지한다.
- 기존 continuity의 문자열 `unresolved_threads`는 결정론적 SHA 기반 ID로 변환한다.
- StoryBeatPlan 신규 필드는 기본값을 제공해 과거 fixture를 수용한다.
- 상태 map이 비어 있으면 불연속을 추정하지 않는다. 양쪽에 같은 key가 명시된 경우만
  hard validation한다.

## 4. 알고리즘

### 4.1 편성

1. 기존 시장 규칙으로 모든 영웅의 `market_fit`을 계산한다.
2. 최근 주연 10회에서 회당 12점, 연속 주연 회당 18점을 감점한다.
3. 마지막 5회에 등장하지 않은 영웅에게 최대 15점의 absence bonus를 준다.
4. 시장 적합도 50점 이상 차이가 나는 후보를 회전만으로 뒤집지 않는다.
5. 결과와 후보별 breakdown을 `casting_trace`에 기록한다.

### 4.2 thread

- ID: 정규화한 `type + promise + owner`의 SHA-256 앞 12자리.
- 이전 OPEN/DUE thread와 현재 `resolved_threads`를 비교해 PAID를 판정한다.
- 직전 `next_hook`은 기본 `MYSTERY`, 빌런 압박은 `VILLAIN_PLAN`이다.
- due가 0 이하인데 PAID/EXTENDED가 아니면 strict gate 오류다.

### 4.3 빌런 정보

canon의 이름, event, trigger, belief, description에서 reader card를 결정론적으로 만든다.
자연현상형은 `immediate_goal` 대신 발현/약화 조건을 사용하고 의도를 부여하지 않는다.
신규/최근 window 미등장 빌런은 `FULL`, 재등장은 `REFRESH` 소개 모드다.

### 4.4 상태 전이

P(n).exiting과 P(n+1).entering에서 같은 key 값이 다르면 다음을 오류로 기록한다.

- `PERF_E_LOCATION_DISCONTINUITY`
- `PERF_E_POSITION_DISCONTINUITY`
- `PERF_E_PROP_DISCONTINUITY`
- `PERF_E_INJURY_DISCONTINUITY`
- `PERF_E_ENVIRONMENT_DISCONTINUITY`

명시된 `transition_explanation`이 향후 planner v2에서 들어오기 전까지 위치 변경은
경고, 소품·부상 복구는 오류로 처리한다.

## 5. 파이프라인 모드

| 모드 | 동작 |
|---|---|
| `shadow` | trace와 issue를 기록하고 기존 발행 유지 |
| `warning` | 경고 로그 및 asset metadata 저장 |
| `strict` | 만기 thread, 불완전 신규 빌런 카드, 상태 hard error에서 중단 |

## 6. 테스트 전략

1. **단위:** 편성 감점/시장 압도 예외, ID 안정성, 자연현상 빌런, mirror 불일치.
2. **통합:** continuity window → 회전 편성 → StoryBeatPlan reader card/thread 계약.
3. **파이프라인:** `run_market` feature flag 및 strict/warning 분기.
4. **전수:** 전체 pytest 실행 후 기존 NO_BATTLE, planner, continuity, performance 회귀 확인.

## 7. 완료 조건

- P0 신규 테스트와 관련 파이프라인 테스트가 모두 통과한다.
- 전체 pytest가 통과한다.
- `git diff --check`와 Python compile 검사가 통과한다.
- 요구사항 문서의 P0 항목과 구현 파일/테스트가 추적 가능하다.
