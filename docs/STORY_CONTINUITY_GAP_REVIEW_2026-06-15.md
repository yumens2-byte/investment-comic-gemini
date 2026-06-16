# 전후 스토리 연속성 강화 갭 리뷰

작성일: 2026-06-15

## 결론

현재 파이프라인은 `previous_episode` 번들, `Narrative Context Pack`, `StoryBeatPlan`, `story_state_json`, `arc_state`까지 연결되어 있어 전후 회차 연속성을 만들 수 있는 뼈대는 존재한다. 다만 실제 결과물이 단편적으로 보이는 이유는 "이전 회차 기억을 로드한다"와 "작가 프롬프트가 반드시 회수한다" 사이의 강제력이 아직 약하고, 완성된 회차에서 다음 회차로 넘겨야 할 hook/관계 변화가 구조화되어 있지 않기 때문이다.

## 이미 갖춰진 장치

1. `load_previous_continuity()`가 직전 `published` 또는 `assembled` 에피소드에서 continuity bundle을 만들 수 있다.
2. `build_narrative_context_pack()`은 `previous_episode`가 있으면 pack에 포함하고 panel 1~2에서 hook을 회수하라는 directive를 추가한다.
3. `build_story_beat_plan()`은 이전 hook/final panel이 있으면 1번 패널에 `continuity_payoff`와 `must_reference_previous`를 설정한다.
4. `narrative_user.j2`는 Narrative Context Pack과 Story Beat Plan을 프롬프트에 전달한다.
5. `story_state_json`은 정확히 전날이 아니라 가장 최근 이전 상태를 조회하도록 개선되어 있다.
6. GitHub Actions에는 `ARC_STATE_V3_ENABLED`, `NARRATIVE_CONTEXT_ENABLED`, `STORY_PLANNER_ENABLED` 플래그가 연결되어 있다.

## 부족한 작업 / 강화 포인트

### 1. 이전 회차 정보가 프롬프트 본문에 충분히 드러나지 않음

`narrative_user.j2`는 `market_cause`, evidence, foreshadow, guardrail은 상세히 보여주지만, `previous_episode`의 제목, 마지막 장면, next hook, unresolved thread를 별도 섹션으로 직접 출력하지 않는다. 현재는 fallback 또는 StoryBeatPlan의 intent에 의존하므로 모델이 시장 데이터 섹션을 더 강하게 따라가면 전후 연결이 약해질 수 있다.

권장 작업:
- `## Previous Episode Continuity` 섹션을 추가한다.
- `source_episode_id`, `title`, `final_panel_summary`, `next_hook`, `unresolved_threads`, `must_continue_from`를 직접 노출한다.
- "P1 또는 P2의 narration/dialogue/market_ref 중 하나에 반드시 회수" 같은 명시 규칙을 넣는다.

### 2. StoryBeatPlan의 연속성 강제력이 1번 패널에만 집중됨

`build_story_beat_plan()`은 continuity seed가 있을 때 1번 패널만 `must_reference_previous=True`로 표시한다. 하지만 생성 결과가 1번 패널에서 약하게 언급하거나 누락하면 이후 패널에서 복구할 장치가 없다.

권장 작업:
- P1은 hook 회수, P2는 오늘 시장 원인과 hook 연결로 역할을 분리한다.
- P2에도 `must_reference_previous=True` 또는 `continuity_payoff`를 조건부 부여한다.
- P6/P7에는 이번 회차의 결과가 이전 unresolved thread를 어떻게 변화시켰는지 쓰는 beat 필드를 추가한다.

### 3. 완료된 회차의 다음 hook 추출이 너무 단순함

`build_continuity_bundle()`은 `script_dict.get("next_hook")`가 없으면 final story panel text를 next hook으로 대체한다. 현재 EpisodeScript가 명시적 `next_hook` 필드를 안정적으로 제공하지 않으면 다음 회차는 "마지막 대사"만 이어받게 되어 장기 떡밥/관계 변화가 흐릿해진다.

권장 작업:
- 스크립트 스키마에 `next_hook`, `resolved_threads`, `unresolved_threads`, `relationship_delta`, `villain_plan_next`를 정식 필드로 추가한다.
- Claude 출력 검증에서 해당 필드가 비어 있으면 실패 또는 보정한다.
- continuity bundle은 final panel fallback보다 구조화 필드를 우선 사용한다.

### 4. continuity 품질 게이트가 없음

