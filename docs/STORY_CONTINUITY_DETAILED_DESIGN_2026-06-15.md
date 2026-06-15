# 전후 스토리 연속성 추가 갭 및 상세 설계

작성일: 2026-06-15

## 1. 배경

직전 개발에서 다음 P0 성격의 작업은 착수되었다.

- 프롬프트에 `Previous Episode Continuity` 섹션을 추가해 이전 회차 hook/thread를 직접 노출했다.
- `EpisodeScript`에 `next_hook`, `unresolved_threads`, `resolved_threads`, `relationship_delta`를 추가했다.
- continuity bundle에 구조화 thread, 관계 변화, arc snapshot을 저장하도록 확장했다.
- P1~P2가 이전 hook을 회수했는지 검사하는 strict gate를 추가했다.
- `CONTINUITY_STRICT_ENABLED` 운영 플래그를 추가했다.

이번 문서는 여기서도 아직 부족한 부분을 더 쪼개고, 실제 구현 가능한 상세 설계 단위로 정의한다.

## 2. 남아 있는 핵심 부족분

### 2.1 continuity gate가 “문자열 포함” 중심이다

현재 strict gate는 previous hook의 직접 문구 또는 키워드가 P1~P2에 들어갔는지를 검사한다. 이 방식은 빠르고 deterministic하지만 다음 한계가 있다.

- 의미적으로 회수했지만 단어가 다르면 false negative가 날 수 있다.
- 단어만 반복하고 실제 서사 연결은 없는 경우 false positive가 날 수 있다.
- `resolved_threads`가 실제 이전 `unresolved_threads` 중 무엇을 회수했는지 검증하지 않는다.

### 2.2 장기 arc와 직전 회차 continuity 간 충돌 판정이 없다

continuity bundle에 `arc_id`, `arc_day`, `active_villain`, `arc_tension` snapshot을 저장하기 시작했지만, 다음 회차 analysis/narrative 단계에서 현재 `arc_context`와 이전 bundle의 snapshot을 비교하지 않는다.

예상 문제:

- 직전 회차의 active villain과 오늘 arc active villain이 달라도 설명 없이 새 전투가 시작된다.
- arc tension이 크게 변해도 P1~P2에서 이유를 설명하지 않는다.
- intentional pivot과 continuity break를 구분할 수 없다.

### 2.3 캐릭터 관계 메모리가 저장만 되고 활용되지 않는다

`relationship_delta`는 스키마와 bundle에 생겼지만 다음 회차의 StoryBeatPlan, character prompt, prompt section에는 아직 충분히 반영되지 않는다.

예상 문제:

- 전 회차에서 동맹/배신/패배 후 감정이 생겨도 다음 회차 대사 톤에 반영되지 않는다.
- 캐릭터 등장 여부는 이어지지만 관계 감정선은 리셋되어 보인다.

### 2.4 continuity 관측성이 “경고 로그” 수준이다

strict mode가 아니면 continuity 실패는 warning만 남는다. DB에는 실패 원인, 회수율, degraded 여부가 구조화되어 저장되지 않는다.

예상 문제:

- 운영자가 어떤 회차가 단편적으로 보였는지 사후 분석하기 어렵다.
- strict mode를 켜기 전 shadow run에서 품질 지표를 축적하기 어렵다.

### 2.5 multi-episode memory depth가 직전 1회차 중심이다

현재 `load_previous_continuity()`는 latest prior published/assembled episode 하나를 가져온다. 장기 떡밥은 2~5회차에 걸쳐 이어질 수 있는데, 직전 회차만 보면 긴 호흡의 unresolved thread가 사라질 수 있다.

### 2.6 스크립트 생성 retry와 continuity gate가 연결되어 있지 않다

strict mode에서 gate 실패 시 에러는 발생하지만, Claude에게 “이전 hook을 회수해서 재생성”하는 targeted retry contract는 없다.

예상 문제:

- 사소한 P1/P2 누락 때문에 전체 실행이 실패한다.
- 실패 후 운영자가 수동 재실행해야 하고, 재실행도 같은 문제를 반복할 수 있다.

## 3. 상세 설계 A — Continuity Semantic Score v1

### 3.1 목표

