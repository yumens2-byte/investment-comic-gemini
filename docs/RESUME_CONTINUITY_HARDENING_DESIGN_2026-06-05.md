# Resume Episode / Story Continuity Hardening 상세 설계

작성일: 2026-06-05

## 1. 목적

현재 ICG 파이프라인에는 에피소드 재개와 스토리 연속성을 위한 기본 구조가 존재하지만, 운영 플래그, 날짜 조회 방식, row 식별 기준, `--force` 제어 부재 때문에 실제 결과물이 단편적으로 보이거나 이미 조립된 에피소드를 의도치 않게 재조립할 수 있다.

이 문서는 개발 착수 전에 원인점을 명확히 분리하고, 구현 단위별 상세 설계를 제공한다.

## 2. 현재 동작 요약

### 2.1 Resume Episode

`resume_episode.yml`은 STEP 7 PIL 조립을 수행한다. 수동 실행 입력으로 `episode_id`와 `force`를 받으며, `force` 설명은 “기존 assembled 상태 덮어쓰기”이다.

`scripts/run_resume.py`는 다음 순서로 동작한다.

1. 명시적 `--episode`가 없으면 최신 에피소드를 자동 선택한다.
2. 자동 선택 우선순위는 `image_generated -> assembled -> narrative_done`이다.
3. 선택한 row를 `episode_date + episode_no`로 조회한다.
4. 조회 실패 시 같은 날짜 최신 row로 fallback한다.
5. `script_json`, `dialog_edits_json`, `panels_json`을 기반으로 PIL 슬라이드를 생성한다.
6. `episode_date + event_type` 기준으로 `slides_json`, `status=assembled`, `slides_run_id`를 patch한다.

### 2.2 Story continuity

현재 연속성 장치는 다음과 같다.

| 장치 | 저장 위치 | 주요 역할 | 현재 한계 |
|---|---|---|---|
| `analysis_ctx_json` | `daily_analysis` | stage 분리 실행 시 analysis context 복원 | 날짜 단위 복원용이며 이전 회차 요약은 아님 |
| `narrative_script_json` | `daily_analysis` | persist/image stage에서 script 복원 | 이전 회차 memory가 아니라 현재 회차 script cache |
| `story_state_json` | `daily_analysis` | 게스트/캐릭터 상태, arc episode 기억 | 정확히 전날만 조회, `SCENARIO_V2_ENABLED` 의존 |
| `arc_state` | `arc_state` 단일 row | active villain, arc day, tension, open hook 유지 | `ARC_STATE_V3_ENABLED`가 workflow에서 설정되지 않음 |
| `narrative_context_pack` | `analysis_ctx_json` 내부 | 오늘의 시장 근거를 Claude에 주입 | previous episode summary/hook 미포함 |

## 3. 명확한 원인점

### 원인 1. `force` 옵션이 실제로 사용되지 않는다

`run_resume.py`는 `--force`를 argparse로 정의하지만, 이후 assembled 상태 보호나 재조립 허용 조건에서 사용하지 않는다. 따라서 `force=false`와 `force=true`의 실제 실행 결과가 동일하다.

영향:

- 이미 `assembled`인 에피소드가 자동 선택되어 재조립될 수 있다.
- artifact 다운로드 실패 또는 이미지 파일 부재 시 text-card fallback 슬라이드로 다시 조립되고, 새 `slides_run_id`로 DB가 갱신될 수 있다.
- 운영자가 “force=false면 기존 assembled 보호”라고 기대하면 실제 동작과 불일치한다.

### 원인 2. 자동 선택 범위가 너무 넓다

자동 선택 우선순위에 `assembled`와 `narrative_done`이 포함되어 있다.

영향:

- `assembled`는 재조립 대상이 아니라 기본적으로 보호 대상이어야 한다.
- `narrative_done`은 아직 이미지 생성이 끝나지 않았을 수 있으므로, resume이 이를 조립하면 전체 text-card fallback이 될 수 있다.

### 원인 3. row 조회 기준과 patch 기준이 다르다

`run_resume.py`는 row 로드 시 `episode_date + episode_no`를 사용하지만, 저장 시 `asset_patch(episode_date, event_type, ...)`를 사용한다. `asset_writer.patch()`도 `episode_date + event_type`만 기준으로 업데이트한다.

영향:

- 같은 날짜에 동일 `event_type` row가 여러 개 있거나 재실행 이력이 있으면 다른 row를 갱신할 수 있다.
- `episode_id` 기준 운영과 `(episode_date,event_type)` 기준 persistence가 충돌한다.

