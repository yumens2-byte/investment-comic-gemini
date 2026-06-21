# run_market all-true Action 에러 분석 및 상세 설계

작성일: 2026-06-16

## 1. 목적

GitHub Actions에서 `run_market` workflow를 수동 실행할 때 continuity/arc/story 관련 입력을 전부 `true`로 선택하면, 기존 shadow-run 성격의 기능들이 동시에 strict 운영 모드로 전환된다. 이 문서는 해당 all-true 실행 에러를 분석하고, 재현/분류/복구/하드닝 상세 설계를 정의한다.

현재 사용자가 공유한 정보에는 실제 Actions log 원문이 포함되어 있지 않으므로, 이 문서는 코드 경로 기준으로 가능한 실패 지점을 분리한다. 실제 log가 확보되면 아래 분류표의 Error Signature에 맞춰 원인 확정이 가능하다.

## 2. all-true 실행 시 활성화되는 주요 경로

수동 실행에서 아래 플래그를 모두 `true`로 켜면 다음 기능이 동시에 작동한다.

| 입력/Env | 영향 |
|---|---|
| `SCENARIO_V2_ENABLED=true` | 캐릭터/게스트/story_state 흐름 활성화 |
| `EPISODE_TYPE_V3_ENABLED=true` | episode type v3 판정 활성화 |
| `ARC_STATE_V3_ENABLED=true` | arc_state 로드/저장 및 arc_context 기반 분기 활성화 |
| `NARRATIVE_CONTEXT_ENABLED=true` | previous continuity, market context pack 생성 및 품질 게이트 활성화 |
| `STORY_PLANNER_ENABLED=true` | StoryBeatPlan 생성 및 narrative 단계 품질 게이트 활성화 |
| `CONTINUITY_STRICT_ENABLED=true` | generated script가 previous hook을 충분히 회수하지 못하면 strict fail |
| Phase 2.3 flags 전부 true | belief/pair/crowd/signature/emergence 경로가 동시에 활성화 |

즉, all-true는 단순 기능 확인이 아니라 “가장 엄격한 통합 운영 모드”이며, 하나의 하위 컨텍스트라도 누락되면 narrative 단계에서 실패할 수 있다.

## 3. 가능한 에러 분류

### 3.1 A유형 — analysis stage에서 context pack 생성 실패 후 narrative quality gate 실패

#### Error Signature

```text
NARRATIVE_CONTEXT_ENABLED=true 이지만 analysis_ctx_json에 narrative_context_pack이 없습니다.
```

또는

```text
STORY_PLANNER_ENABLED=true 이지만 analysis_ctx_json에 story_beat_plan이 없습니다.
```

#### 원인

`step_analysis()`의 narrative context 생성 블록은 내부 예외를 warning으로 처리하고 파이프라인을 계속 진행한다. 하지만 이후 `step_narrative()`의 `_validate_narrative_quality_inputs()`는 `NARRATIVE_CONTEXT_ENABLED`/`STORY_PLANNER_ENABLED`가 true일 때 해당 객체가 없으면 fail-fast한다.

#### 상세 설계

1. context 생성 실패를 warning으로만 묻지 말고 `ctx["narrative_context_error"]`에 error class/message를 저장한다.
2. quality gate 실패 메시지에 `narrative_context_error`를 포함한다.
3. all-true/strict 모드에서는 analysis 단계에서 바로 fail-fast하고, shadow 모드에서는 degraded로 저장한다.

권장 payload:

```json
"narrative_context_error": {
  "stage": "STEP_3",
  "feature": "narrative_context_pack",
  "error_type": "...",
  "error_message": "...",
  "strict_mode": true
}
```

### 3.2 B유형 — strict continuity gate가 정상적으로 실패시킨 케이스

#### Error Signature

```text
StoryContinuityError: Continuity score ... below threshold 70
```

#### 원인

`CONTINUITY_STRICT_ENABLED=true`는 생성 결과가 이전 hook/thread를 P1~P2에서 회수하지 못하면 실패시키는 운영 모드다. 이 경우 에러는 코드 버그라기보다 “strict gate가 의도대로 차단한 결과”일 수 있다.

#### 상세 설계