문자열 포함 검사만으로 끝내지 않고, 이전 hook/thread가 실제로 회수되었는지 panel 단위 점수로 판단한다. LLM judge 없이 deterministic rule 기반으로 시작한다.

### 3.2 신규 모듈

대상 파일:

- `engine/narrative/continuity_score.py`
- `tests/test_continuity_score.py`

### 3.3 데이터 구조

```python
@dataclass(frozen=True)
class ContinuityScore:
    source_episode_id: str | None
    seed: str
    opening_overlap_score: float
    thread_resolution_score: float
    relationship_reuse_score: float
    total_score: float
    missing_requirements: list[str]
    matched_terms: list[str]
```

### 3.4 점수 규칙

| 항목 | 점수 | 설명 |
|---|---:|---|
| opening_overlap_score | 0~40 | P1~P2가 previous next_hook/must_continue_from의 핵심어를 회수 |
| thread_resolution_score | 0~30 | `resolved_threads` 또는 P1~P7 텍스트가 이전 unresolved thread 중 하나 이상 회수 |
| relationship_reuse_score | 0~20 | 이전 `relationship_delta` 대상 캐릭터/페어가 오늘 대사/beat에 반영 |
| strict beat compliance | 0~10 | `must_reference_previous=True` 패널에 실제 텍스트 존재 |

권장 threshold:

- `>=70`: pass
- `40~69`: warn/degraded
- `<40`: strict mode fail

### 3.5 integration

`validate_story_continuity()`는 내부에서 `score_story_continuity()`를 호출하도록 변경한다.

반환 warning 예시:

```text
Continuity score 35 below threshold 70: missing opening hook payoff, no unresolved thread resolution.
```

## 4. 상세 설계 B — Arc Pivot Contract

### 4.1 목표

직전 continuity bundle과 오늘 `arc_context`가 충돌할 때, 새 회차가 왜 장면/빌런/긴장도가 바뀌었는지 설명하도록 강제한다.

### 4.2 신규 함수

대상 파일:

- `engine/narrative/continuity.py`
- `engine/analysis/story_context_builder.py`
- `engine/narrative/story_planner.py`

```python
def detect_arc_pivot(previous_episode: dict, arc_context: dict) -> dict:
    return {
        "pivot_required": bool,
        "pivot_reasons": ["active_villain_changed", "arc_tension_jump"],
        "previous_active_villain": "...",
        "current_active_villain": "...",
        "previous_arc_tension": 52,
        "current_arc_tension": 78,
    }
```

### 4.3 prompt contract

`narrative_context_pack`에 아래 블록을 추가한다.

```json
"arc_pivot": {
  "pivot_required": true,
  "pivot_reasons": ["active_villain_changed"],
  "instruction": "P1-P2 must explain why the scene/villain changed before the new conflict escalates."
}
```

StoryBeatPlan 규칙:

- P1: previous hook 회수
- P2: pivot reason 설명
- P3 이후: 오늘 시장 원인/전투 전개

## 5. 상세 설계 C — Relationship Memory v1

### 5.1 목표

캐릭터 간 감정/관계 변화가 다음 회차 대사 톤과 등장 판단에 반영되도록 한다.

### 5.2 저장 위치

단기 구현:

- `script_json._continuity.relationship_delta`
- `analysis_ctx_json.previous_episode.relationship_delta`

중기 구현:

- `daily_analysis.story_state_json.relationship_state`

### 5.3 story_state 확장안

```json
"relationship_state": {
  "hero_gold_bond_muscle:villain_debt_titan": {
    "trust": -40,
    "conflict": 75,
    "last_scene": "Debt Titan retreated through the bond auction gate.",
    "unresolved_emotion": "hero suspects a trap"
  }
}
```

### 5.4 update rule

`update_after_episode()`에 optional `relationship_delta`를 전달한다.

```python
def update_relationship_state(story_state: dict, relationship_delta: dict[str, str]) -> dict:
    ...
```

### 5.5 prompt usage

`Previous Episode Continuity` 아래에 Relationship Memory 섹션을 추가한다.

```text
- relationship_delta:
  - hero_gold_bond_muscle:villain_debt_titan = 경계 심화
- HARD RULE: if these characters appear, their dialogue tone must reflect this relationship_delta.
```