### 원인 4. `ARC_STATE_V3_ENABLED`가 GitHub Actions env에 연결되어 있지 않다

`run_market.py`는 arc state load/save 모두 `ARC_STATE_V3_ENABLED=true`일 때만 실행한다. 그러나 `run_market.yml`에는 `EPISODE_TYPE_V3_ENABLED`만 있고, `ARC_STATE_V3_ENABLED` 설정이 없다.

영향:

- `episode_type_v3=true`여도 장기 아크 상태가 저장/복원되지 않을 수 있다.
- `arc_context.open_hook`, `last_outcome`, `arc_day`, `arc_tension`이 이전 회차 기반으로 강화되지 않는다.
- 결과적으로 각 회차가 오늘 시장 데이터 중심의 단편처럼 보인다.

### 원인 5. `story_state_json`은 정확히 전날만 조회한다

`load_story_state(episode_date)`는 `episode_date - 1일`의 `daily_analysis.story_state_json`만 조회한다.

영향:

- 주말, 휴장일, major gate skip, 실패한 날짜가 사이에 있으면 story state가 초기값으로 돌아간다.
- 월요일 에피소드가 금요일 에피소드를 자연스럽게 이어받지 못할 수 있다.

### 원인 6. 이전 에피소드의 “서사 요약”이 Claude 프롬프트에 강하게 주입되지 않는다

`narrative_context_pack`은 `delta`, `battle_result`, `event_type`, `scenario_type`, `ending_tone`, `arc_context`, optional news/event/sector 정보를 기반으로 생성된다. 반환값은 시장 근거와 factual guardrail 중심이다.

영향:

- 직전 에피소드 제목, 마지막 장면, next hook, unresolved thread가 prompt contract로 들어가지 않는다.
- Claude가 매번 오늘 시장 지표만 보고 새로운 8컷을 만들 가능성이 커진다.

### 원인 7. 상태 전이 정책과 실제 patch 동작이 불일치한다

`asset_writer.py`에는 state machine 주석과 transition table이 있지만, 실제 `patch()`는 상태 전이 검증 없이 update한다.

영향:

- `assembled -> assembled` 같은 재조립이 명시적 audit 없이 발생한다.
- `image_generated -> assembled` 외의 우회 전이가 운영에서 숨겨질 수 있다.

## 4. 설계 목표

### 4.1 Resume hardening 목표

1. `force=false`에서는 기존 `assembled`를 절대 덮어쓰지 않는다.
2. 자동 선택은 기본적으로 `image_generated`만 대상으로 한다.
3. `narrative_done`은 명시적 개발/복구 모드가 아니면 조립하지 않는다.
4. patch 기준을 `episode_date + episode_no` 또는 `episode_id`로 통일한다.
5. `published` 상태는 기본적으로 재조립 불가로 보호한다.
6. text-card fallback 조립 비율이 높으면 명시적으로 degrade 상태를 기록한다.

### 4.2 Continuity hardening 목표

1. `arc_state`가 운영 workflow에서 실제로 켜질 수 있도록 env를 연결한다.
2. `story_state_json`은 “전날”이 아니라 “가장 최근 이전 저장 상태”를 조회한다.
3. 이전 에피소드 요약과 hook을 별도 continuity bundle로 저장한다.
4. 다음 에피소드의 `narrative_context_pack`에 `previous_episode` 블록을 추가한다.
5. story planner는 이전 hook을 panel 1~2에서 회수하도록 contract를 갖는다.
6. 각 실행의 continuity input/output을 DB와 log에서 관측 가능하게 한다.

## 5. 상세 설계

## 5.1 Resume Episode 보호 설계

### 5.1.1 자동 선택 정책 변경

현재:

```text
image_generated -> assembled -> narrative_done
```

변경:

```text
기본 자동 선택: image_generated only
명시적 --include-assembled 또는 --force + --episode: assembled 허용
명시적 --allow-narrative-only: narrative_done 허용
```

권장 CLI:

```bash
python -m scripts.run_resume
python -m scripts.run_resume --episode ICG-YYYY-MM-DD-NNN
python -m scripts.run_resume --episode ICG-YYYY-MM-DD-NNN --force
python -m scripts.run_resume --episode ICG-YYYY-MM-DD-NNN --allow-narrative-only
```

### 5.1.2 상태별 처리 정책

