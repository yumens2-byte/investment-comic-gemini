# ICG Code Hardening Report — schema_compat 공통화 + step_analysis 분해 (2026-06-30)

## 결론

운영 안전(동작 100% 보존)을 전제로 **C(schema-compat 공통화)** 와 **A(step_analysis 책임 분리)** 를
구현·검증 완료했다. 전체 회귀 2회 통과(594 → 609). **B(Feature Flag 정리)는 추측 금지 원칙에 따라 제외**하고
마스터 운영 데이터 입력을 기다리는 별도 건으로 분리했다.

## 범위 결정 (실측 기반)

| 후보 | 처리 | 사유 |
| --- | --- | --- |
| A — step_analysis 분해 | 구현 | 680줄 god function. 입출력 명확·부수효과 격리된 5개 블록만 추출(보수적). |
| C-코드 — schema-compat 공통화 | 구현 | `_missing_schema_column_from_error` 가 3개 파일에 100% 중복(DRY 위반). |
| B — Feature Flag 정리 | 제외 | 11개 플래그의 안정화/실험/폐기 분류는 코드만으로 판단 불가. 운영 성과 데이터 필요. |
| C-운영 — migration 적용 | 분리 | 코드 산출물이 아닌 운영 DB 액션. 아래 "운영 잔여 액션" 참조. |
| D — non-retryable 분류 | 해당 없음 | 실측 결과 이미 구현 완료(crypto_fetcher / sentiment_fetcher). |
| F — Major Gate v3-aware | 해당 없음 | 실측 결과 이미 구현 완료(decide_major_gate). |

## A. step_analysis 책임 분리

`scripts/run_market.py` 의 `step_analysis()`(680줄)에서 다음 5개 헬퍼를 모듈 레벨로 추출했다.
모두 원본 인라인 로직과 동작이 동일하다.

- `_compute_signal_and_risk(delta, curr_row, logger_inst)` — SIGNAL_PACK_V1 / RISK_SCORE_V3 옵션 계산
- `_load_arc_context(logger_inst)` — ARC_STATE_V3 arc_context 로드
- `_resolve_base_power(canon, hero_id, villain_id)` — Notion battle_constants → characters.yaml fallback
- `_build_sector_rank(signal_pack)` — sector 도메인 → rank / watch / caution
- `_resolve_guest_block(episode_date, curr_row, character_selection_trace, logger_inst)` — STEP 3-Story

scenario/battle 분기(3-2~3-5b)는 지역변수 강결합으로 추출 시 회귀 위험이 커서 보존했다.

**효과**: `step_analysis` 본문 680 → 556줄. 추출 헬퍼는 독립 단위 테스트 가능.

## C. schema-compat 공통화

- 신규 `engine/common/schema_compat.py` — `extract_missing_column(exc)` 단일 진실 소스.
- `asset_writer.py` / `arc_state_engine.py` / `snapshot_writer.py` 의 중복
  `_missing_schema_column_from_error` 를 공통 함수 위임 래퍼로 전환(이름·시그니처 유지).
- strip 정책(one_by_one / all_at_once)은 모듈별 차이가 있어 통합하지 않음(과도 추상화 회피).

## 테스트 결과

- Baseline: ruff PASS, pytest **594 passed**
- 최종: ruff PASS ×2, pytest **609 passed** ×2 (594 + schema_compat 8 + helpers 7), 회귀 0, flaky 없음

### 변경/신규 파일

| 파일 | 구분 |
| --- | --- |
| `engine/common/schema_compat.py` | 신규 |
| `tests/test_schema_compat.py` | 신규 |
| `tests/test_run_market_analysis_helpers.py` | 신규 |
| `scripts/run_market.py` | 변경(헬퍼 5종 추출 + 호출 교체) |
| `engine/persist/asset_writer.py` | 변경(위임 전환) |
| `engine/arc/arc_state_engine.py` | 변경(위임 전환) |
| `engine/data/snapshot_writer.py` | 변경(위임 전환) |
| `docs/ICG_CODE_HARDENING_REPORT_2026-06-30.md` | 신규(본 문서) |

## 운영 잔여 액션 (코드와 분리)

Supabase migration 적용 + PostgREST schema 캐시 갱신 시 schema-compat 경고 자체가 소멸한다.

- `migrations/2026_06_20_run_market_critical_fallback.sql` (daily_snapshots.data_quality)
- `migrations/2026_06_03_character_selection_observability.sql` (daily_analysis.character_selection 외)
- `migrations/2026_06_21_arc_state_zero_block_compat.sql` (arc_state.zero_block_just_appeared)

## 다음 단계

1. B 플래그 분류 — 11개 플래그 ON 회차/성과 입력 → 안정화/실험/폐기 3분류안 작성.
2. C-운영 migration 적용 — Supabase MCP 직접 적용.

> 배포 시 `.github/workflows/` 는 기존 운영 원칙대로 GitHub 웹에서 직접 관리한다.
> 이번 변경은 워크플로우 파일을 수정하지 않았다(.py / 신규 테스트만 변경).

---

## 후속 (2026-06-30 P2) — Feature Flag 관측성 확장