## 6. 상세 설계 D — Continuity Observability

### 6.1 목표

연속성 입력/출력/품질 결과를 DB와 log에서 추적 가능하게 한다.

### 6.2 신규 payload

`episode_assets`에 바로 컬럼 추가가 어려우면 우선 `script_json._continuity_quality`에 저장한다.

```json
"_continuity_quality": {
  "version": "continuity-quality-1",
  "strict_enabled": false,
  "score": 65,
  "status": "degraded",
  "warnings": ["P1-P2 weak hook payoff"],
  "previous_source_episode_id": "ICG-2026-06-14-001"
}
```

중기 DB migration 후보:

- `episode_assets.continuity_quality_json jsonb`
- `episode_assets.continuity_degraded boolean default false`
- `episode_assets.previous_episode_id text`

### 6.3 로그 규칙

STEP_4 완료 전에 아래 한 줄을 반드시 출력한다.

```text
[StoryContinuity] previous=ICG-... score=65 status=degraded strict=false warnings=1
```

## 7. 상세 설계 E — Multi Episode Memory Window

### 7.1 목표

직전 1회차뿐 아니라 최근 N회차의 unresolved thread를 압축해 장기 떡밥이 사라지지 않도록 한다.

### 7.2 함수 변경

현재:

```python
load_previous_continuity(episode_date) -> dict | None
```

추가:

```python
load_continuity_window(episode_date: str, limit: int = 3) -> dict:
    return {
        "primary_previous": {...},
        "recent_threads": [...],
        "recurring_villains": [...],
        "relationship_memory": {...},
    }
```

### 7.3 prompt 압축 규칙

- primary previous는 상세 노출
- 2~3회차 이전 thread는 최대 3개만 `Long-running Threads`로 노출
- 오늘 evidence와 무관한 thread는 `background only`로 표시

## 8. 상세 설계 F — Continuity Repair Retry

### 8.1 목표

strict gate 실패 시 즉시 실패하기 전에 한 번 재생성을 시도해 운영 안정성을 높인다.

### 8.2 변경 대상

- `engine/narrative/claude_client.py`
- `scripts/run_market.py`
- `engine/narrative/story_quality.py`

### 8.3 retry flow

1. 첫 생성 후 `validate_story_continuity(strict=False)` 실행.
2. score가 threshold 미만이면 repair prompt를 추가한다.
3. Claude 재호출 1회.
4. 재검증.
5. 그래도 실패하면 strict mode에서는 fail, non-strict에서는 degraded 저장.

repair instruction 예시:

```text
Your previous draft failed continuity: P1-P2 did not acknowledge previous_next_hook.
Revise only the narrative content so Panel 1 or 2 explicitly pays off: "...".
Do not change market facts or battle_result.outcome.
```

## 9. 구현 우선순위

### P0 — 다음 개발 착수 권장

1. Continuity Semantic Score v1 추가.
2. `script_json._continuity_quality` 저장.
3. Relationship Memory를 prompt에 노출.

### P1 — strict 운영 전 필수

1. Arc Pivot Contract 추가.
2. Multi Episode Memory Window 추가.
3. Continuity Repair Retry 1회 추가.

### P2 — DB/운영 고도화

1. `continuity_quality_json`, `continuity_degraded`, `previous_episode_id` migration.
2. dashboard/report에서 continuity score trend 노출.
3. 운영 preset `CONTINUITY_STRICT=true`가 context/planner/arc/strict를 함께 켜도록 정리.

## 10. 권장 PR 분할

1. `feat: add continuity semantic scoring`
   - `continuity_score.py`, tests, story_quality integration
2. `feat: persist continuity quality metadata`
   - `_continuity_quality` payload 저장, logs, tests
3. `feat: add relationship memory to continuity prompts`
   - prompt section, story_state update helper, tests
4. `feat: detect arc pivots in continuity context`
   - `detect_arc_pivot`, context pack, planner P2 rule, tests
5. `feat: load continuity memory window`
   - multi episode loader, prompt compression, tests
6. `feat: retry narrative generation on continuity failure`
   - repair prompt/retry, strict/non-strict behavior tests