1. strict gate 실패를 곧바로 전체 실패로 끝내지 않고 repair retry 1회를 실행한다.
2. retry prompt는 시장 데이터/전투 결과를 바꾸지 않고 P1~P2 continuity만 보정하도록 제한한다.
3. retry 후에도 score < 70이면 fail한다.
4. non-strict에서는 `_continuity_quality.status=degraded`로 저장하고 publish gate에서 차단 여부를 결정한다.

Repair prompt 예시:

```text
Previous draft failed continuity score: 35/100.
Missing: opening_hook_payoff, unresolved_thread_resolution.
Revise Panel 1 or 2 so it explicitly acknowledges previous_next_hook: "...".
Do not change market facts, supplied evidence, or battle_result.outcome.
Return the full EpisodeScript JSON only.
```

### 3.3 C유형 — all-true지만 stage 재실행 조합이 일치하지 않는 케이스

#### Error Signature

```text
analysis_ctx_json에 narrative_context_pack이 없습니다. analysis stage를 같은 flag로 재실행하세요.
```

#### 원인

`stage=narrative` 또는 `stage=persist/image`만 재실행하면서 이번 실행에서는 all-true를 선택했지만, DB에 저장된 `analysis_ctx_json`은 이전에 일부 flag가 false였던 상태일 수 있다.

#### 상세 설계

1. `analysis_ctx_json`에 `feature_flags_snapshot`을 저장한다.
2. narrative 단계에서 현재 env snapshot과 DB snapshot을 비교한다.
3. mismatch가 있으면 “analysis stage부터 재실행 필요”라고 명확히 실패한다.
4. `stage=all`일 때는 항상 현재 flag snapshot으로 ctx를 다시 저장한다.

권장 snapshot:

```json
"feature_flags_snapshot": {
  "NARRATIVE_CONTEXT_ENABLED": true,
  "STORY_PLANNER_ENABLED": true,
  "CONTINUITY_STRICT_ENABLED": true,
  "ARC_STATE_V3_ENABLED": true,
  "EPISODE_TYPE_V3_ENABLED": true
}
```

### 3.4 D유형 — external dependency / secret / DB schema 누락

#### Error Signature 예시

```text
ANTHROPIC_API_KEY missing
SUPABASE_URL missing
column ... does not exist
PostgREST filter method ... failed
```

#### 원인

all-true는 평소 비활성화된 DB/API 경로를 모두 밟기 때문에, 일부 secret이나 schema/migration 누락이 표면화될 수 있다.

#### 상세 설계

1. workflow 초반에 strict preflight step을 추가한다.
2. 필요한 secrets/env/schema 접근을 dry check한다.
3. 실패 시 STEP_0에서 중단하여 Claude 호출 비용과 중간 산출물 오염을 방지한다.

Preflight 체크 대상:

- `ANTHROPIC_API_KEY`
- `SUPABASE_URL`, `SUPABASE_KEY`, `SUPABASE_SCHEMA`
- `episode_assets` select 권한
- `daily_analysis` select/update 권한
- `arc_state` select/upsert 권한

### 3.5 E유형 — all-true 조합 자체가 운영적으로 너무 강한 케이스

#### 원인

all-true는 다음 세 성격을 동시에 켠다.

1. 기능 활성화
2. strict 검증
3. experimental context 확장

따라서 파일럿 테스트에서는 “기능 ON”과 “strict 차단”을 분리해야 한다.

#### 상세 설계

운영 preset을 3단계로 나눈다.

| Preset | 목적 | 주요 설정 |
|---|---|---|
| `continuity_shadow` | 산출물 생성은 통과, 점수만 수집 | context/planner/arc=true, strict=false |
| `continuity_warn` | publish 전 warning 확인 | context/planner/arc=true, strict=false, publish gate optional |
| `continuity_strict` | 운영 차단 | context/planner/arc=true, strict=true, repair retry=true |

## 4. 상세 설계 — 진단 기능 추가

### 4.1 신규 함수: flag snapshot

대상 파일:

- `scripts/run_market.py`
- `tests/test_run_market_quality.py`