| 현재 status | `--force=false` | `--force=true` | 비고 |
|---|---|---|---|
| `image_generated` | 조립 허용 | 조립 허용 | 정상 경로 |
| `assembled` | 중단 | 재조립 허용 | 기존 slides 덮어쓰기 |
| `published` | 중단 | 중단 기본값 | 별도 `FORCE_REASSEMBLE_PUBLISHED` 없으면 금지 |
| `narrative_done` | 중단 | 중단 | `--allow-narrative-only`가 있을 때만 허용 |
| `failed`/`aborted` | 중단 | 중단 | 별도 복구 flow 필요 |

### 5.1.3 코드 변경안

대상 파일:

- `scripts/run_resume.py`
- `engine/persist/asset_writer.py`
- `.github/workflows/resume_episode.yml`

신규/변경 함수:

```python
def _latest_episode_id(*, include_assembled: bool = False, allow_narrative_only: bool = False) -> str | None:
    statuses = ["image_generated"]
    if include_assembled:
        statuses.append("assembled")
    if allow_narrative_only:
        statuses.append("narrative_done")
    ...
```

```python
def patch_by_episode(episode_date: str, episode_no: int, data: dict) -> None:
    icg_table("episode_assets").update(data).eq("episode_date", episode_date).eq("episode_no", episode_no).execute()
```

```python
def guard_resume_status(status: str, *, force: bool, allow_narrative_only: bool) -> None:
    if status == "image_generated":
        return
    if status == "assembled" and force:
        return
    if status == "narrative_done" and allow_narrative_only:
        return
    raise RuntimeError(...)
```

### 5.1.4 DB 저장 정책

현재 patch payload:

```json
{
  "slides_json": [...],
  "dialog_edited": true/false,
  "status": "assembled",
  "slides_run_id": "..."
}
```

추가 권장 필드:

```json
{
  "assembly_degraded": false,
  "assembly_fallback_count": 0,
  "assembly_source_status": "image_generated",
  "assembly_forced": false
}
```

마이그레이션이 부담되면 우선 `run_logs`와 `slides_json` 내부 메타로 기록하고, 이후 컬럼 추가를 진행한다.

## 5.2 Arc state workflow 연결 설계

### 5.2.1 문제

`run_market.py`는 `ARC_STATE_V3_ENABLED`를 확인하지만 workflow env에 해당 키가 없다.

### 5.2.2 변경안

`.github/workflows/run_market.yml` input 추가:

```yaml
arc_state_v3:
  description: 'Arc State v3 continuity 활성화 (true/false/auto)'
  required: false
  default: 'auto'
```

Env 추가:

```yaml
ARC_STATE_V3_ENABLED: ${{ (inputs.arc_state_v3 != '' && inputs.arc_state_v3 != 'auto') && inputs.arc_state_v3 || vars.ARC_STATE_V3_ENABLED || 'false' }}
```

운영 권장:

- Repository Variable `ARC_STATE_V3_ENABLED=true`
- `EPISODE_TYPE_V3_ENABLED=true`
- `SCENARIO_V2_ENABLED=true`

### 5.2.3 로그 보강

STEP 4 전 flag 출력에 다음을 추가한다.

```bash
echo "  ARC_STATE_V3_ENABLED            = $(flag_label "$ARC_STATE_V3_ENABLED")"
```

## 5.3 Story state 최근 이전 상태 조회 설계

### 5.3.1 현재 문제

`load_story_state()`가 정확히 `episode_date - 1 day`만 조회한다.

### 5.3.2 변경안

새 조회 정책:

1. `analysis_date < episode_date`
2. `story_state_json is not null`
3. `analysis_date desc limit 1`

Supabase query 예시:

```python
resp = (
    icg_table("daily_analysis")
    .select("analysis_date, story_state_json")
    .lt("analysis_date", episode_date)
    .not_.is_("story_state_json", "null")
    .order("analysis_date", desc=True)
    .limit(1)
    .execute()
)
```

Supabase Python 문법 호환성이 불확실하면 다음 fallback을 사용한다.

```python
resp = (
    icg_table("daily_analysis")
    .select("analysis_date, story_state_json")
    .lt("analysis_date", episode_date)
    .order("analysis_date", desc=True)
    .limit(10)
    .execute()
)
for row in resp.data or []:
    if row.get("story_state_json"):
        return row["story_state_json"]
```

### 5.3.3 추가 메타

로드 시 다음 로그를 남긴다.

```text
[StoryStateManager] 이전 story_state 로드 source_date=YYYY-MM-DD target_date=YYYY-MM-DD arc=...
```