현재 `narrative_context_pack`과 `story_beat_plan` 존재 여부에 대한 품질 게이트는 있지만, 실제 생성된 8컷이 이전 hook을 회수했는지 검사하는 게이트는 부족하다.

권장 작업:
- `previous_episode.next_hook`이 있을 때 P1~P2 텍스트에 hook 키워드가 포함되는지 검사한다.
- `must_reference_previous=True` beat가 있는 패널의 narration/dialogue가 빈 회수가 아닌지 검사한다.
- 실패 시 publish/persist를 막거나 `continuity_degraded=true`를 기록한다.

### 5. 장기 아크와 단기 continuity가 분리되어 있음

`arc_state`는 active villain, arc tension, open hook 등 장기 축을 담당하고, `previous_episode`는 직전 회차 기억을 담당한다. 그러나 두 정보가 서로 검증되거나 병합되는 단계가 약하다. 예를 들어 previous_episode의 villain과 arc_state의 active_villain이 다를 때, 의도적 교체인지 단절인지 설명하는 규칙이 필요하다.

권장 작업:
- continuity bundle에 `arc_id`, `arc_day`, `active_villain`, `arc_tension` 스냅샷을 추가한다.
- 오늘 `arc_context`와 직전 bundle이 충돌하면 `continuity_pivot_reason`을 요구한다.
- 캐릭터 교체/빌런 교체 시 P1~P2에서 "왜 장면이 바뀌었는지" 설명하도록 한다.

### 6. 관계 변화 메모리가 캐릭터 등장 이력 중심임

`story_state_json`은 캐릭터의 마지막 역할/등장일, world_state, arc_episode를 저장한다. 그러나 캐릭터 간 감정 변화, 패배 후 반응, 임시 동맹, 배신 같은 전후 스토리 체감 요소는 별도 구조로 저장되지 않는다.

권장 작업:
- `relationship_state` 또는 `character_memory`를 추가한다.
- 예: `{pair_id, trust_delta, conflict_delta, last_scene, unresolved_emotion}`.
- StoryBeatPlan의 `hero_inner_conflict`와 `villain_motivation`에 이 메모리를 반영한다.

### 7. 운영 플래그가 꺼져 있으면 연속성 기능이 통째로 약화됨

workflow에는 플래그가 연결되어 있지만 기본값은 repository variables 또는 `false`이다. 운영에서 `NARRATIVE_CONTEXT_ENABLED`, `STORY_PLANNER_ENABLED`, `ARC_STATE_V3_ENABLED` 중 하나라도 꺼져 있으면 전후 연속성 체감이 급격히 떨어진다.

권장 작업:
- 운영 preset을 만든다: `CONTINUITY_STRICT=true`일 때 세 플래그를 함께 켠다.
- 로그에 세 플래그와 previous_episode 로드 여부를 한 줄로 출력한다.
- previous_episode가 없을 때 "첫 회차/DB 부재/직전 회차 스크립트 부재" 원인을 구분한다.

## 우선순위 제안

### P0: 즉시 효과가 큰 작업

1. `narrative_user.j2`에 Previous Episode Continuity 섹션 추가.
2. P1~P2 continuity quality gate 추가.
3. EpisodeScript/continuity bundle에 명시적 `next_hook`과 `unresolved_threads` 필드 강화.

### P1: 장기 연속성 강화

1. StoryBeatPlan에서 P1/P2/P6/P7에 continuity 역할 분배.
2. `arc_context`와 `previous_episode` 충돌 시 pivot reason 요구.
3. 캐릭터 관계 메모리(`relationship_state`) 저장.

### P2: 운영/관측성

1. `CONTINUITY_STRICT` 운영 preset 추가.
2. continuity input/output snapshot을 `analysis_ctx_json` 또는 별도 `continuity_json`으로 저장.
3. continuity degraded/fallback 상태를 DB와 로그에 남긴다.

## 권장 구현 순서

1. 프롬프트 노출 강화: 기존 구조를 바꾸지 않고 `previous_episode`를 작가에게 직접 보이게 한다.
2. 품질 게이트 추가: 생성 결과가 이전 hook을 실제로 회수했는지 자동 검사한다.
3. 스키마 강화: 다음 회차로 넘길 hook/thread/관계 변화를 구조화한다.
4. 장기 아크 병합: `arc_state`, `story_state_json`, `previous_episode`를 하나의 continuity contract로 묶는다.
5. 운영 preset/로그: 플래그 누락으로 기능이 꺼지는 상황을 방지한다.
