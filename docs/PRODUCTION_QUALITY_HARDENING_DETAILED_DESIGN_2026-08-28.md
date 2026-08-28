# 운영 에피소드 품질 결함 보완 상세설계

## 1. 목표

`ICG-2026-08-28-001`에서 확인된 변화율 재계산, 근거 없는 시장 인과, 누락 배역, 빈 연재 hook/thread, `NO_BATTLE`/`BATTLE` 불일치 및 연속성 점수 위양성을 persist 이전에 탐지한다. `SERIAL_NARRATIVE_P0_ENABLED=true`에서는 1회 재생성 후에도 위반이 남으면 hard fail한다.

## 2. 데이터 의미 계약

`delta_engine`은 각 snapshot 컬럼에 `semantic_type`, `unit`, `change`를 부여한다.

| semantic_type | `pct` 의미 | 비교 규칙 |
|---|---|---|
| `daily_return_pct` | `curr` 자체 | 전일 수익률과 재비교 금지 |
| `level` | level의 전일 대비 변화율 | 기존 계산 유지 |
| `rate` | `null` | `change`에 절대 변화 저장 |
| `spread` | `null` | `change`에 절대 변화 저장 |
| `index_score` | `null` | `change`에 점수 변화 저장 |

Story Context formatter는 `daily_return_pct`를 `SPY +0.6553%`처럼 한 번만 표시한다. SPY/NASDAQ 수치만으로 Algorithm Reaper나 알고리즘 주문 흐름을 실제 원인으로 지정하지 않는다.

## 3. ProductionQualityGate

`validate_production_episode`는 다음 violation code를 반환한다.

- `NUMERIC_PERCENT_OUTLIER`: SPY/NASDAQ 25% 초과 또는 모든 지표의 100% 초과 publish 숫자
- `DOUBLE_PERCENT_CHANGE`: `daily_return_pct`의 `pct != curr`
- `UNSUPPORTED_ALGORITHM_CAUSALITY`: 알고리즘 거래 evidence 없이 인과 단정
- `REQUIRED_CAST_MISSING`: StoryBeatPlan 필수 배역이 최종 패널에서 누락
- `SCENARIO_PANEL_MISMATCH`: `NO_BATTLE`에 `BATTLE` 패널 사용
- `SERIAL_NEXT_HOOK_MISSING`: 연재 모드에서 `next_hook` 누락
- `SERIAL_THREAD_LEDGER_EMPTY`: resolved/unresolved thread 모두 누락
- `STATIC_ACTION_STREAK`: 서사 패널 80% 이상이 stand/look/study/read/watch/sit에 의존

Gate는 첫 생성 후 violation을 Claude retry feedback으로 전달한다. 두 번째 결과에도 violation이 있으면 `ProductionQualityError`를 발생시켜 JSON 저장·persist·image 단계로 진행하지 않는다.

## 4. 편성 및 NO_BATTLE 설계

게스트 판정 결과를 `neutral_guest_ids`로 StoryBeatPlan에 전달하고 P3/P4 필수 배역으로 지정한다. `NO_BATTLE` beat는 단순 관찰 대신 검증 가능한 가설, 구체 행동, 저항, 상태 변화를 요구하며 `BATTLE` panel type을 금지한다.

`SENTINEL_YIELD`, `CRYPTO_SHADE`는 `characters.yaml` 영웅/빌런이 아니라 별도 character engine이 관리하는 등록 중립 게스트다. Canon validator는 두 ID를 `npc` role로만 허용한다. 이 예외가 없으면 planner가 요구한 게스트를 제대로 생성해도 사후 canon 검사에서 거부되는 모순이 생긴다.

## 5. 연속성 점수 설계

- 입력이 없는 관계 차원은 20점 만점으로 처리하지 않고 `0/not applicable`로 제외한다.
- unresolved thread는 opening hook keyword 중복만으로 15점 보정하지 않는다.
- 적용 가능한 차원의 획득점만 100점으로 재정규화한다.
- 필수 beat는 텍스트 존재뿐 아니라 `required_character`와 `continuity_payoff`도 확인한다.
- 연재 hard contract인 hook/thread 부재는 총점과 별도로 ProductionQualityGate가 차단한다.

## 6. 파이프라인 순서

```text
snapshot → semantic delta → context/evidence → StoryBeatPlan
→ Claude generation
→ grounding + continuity + production quality
→ (violation) one constrained retry
→ strict production quality
→ script archive → persist → image
```

## 7. 운영 및 하위 호환

- 지표 dictionary의 기존 `curr`, `prev`, `pct` 키는 유지한다.
- `daily_return_pct`의 `pct`는 기존 공식 엔진과 호환되도록 `curr`과 동일하게 제공한다.
- strict 발행 차단은 기존 `SERIAL_NARRATIVE_P0_ENABLED`에 연결한다.
- flag가 꺼져 있어도 prompt의 단위·hook·필수 배역·NO_BATTLE guardrail은 항상 제공한다.
- VIX처럼 실제 상대 변화율이 25%를 넘을 수 있는 지표는 equity threshold를 적용하지 않는다.

## 8. 완료 조건

1. `0.0508 → 0.6553` SPY 입력에서 `+1190%`가 생성되지 않는다.
2. CRYPTO_BASIS spread는 자산 수익률로 출력되지 않는다.
3. 제공된 불량 에피소드 fixture가 7개 핵심 violation을 모두 발생시킨다.
4. VIX `+32.4%`와 같은 합법적인 상대 변화는 오탐하지 않는다.
5. 관련 파이프라인 테스트와 전체 테스트가 통과한다.