`ctx`에도 다음을 넣는다.

```json
"story_state_source_date": "YYYY-MM-DD"
```

## 5.4 Continuity bundle 설계

### 5.4.1 목적

`story_state_json`과 `arc_state`는 상태값 중심이다. 실제 서사 연결감을 만들려면 “직전 회차에서 무슨 일이 있었고, 오늘 무엇을 회수해야 하는지”를 Claude가 명확히 알아야 한다.

### 5.4.2 데이터 구조

권장 필드명:

- `episode_assets.continuity_json`
- 또는 `daily_analysis.continuity_json`

초기 구현은 migration 부담을 줄이기 위해 `episode_assets.script_json`에서 추출하고, `daily_analysis.analysis_ctx_json.previous_episode`에 저장하는 방식으로 시작할 수 있다. 이후 별도 컬럼화한다.

권장 JSON schema:

```json
{
  "version": "continuity-1",
  "source_episode_id": "ICG-2026-06-06-002",
  "source_date": "2026-06-06",
  "title": "...",
  "logline": "...",
  "final_panel_summary": "...",
  "next_hook": "...",
  "outcome": "HERO_DEFEAT",
  "event_type": "BATTLE",
  "scenario_type": "ONE_VS_ONE",
  "hero_ids": ["..."],
  "villain_id": "...",
  "unresolved_threads": ["..."],
  "must_continue_from": "..."
}
```

### 5.4.3 생성 시점

`step_persist()` 이후 또는 story/arc state 저장 직후 생성한다.

입력:

- `episode_id`
- `episode_date`
- `ctx`
- `script_dict`

생성 함수:

```python
def build_continuity_bundle(episode_id: str, episode_date: str, ctx: dict, script_dict: dict) -> dict:
    panels = script_dict.get("panels", [])
    final_panel = panels[-1] if panels else {}
    return {
        "version": "continuity-1",
        "source_episode_id": episode_id,
        "source_date": episode_date,
        "title": script_dict.get("title", ""),
        "logline": script_dict.get("logline", ""),
        "final_panel_summary": final_panel.get("narration") or final_panel.get("key_text") or "",
        "next_hook": script_dict.get("next_hook") or "",
        "outcome": (ctx.get("battle_result") or {}).get("outcome"),
        "event_type": ctx.get("event_type"),
        "scenario_type": ctx.get("scenario_type"),
        "hero_ids": ctx.get("heroes") or [ctx.get("hero_id")],
        "villain_id": ctx.get("villain_id"),
        "unresolved_threads": _derive_threads(script_dict, ctx),
        "must_continue_from": _derive_must_continue(final_panel, script_dict),
    }
```

### 5.4.4 로드 시점

`step_analysis()`에서 context pack 생성 전에 “가장 최근 이전 continuity”를 조회한다.

조회 기준:

1. `episode_date < current_episode_date`
2. `status in ('published', 'assembled')` 우선
3. `episode_date desc, episode_no desc limit 1`
4. `continuity_json`이 없으면 `script_json`에서 best-effort 추출

## 5.5 Narrative Context Pack 확장 설계

### 5.5.1 함수 시그니처 변경

현재:

```python
def build_narrative_context_pack(..., arc_context=None, news_items=None, economic_events=None, sector_heatmap=None)
```

변경:

```python
def build_narrative_context_pack(
    ...,
    arc_context: dict | None = None,
    previous_episode: dict | None = None,
    news_items: list[dict] | None = None,
    economic_events: list[dict] | None = None,
    sector_heatmap: dict | None = None,
) -> dict:
```

반환값 추가:

```json
{
  "previous_episode": {
    "source_episode_id": "...",
    "title": "...",
    "logline": "...",
    "final_panel_summary": "...",
    "next_hook": "...",
    "unresolved_threads": [...],
    "must_continue_from": "..."
  },
  "continuity_directives": [
    "Panel 1-2 must acknowledge or pay off previous_episode.next_hook when present.",
    "Do not reset character relationship state without explanation.",
    "Continue unresolved_threads unless today's market evidence makes a clear pivot necessary."
  ]
}
```

### 5.5.2 Prompt fallback 변경

`_append_narrative_context_fallback()`에 다음 section을 추가한다.

```text
### Previous Episode Continuity
- source_episode_id: ...
- title: ...
- previous_final_panel: ...
- previous_next_hook: ...
- unresolved_threads: ...
- must_continue_from: ...

### Continuity Directives
- Panel 1-2 must acknowledge previous_next_hook when present.
- Preserve character emotional continuity.
```