```python
_CONTINUITY_FLAG_NAMES = [
    "NARRATIVE_CONTEXT_ENABLED",
    "STORY_PLANNER_ENABLED",
    "CONTINUITY_STRICT_ENABLED",
    "ARC_STATE_V3_ENABLED",
    "EPISODE_TYPE_V3_ENABLED",
]


def _feature_flag_snapshot() -> dict[str, bool]:
    return {name: _env_flag_enabled(name) for name in _CONTINUITY_FLAG_NAMES}
```

저장 위치:

```python
ctx["feature_flags_snapshot"] = _feature_flag_snapshot()
```

### 4.2 신규 함수: context error recorder

```python
def _record_context_error(ctx: dict, feature: str, exc: Exception, *, strict: bool) -> None:
    ctx.setdefault("context_errors", []).append({
        "feature": feature,
        "error_type": exc.__class__.__name__,
        "error_message": str(exc),
        "strict": strict,
    })
```

### 4.3 quality gate 메시지 개선

현재 메시지:

```text
narrative_context_pack이 없습니다.
```

개선 메시지:

```text
NARRATIVE_CONTEXT_ENABLED=true but narrative_context_pack is missing.
flags={...}
context_errors=[...]
If stage != all, rerun stage=analysis with the same flags.
```

## 5. 상세 설계 — all-true 파일럿 테스트 절차

### 5.1 사전 검증

```bash
python -m py_compile scripts/run_market.py engine/narrative/continuity.py engine/narrative/continuity_score.py engine/narrative/story_quality.py engine/narrative/story_planner.py
python -m ruff check scripts/run_market.py engine/narrative/continuity.py engine/narrative/continuity_score.py engine/narrative/story_quality.py engine/narrative/story_planner.py
pytest -q tests/test_workflow_run_market.py tests/test_run_market_quality.py tests/test_continuity.py tests/test_continuity_score.py tests/test_story_quality.py tests/test_story_planner.py
```

### 5.2 shadow pilot

권장 첫 실행:

```text
NARRATIVE_CONTEXT_ENABLED=true
STORY_PLANNER_ENABLED=true
ARC_STATE_V3_ENABLED=true
EPISODE_TYPE_V3_ENABLED=true
CONTINUITY_STRICT_ENABLED=false
```

성공 조건:

- STEP_3에서 previous/context/plan 생성 로그 확인
- STEP_4에서 `[StoryContinuity] previous=... score=... status=... strict=false` 확인
- `_continuity_quality`가 output JSON과 `script_json`에 저장됨

### 5.3 strict pilot

shadow에서 3회 이상 `score>=70`이면 strict를 켠다.

```text
CONTINUITY_STRICT_ENABLED=true
```

성공 조건:

- score >= 70이면 통과
- score < 70이면 repair retry 1회 후 재검증
- retry 후에도 실패하면 expected fail로 분류하고 `_continuity_quality`를 확인

### 5.4 all-true full pilot

마지막 단계에서만 Phase 2.3 플래그까지 전부 true로 켠다.

성공 조건:

- STEP_0 preflight 통과
- STEP_3 context pack/story plan/arc pivot 생성 또는 명시적 no-op 로그
- STEP_4 continuity score 저장
- STEP_5 persist payload에 `_continuity_quality` 포함
- 전체 pytest 전수테스트 통과

## 6. 구현 우선순위

### P0 — 에러 원인 확정/재발 방지

1. `feature_flags_snapshot` 저장.
2. `context_errors` 기록.
3. quality gate error message 개선.
4. workflow preflight 로그에 all-true 위험 경고 추가.

### P1 — strict 안정화

1. continuity repair retry 1회.
2. `_continuity_quality`를 strict fail path에서도 artifact로 남기는 구조.
3. publish gate와 continuity degraded 상태 연동.

### P2 — 운영 preset

1. `continuity_mode` input 추가: `off/shadow/warn/strict`.
2. 개별 true/false보다 preset 우선 적용.
3. all-true 직접 운영 대신 preset 기반 rollout로 전환.

## 7. 예상 PR 분할

1. `fix: improve all-true run_market diagnostics`
   - flag snapshot, context error recorder, quality gate 메시지 개선, tests
2. `feat: add continuity repair retry`
   - strict 실패 시 1회 repair generation, tests
