# Run Market Action 고도화 상세설계 — 2026-06-30

## 배경

2026-06-30 Run Market Action 로그 분석에서 파이프라인은 정상 완료됐지만,
운영자가 오해하기 쉬운 지점과 코드/DB rollout 순서 차이로 인한 경고가 확인됐다.

1. `INTEL` 실행이 수동/비-schedule 트리거에서는 STEP 4~6까지 진행될 수 있지만,
   schedule 실행에서는 Major Event Gate에 의해 스킵될 수 있다.
2. Phase 2.3의 `episode_type_v3`가 메이저 타입이어도 기존 schedule gate는
   `daily_analysis.regime`만 보면 비용 단계가 스킵될 수 있다.
3. `daily_analysis` character-selection 관측 컬럼 중 하나라도 DB에 없으면,
   기존 fallback은 모든 summary 컬럼을 버리고 `analysis_ctx_json`만 저장했다.

## 목표

- schedule 비용 게이트가 legacy `regime`과 Phase 2.3 `episode_type_v3`를 모두 고려한다.
- schedule 스킵/실행 사유가 GitHub Actions 로그에 명확히 남는다.
- Supabase migration/schema-cache가 부분 반영된 상태에서도 존재하는
  character-selection summary 컬럼은 최대한 보존한다.
- 기존 안전장치인 `analysis_ctx_json` fallback은 유지한다.

## 설계

### 1. Major Gate v3-aware 결정

`scripts.check_major_event_gate`는 `daily_analysis.regime`과
`analysis_ctx_json.episode_type_v3`를 함께 조회한다.

우선순위는 다음과 같다.

1. `regime`이 메이저면 `gate_source=regime`
2. `regime`은 비메이저지만 `episode_type_v3`가 메이저면 `gate_source=episode_type_v3`
3. 둘 다 비메이저면 `gate_source=none`

GitHub Actions output에는 `event_type`, `episode_type_v3`, `gate_source`,
`should_run_expensive`를 출력한다.

### 2. Workflow 진단 로그

`run_market.yml`에 `STEP 3.6 — Major Gate Summary`를 추가해 schedule 실행에서
gate 결과를 명시적으로 출력한다. 비메이저 스킵이면 "expected skip" 메시지를 남긴다.

### 3. daily_analysis schema-compatible update

`engine.persist.asset_writer.save_analysis_ctx()`는 다음 방식으로 저장한다.

1. `analysis_ctx_json` + character-selection summary 전체 update 시도
2. PostgREST schema-cache missing-column 오류가 character-selection 관측 컬럼에서 나면
   같은 optional 관측 컬럼 그룹을 일괄 제거하고 재시도
3. `analysis_ctx_json`이 누락 컬럼으로 보고되거나 알 수 없는 오류면 fail-fast 후
   기존 last-resort fallback으로 `analysis_ctx_json`만 저장

이 방식은 migration/schema-cache 미반영 상태에서 반복 400을 줄이고,
후속 narrative/persist/image 단계에 필요한 `analysis_ctx_json` 저장을 우선 보장한다.

## 테스트 전략

- Major Gate 단위 테스트:
  - legacy regime 메이저 우선
  - legacy regime 비메이저 + `episode_type_v3` 메이저 허용
  - 두 신호 모두 비메이저면 스킵
- Workflow 정적 테스트:
  - Major Gate Summary step 존재
  - `episode_type_v3`, `gate_source`, expected skip 메시지 출력 확인
- persistence 단위 테스트:
  - missing optional observability column 발생 시 관측 컬럼 그룹을 일괄 제거하며 재시도
  - 마지막 성공 payload가 반복 400 없이 `analysis_ctx_json`만 안전하게 유지하는지 확인
- 전체 테스트:
  - `pytest -q`