## 5.6 Story planner 확장 설계

### 5.6.1 입력 변경

현재 `build_story_beat_plan()`은 `narrative_context_pack`, hero/villain, battle_result, scenario_type을 기반으로 beat plan을 만든다.

변경:

- context pack의 `previous_episode`를 읽는다.
- `previous_episode.next_hook`이 있으면 panel 1 또는 2 beat에 `continuity_payoff`를 추가한다.

### 5.6.2 beat schema 확장

기존 beat dict에 다음 key를 추가한다.

```json
{
  "continuity_payoff": "previous next_hook 회수 지시",
  "must_reference_previous": true
}
```

Pydantic model이 있다면 optional field로 추가한다.

### 5.6.3 planner guardrail

추가 forbidden/directive:

```text
Do not start a completely new conflict in panel 1 if previous_episode.next_hook exists.
Panel 1 must show the consequence of previous_episode.final_panel_summary or next_hook.
```

## 5.7 State machine / asset writer 정합성 설계

### 5.7.1 `patch_by_episode` 추가

`asset_writer.patch()`는 기존 호환을 위해 유지한다.

신규:

```python
def patch_by_episode(episode_date: str, episode_no: int, data: dict) -> None:
    ...eq("episode_date", episode_date).eq("episode_no", episode_no)...
```

### 5.7.2 상태 변경 전용 함수 추가

```python
def transition_by_episode(episode_date: str, episode_no: int, target_status: str, data: dict | None = None, *, force: bool = False) -> None:
    row = get_episode_by_no(...)
    current = row["status"]
    if force and current == target_status == "assembled":
        allow with audit log
    else:
        validate_transition(current, target_status)
    patch_by_episode(...)
```

### 5.7.3 Resume에서는 transition 함수 사용

- `image_generated -> assembled`: 정상 transition
- `assembled -> assembled`: `force=true`일 때만 허용
- `narrative_done -> assembled`: 기본 금지, `allow_narrative_only=true`일 때 degraded transition으로 허용 가능

## 6. 구현 단계 계획

### Phase 1. Resume 안전장치

목표: 의도치 않은 assembled overwrite 방지.

변경 파일:

- `scripts/run_resume.py`
- `engine/persist/asset_writer.py`
- `.github/workflows/resume_episode.yml`
- `tests/test_run_resume.py` 또는 신규 테스트 파일

작업:

1. `patch_by_episode()` 추가.
2. `run_resume.py`에서 row status guard 추가.
3. `_latest_episode_id()` 기본 자동 선택을 `image_generated`로 제한.
4. `--allow-narrative-only` 옵션 추가.
5. `--force`가 assembled 재조립에만 작동하도록 구현.
6. workflow input 설명을 실제 정책에 맞게 수정.

테스트:

- assembled + force false -> exit 1
- assembled + force true -> compose 호출 및 patch_by_episode 호출
- image_generated -> 정상 assembled
- narrative_done -> 기본 exit 1
- narrative_done + allow_narrative_only -> 허용 또는 degraded 기록

### Phase 2. Arc state 활성화

목표: 장기 arc memory가 운영에서 실제로 켜지도록 함.

변경 파일:

- `.github/workflows/run_market.yml`
- `tests/test_workflow_run_market.py`

작업:

1. `arc_state_v3` input 추가.
2. `ARC_STATE_V3_ENABLED` env 추가.
3. STEP 4 flag 출력에 추가.
4. workflow test에서 env key 존재 검증.

테스트:

- workflow text에 `ARC_STATE_V3_ENABLED`가 정확히 1회 env 정의되는지 확인.
- `episode_type_v3`와 별도 input으로 동작하는지 확인.

### Phase 3. Story state 최근 이전 상태 조회

목표: 주말/휴장/skip 이후에도 연속성 유지.

변경 파일:

- `engine/character/story_state_manager.py`
- `tests/test_story_state_manager.py` 또는 신규 테스트

작업:

1. 전날 조회를 최근 이전 상태 조회로 변경.
2. source date 로그 추가.
3. 실패 시 기존 default fallback 유지.

테스트:

- 전날 row 없음, 3일 전 row 있음 -> 3일 전 state 반환
- 이전 row는 있으나 `story_state_json` null -> 다음 row 탐색
- 이전 state 없음 -> default 반환

### Phase 4. Continuity bundle 저장/로드

목표: 실제 이전 에피소드 서사 정보를 다음 회차에 전달.

변경 파일:

