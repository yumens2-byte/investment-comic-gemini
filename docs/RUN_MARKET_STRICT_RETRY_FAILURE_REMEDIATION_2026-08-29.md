# Run Market strict retry 실패 분석 및 보완

## 1. 현상

2026-08-29 narrative stage는 의도대로 fail-closed했지만 두 번째 생성까지 다음 위반이 남아 종료됐다.

- `UNSUPPORTED_ALGORITHM_CAUSALITY: P1.key_text`
- `SYNTHETIC_THREAD_PLACEHOLDER: resolved_threads[0]`

이는 품질 gate의 오탐이나 실행 오류가 아니다. 이전 실행에서 DB에 저장된 오염된 continuity와 StoryBeatPlan을 새 strict gate가 그대로 입력받아, **retry prompt가 반드시 복사하라고 요구한 문자열을 production gate가 금지하는 계약 충돌**이었다.

## 2. 원인 흐름

```text
legacy continuity DB
  next_hook = "...알고리즘 압력 구간..."
  unresolved = "Track continuing pressure from villain CHAR_VILLAIN_004"
  resolved = "Previous battle outcome ... PEACEFUL_GROWTH"
       ↓
복원된 StoryBeatPlan / strict retry
  EXACT opening/thread verbatim 복사 요구
       ↓
Claude 두 번째 결과도 금지 문자열 포함
       ↓
ProductionQualityGate fail
```

첫 번째 시도에서 gate가 8개 위반을 정확히 검출하고 두 번째 시도에서 2개로 줄였으므로 retry 자체는 작동했다. 다만 입력 계약이 상호 모순돼 0개까지 줄일 수 없었다.

## 3. 보완 내용

### 3.1 Read-boundary continuity sanitization

과거 DB row를 직접 마이그레이션하지 않고, continuity를 읽거나 context를 복원하는 경계에서 다음을 제거·중립화한다.

- `Previous battle outcome remains unresolved emotionally`
- `Track continuing pressure from villain CHAR_*`
- `PEACEFUL_GROWTH` 운영 상태 문자열
- evidence 없이 저장된 `알고리즘 압력 구간`을 `이전 회차에서 묘사한 시장 압력 구간`으로 중립화
- cached `recent_threads`와 `thread_ledger`의 동일 placeholder

원본 DB 기록은 감사 가능하도록 보존하고 생성 입력만 정제한다.

### 3.2 StoryBeatPlan 강제 재구축

narrative stage가 DB에서 기존 plan을 복원했더라도, 정제된 `previous_episode`와 `continuity_window`를 사용해 StoryBeatPlan을 다시 만든다. 이로써 analysis stage에서 만들어진 오염된 `continuity_payoff`, `dialogue_intent`, `due_threads`가 retry prompt로 재진입하지 않는다.

### 3.3 Retry 지시 변경

기존 `EXACT_OPENING_ANCHOR`, `EXACT_RESOLVED_THREAD`, `verbatim` 요구를 제거했다.

- 안전하게 정제된 prior hook을 의미상 paraphrase한다.
- 패널에서 observable action이 있을 때만 thread를 resolve한다.
- 해결되지 않았으면 unresolved로 유지한다.
- 과거 회차에 있었다는 이유로 unsupported causality나 운영 placeholder를 복사하지 않는다.

### 3.4 Strict 상태 관측성

로그에 `SERIAL_NARRATIVE_P0_ENABLED=OFF`가 표시되더라도 `CONTINUITY_STRICT_ENABLED=ON`이면 코드상 production strict는 ON이다. 혼동을 막기 위해 workflow에 다음 effective 상태를 별도로 출력한다.

```text
PRODUCTION_QUALITY_EFFECTIVE_STRICT = ON
```

## 4. 보완 후 기대 실행

1. DB에서 analysis context를 복원한다.
2. legacy continuity와 window ledger를 정제한다.
3. StoryBeatPlan을 정제된 입력으로 다시 생성한다.
4. 첫 Claude 결과를 continuity/production gate로 평가한다.
5. 실패하면 서로 모순되지 않는 통합 retry feedback을 전달한다.
6. 두 번째 결과가 pass이면 저장하고, 위반이 남으면 현재와 같이 exit code 1로 차단한다.

Strict gate를 약화하거나 위반을 warning으로 되돌리지 않는다. 이번 보완은 **차단을 유지하면서 재생성이 성공 가능한 입력 계약을 만드는 것**이다.

## 5. 재검증 조건

- retry feedback에 `EXACT_*`, `verbatim`, 운영 placeholder가 없다.
- 복원된 hook과 plan에 unsupported `알고리즘 압력 구간`이 없다.
- cached thread ledger에서 `PEACEFUL_GROWTH`와 `CHAR_VILLAIN_*` placeholder가 제거된다.
- workflow에 effective production strict가 출력된다.
- 유효한 독자용 thread는 정제 과정에서 보존된다.
- 두 번째 결과에 실제 위반이 남으면 계속 exit code 1로 차단된다.