3. `feat: add run_market continuity mode preset`
   - workflow input/preset/env normalization, tests
4. `feat: persist continuity failure artifacts`
   - strict fail에서도 quality artifact 저장/업로드, tests

## 8. 임시 운영 권장안

실제 에러 log 원문이 확인되기 전까지는 다음 순서로 실행하는 것이 안전하다.

1. `stage=all`, continuity/arc/context/planner true, `continuity_strict=false`.
2. score와 warnings를 확인한다.
3. score가 안정적으로 70 이상이면 `continuity_strict=true`를 켠다.
4. Phase 2.3 부가 플래그는 한 번에 전부 true로 켜지 말고 `narrative_depth -> pair_tension -> crowd_modifier -> signature/emergence` 순서로 켠다.
5. all-true는 최종 회귀 테스트용으로만 사용한다.

## 9. 2026-06-16 strict continuity repair 구현 결과

### 9.1 확정한 런타임 실패 경로

`CONTINUITY_STRICT_ENABLED=true`에서 Claude 초안이 이전 에피소드 hook/thread를 P1~P2에서 충분히 회수하지 못하면 `StoryContinuityError`가 발생하며 STEP 4가 즉시 실패한다. 배포 자체는 성공해도 `run_market` 수동 실행 또는 all-true 파일럿에서 중단될 수 있는 경로다.

### 9.2 적용한 상세 설계

1. STEP 4 최초 초안에 대해 기존 continuity quality payload를 먼저 산출한다.
2. strict continuity gate가 실패하면 전체 파이프라인을 즉시 종료하지 않고 1회 한정 repair retry를 수행한다.
3. repair prompt는 이전 실패 점수, missing requirement, warning, previous source episode id를 포함한다.
4. repair prompt는 시장 사실, `event_type`, `battle_result`, `scenario_type`, 캐릭터 ID, 8패널 구조를 바꾸지 말고 P1~P2 continuity payoff만 보정하도록 제한한다.
5. repair 결과도 동일한 strict gate로 재검증한다. 재검증 실패 시에는 기존처럼 실패시켜 publish 오염을 막는다.
6. 통과한 repair 결과에는 `_continuity_quality.repair_attempted=true`와 `_continuity_quality.repair_reason`을 남겨 운영 로그/DB에서 원인 추적이 가능하게 한다.

### 9.3 회귀 테스트 범위

- repair prompt가 시장 사실 보존 계약과 누락 requirement를 포함하는지 검증한다.
- STEP 4 strict continuity failure에서 Claude generation이 정확히 한 번 추가 호출되는지 검증한다.
- repair 호출에 `continuity_repair_instructions`가 전달되는지 검증한다.
- repair 성공 산출물이 최종 script로 저장되고 `_continuity_quality.repair_attempted=true`가 남는지 검증한다.

## 10. 2026-06-16 run_market 재실패 로그 반영 보강

### 10.1 재현된 실패

운영 로그에서 all-true 설정으로 `stage=narrative`를 단독 재실행했을 때 STEP 4 최초 Claude 생성은 성공했지만, continuity 점수가 35점으로 `opening_hook_payoff`, `unresolved_thread_resolution` 요구사항을 만족하지 못해 `StoryContinuityError`가 발생했고 프로세스가 exit code 1로 종료됐다.

### 10.2 추가 보강 설계

1. strict continuity 실패 시 repair retry를 먼저 수행한다.
2. repair 결과도 strict 기준을 통과하지 못하면 기본 운영값에서는 narrative 산출물을 `degraded` 메타데이터와 함께 계속 저장한다.
3. 반드시 STEP 4를 중단해야 하는 운영에서는 `CONTINUITY_STRICT_HARD_FAIL=true`를 별도로 설정한다.
4. repair 실패 후 계속 진행된 산출물에는 `_continuity_quality.repair_failed=true`, `_continuity_quality.repair_failure_reason`, `_continuity_quality.hard_fail_suppressed=true`를 남긴다.
5. workflow 경고 문구도 “즉시 중단”이 아니라 “1회 repair 후 hard-fail 옵션에 따라 중단”으로 수정한다.