- 신규 `engine/narrative/continuity.py` 또는 `engine/analysis/continuity_builder.py`
- `scripts/run_market.py`
- `engine/persist/asset_writer.py`
- 테스트 신규

작업:

1. `build_continuity_bundle()` 구현.
2. `load_previous_continuity(episode_date)` 구현.
3. persist 이후 continuity 저장.
4. analysis 단계에서 previous continuity 로드 후 ctx에 저장.

테스트:

- script panels가 있으면 final panel summary 추출
- `next_hook`이 있으면 bundle에 저장
- previous continuity row가 있으면 최신 published/assembled 우선 반환
- continuity_json이 없으면 script_json best-effort fallback

### Phase 5. Context pack / prompt / planner 확장

목표: Claude가 이전 hook을 회수하도록 prompt contract 강화.

변경 파일:

- `engine/analysis/story_context_builder.py`
- `engine/narrative/prompt_tpl.py`
- `engine/narrative/story_planner.py`
- `tests/test_prompt_tpl.py`
- `tests/test_pilot_flow_contract.py`

작업:

1. `build_narrative_context_pack(previous_episode=...)` 파라미터 추가.
2. 반환값에 `previous_episode`, `continuity_directives` 추가.
3. prompt fallback에 Previous Episode Continuity 섹션 추가.
4. story planner가 previous hook을 panel 1~2에 반영.
5. strict validation에서 previous hook 누락 warning 추가 가능.

테스트:

- context pack에 previous_episode가 보존되는지 확인
- Notion template이 outdated여도 prompt fallback에 previous continuity가 append되는지 확인
- story planner panel 1 또는 2에 continuity payoff가 들어가는지 확인

## 7. 수용 기준

### Resume

- `force=false`로 assembled row를 실행하면 DB `slides_run_id`가 바뀌지 않아야 한다.
- `force=true`로 명시 episode를 실행하면 재조립되고 로그에 forced overwrite가 남아야 한다.
- 자동 resume은 `image_generated`만 선택해야 한다.
- `narrative_done` 자동 조립은 발생하지 않아야 한다.

### Continuity

- 월요일 실행 시 금요일 또는 가장 최근 이전 `story_state_json`을 로드해야 한다.
- `ARC_STATE_V3_ENABLED=true` 운영에서 `arc_state.arc_day`가 persist 이후 증가해야 한다.
- 다음 회차 `analysis_ctx_json.narrative_context_pack.previous_episode`가 직전 회차를 가리켜야 한다.
- Claude user prompt에 Previous Episode Continuity 섹션이 포함되어야 한다.
- story beat plan의 panel 1~2 중 하나가 previous hook 회수를 명시해야 한다.

## 8. 우선순위

| 우선순위 | 항목 | 이유 |
|---|---|---|
| P0 | `--force` 실제 적용 | 기존 assembled 보호 실패는 운영 손상 가능성이 큼 |
| P0 | 자동 선택 `image_generated` 제한 | narrative_done/text-card fallback 조립 방지 |
| P0 | `ARC_STATE_V3_ENABLED` workflow 연결 | 장기 arc memory가 현재 운영에서 꺼져 있을 가능성 큼 |
| P0 | `story_state` 최근 이전 조회 | 주말/휴장 후 연속성 초기화 방지 |
| P1 | `patch_by_episode` 도입 | row 덮어쓰기 위험 감소 |
| P1 | continuity bundle 저장/로드 | 단편적 서사를 직접 개선 |
| P1 | context pack/prompt/planner 확장 | Claude가 이전 회차를 회수하도록 강제 |
| P2 | 상태 전이 함수 정비 | 운영 감사성과 유지보수성 강화 |

## 9. 개발 착수 순서 권장

1. **Resume safety hotfix**: `--force`, 자동 선택, `patch_by_episode`.
2. **Workflow flag hotfix**: `ARC_STATE_V3_ENABLED` 추가.
3. **Story state lookup hotfix**: 최근 이전 상태 조회.
4. **Continuity bundle MVP**: 이전 episode 요약 저장/로드.
5. **Prompt/planner continuity contract**: Previous Episode Continuity 섹션과 panel payoff.
6. **State machine 정비**: transition API와 audit log.

이 순서가 좋은 이유는, 1~3은 운영 리스크를 즉시 줄이고, 4~5는 사용자가 체감하는 “연속성 있는 이야기” 품질을 직접 개선하며, 6은 구조적 안정성을 높이는 후속 정리 작업이기 때문이다.
