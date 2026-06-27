# Strict Continuity Retry Hardening 상세 설계

작성일: 2026-06-28

## 1. 장애 원인

`run_market` narrative 단계는 `CONTINUITY_STRICT_ENABLED=true`일 때 이전 회차의 `next_hook`/`must_continue_from`과 `unresolved_threads`가 생성 스크립트에 회수됐는지 결정적으로 채점한다. 공유된 로그에서는 Claude 생성과 strict retry가 모두 완료됐지만, 최종 점수가 35점으로 유지되고 `opening_hook_payoff`, `unresolved_thread_resolution`이 누락되어 `StoryContinuityError`가 발생했다.

핵심 원인은 다음과 같다.

1. 기존 retry feedback은 “명시적으로 acknowledge”처럼 의미 기반 지시가 강했고, strict scorer는 keyword overlap 기반이라 paraphrase에 취약했다.
2. `resolved_threads`는 bookkeeping 필드인데도 기존 지시는 “include at least one acknowledged or resolved”처럼 패널 서술과 top-level 배열 중 하나를 선택할 수 있게 해 LLM 출력이 scorer 기대와 어긋날 수 있었다.
3. 첫 생성 prompt와 retry prompt의 표현이 달라, strict 모드에서 반드시 복사해야 하는 문자열 계약이 일관되지 않았다.

## 2. 개선 원칙

- 생성 후 패널 문장을 코드로 임의 조작하지 않는다.
- 대신 모델 입력 단계에서 scorer가 검증 가능한 “verbatim continuity contract”를 제공한다.
- 이전 hook과 thread는 이미 DB에서 공급된 안전한 story context이므로, 정확한 복사 지시를 통해 hallucination 없이 strict gate를 통과하도록 유도한다.
- retry 후에도 실패하면 strict gate는 계속 실패시켜 실제 서사 누락을 숨기지 않는다.

## 3. 상세 설계

### 3.1 Initial prompt hard rule 강화

`Previous Episode Continuity` 섹션에서 다음을 명시한다.

- Panel 1 narration 또는 key_text에 다음 exact anchor를 그대로 포함한다.
  - `이전 회차의 단서: {previous_next_hook_or_must_continue_from}`
- unresolved thread가 있으면 top-level `resolved_threads`에 목록 중 최소 1개를 verbatim으로 복사한다.

### 3.2 Retry feedback hardening

기존 retry feedback에 다음 machine-checkable 필드를 추가한다.

- `EXACT_OPENING_ANCHOR`
- `EXACT_RESOLVED_THREAD`
- `verbatim` 복사 요구

이로써 retry는 “의미상 회수”가 아니라 scorer와 동일한 계약을 만족하도록 유도한다.

### 3.3 Gate 정책

- strict retry 횟수와 최종 validation 흐름은 유지한다.
- retry 후에도 score < 70이면 실패한다.
- 실패는 운영자가 previous hook 품질 또는 모델 출력 품질을 확인해야 하는 신호로 남긴다.

## 4. 기대 효과

- Claude가 hook/thread를 의역해 strict scorer와 불일치하는 사례를 줄인다.
- 생성 후 코드가 스토리 문장을 임의 변경하지 않아 narrative ownership이 명확하다.
- 실패 시 원인은 “verbatim contract 미준수”로 더 명확해진다.