### 배경
운영 데이터(`icg.daily_analysis`) 실측 결과, `_feature_flag_snapshot()`이 연속성 5개 플래그만
기록하여 나머지 6개(scenario/battle 계열)의 활성 이력을 데이터로 확인할 수 없었다.
"11개 전부 ON 운영"을 데이터로 검증하려면 11개 전부를 기록해야 한다.

### 변경
- `scripts/run_market.py`: `_feature_flag_snapshot()`을 **5개 → 11개** 기록으로 확장.
  - `_CONTINUITY_FLAG_NAMES`(5) 유지 + `_SCENARIO_BATTLE_FLAG_NAMES`(6) 신규 + `_ALL_FEATURE_FLAG_NAMES`(11).
  - 11개: NARRATIVE_CONTEXT / STORY_PLANNER / CONTINUITY_STRICT / ARC_STATE_V3 / EPISODE_TYPE_V3
    + SCENARIO_V2 / NARRATIVE_DEPTH / PAIR_TENSION / CROWD_MODIFIER / VILLAIN_SIGNATURE_BONUS / EMERGENCE_DEFICIT
- `tests/test_run_market_quality.py`: 기존 continuity 테스트를 부분검증으로 완화(상위호환 확인) + 11개 전부 검증 테스트 추가.

### 안전성
- `analysis_ctx_json`(JSONB)에 저장되므로 **DB 스키마 변경 없음**.
- 기존 5개 키 전부 보존 → 다운스트림 진단 로직 무영향(상위호환).
- 동작 변경 없이 **관측만 추가**.

### 테스트
- 파일럿: `test_run_market_quality.py` 8 passed
- 전수: ruff PASS ×2, pytest **610 passed** ×2 (이전 609 + 신규 11개검증 1), 회귀 0

### 효과
다음 운영 회차부터 6개 scenario/battle 플래그의 ON/OFF가 회차별로 기록된다.
일정 기간 축적 후, 데이터 기반으로 B(플래그 안정화/폐기 분류)를 팩트로 진행할 수 있다.

> 참고: 작업 시작 시점에 작업 컨테이너에 출처 불명의 11개 확장 코드가 존재했으나,
> 검증된 직전 산출물(A/C 적용본, flag 5개)을 신뢰 base로 재설정한 뒤 깨끗이 재구현했다.

---

## 후속 (2026-06-30 P3) — BATTLE 회차 플래그 OFF 원인 규명 및 yml 수정

### 증상
운영 데이터에서 `regime=BATTLE` 회차의 `feature_flags_snapshot`이 일관되게 전부 OFF(0)로 기록.

### 원인 (복합 2가지)
**원인 A — yml fallback 결함 (확정)**
`run_market.yml` env 블록에서 11개 중 9개는 `... || vars.X || 'false'`로 vars fallback이 있으나,
`SCENARIO_V2_ENABLED`/`EPISODE_TYPE_V3_ENABLED`만 `inputs.X || 'false'`로 vars fallback이 없었다.
또한 두 input의 default가 `'false'`였다. 따라서 cron schedule 자동 실행(inputs 비어 있음) 시
이 2개는 구조적으로 무조건 false가 된다.

**원인 B — vars 미등록 (강한 정황, 마스터 확인 필요)**
schedule(BATTLE) 회차에서 vars-fallback 9개도 전부 false였다.
이는 GitHub Actions Repository Variables에 11개 플래그가 true로 등록되지 않았음을 시사한다.

### 데이터 교차검증
- `episode_type_v3=true`는 yml상 workflow_dispatch로만 가능 → true 회차 = 수동 dispatch, OFF 회차 = schedule 자동.
- 즉 "전부 true 운영"은 수동 dispatch 시에만 성립했고, cron 자동 회차는 전부 false로 발행되고 있었다.

### 해결 (원인 A) — yml 수정 4곳
- `inputs.scenario_v2` default: `'false'` → `'auto'`
- `inputs.episode_type_v3` default: `'false'` → `'auto'`
- `env.SCENARIO_V2_ENABLED`: vars fallback 추가 (나머지 9개와 동일 패턴)
- `env.EPISODE_TYPE_V3_ENABLED`: vars fallback 추가

검증: yml 파싱 OK, `test_workflow_run_market.py` 8 passed, 전수 610 passed ×2, ruff PASS.

### 남은 운영 액션 (원인 B) — 마스터 영역, 필수
yml 수정만으로는 부족하다. **Repository Variables에 11개 플래그를 `true`로 등록**해야
schedule 자동 회차가 의도대로 동작한다. (vars 미등록 시 yml fallback이 여전히 'false')

등록 대상 11개: SCENARIO_V2_ENABLED, EPISODE_TYPE_V3_ENABLED, ARC_STATE_V3_ENABLED,
NARRATIVE_DEPTH_ENABLED, PAIR_TENSION_ENABLED, CROWD_MODIFIER_ENABLED,
VILLAIN_SIGNATURE_BONUS_ENABLED, EMERGENCE_DEFICIT_ENABLED, NARRATIVE_CONTEXT_ENABLED,
STORY_PLANNER_ENABLED, CONTINUITY_STRICT_ENABLED

> yml은 기존 운영 원칙대로 GitHub 웹 에디터로 직접 반영 권장. 본 압축물에는 수정본이 포함되어 있다.
