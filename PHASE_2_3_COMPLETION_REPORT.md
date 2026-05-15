# ICG Phase 2.3 스토리라인 고도화 — EDT→ICG 이식 작업 완료 보고서

**일자**: 2026-05-14
**범위**: Phase 2.3 핵심 6 갭(G01/G02/G03/G05/G08/G09) ICG 이식
**상태**: 코드 완료 + 테스트 443/443 PASS + 양극 환경 회귀 통과

---

## 1. 작업 결과 요약

| 항목 | 수치 |
|---|---|
| 신규 코드 모듈 작성 | 2 (merge 스크립트, SQL 마이그레이션) |
| 기존 모듈 확장 | 5 (arc_state_engine, battle_calc, episode_type_engine, prompt_tpl, claude_client) |
| 템플릿 확장 | 1 (narrative_user.j2) |
| 신규 Feature Flag | 5 |
| 신규 테스트 | 156 (단위 151 + 파일럿 5) |
| 베이스라인 회귀 | 287/287 PASS (백워드 호환) |
| 전수 테스트 (Flag OFF) | 443/443 PASS |
| 전수 테스트 (Flag ON) | 443/443 PASS |

---

## 2. 변경 파일 리스트 (절대경로)

### 2-1. 신규 생성
- `/home/claude/icg_upgrade/migrations/2026_05_14_phase23_pair_tension.sql` — Supabase 스키마 확장 + 롤백 SQL
- `/home/claude/icg_upgrade/src/scripts/merge_belief_into_canon.py` — characters.yaml belief 머지 스크립트 (idempotent)
- `/home/claude/icg_upgrade/src/tests/test_g01_belief_canon.py` — 17 테스트
- `/home/claude/icg_upgrade/src/tests/test_g02_prompt_integration.py` — 10 테스트
- `/home/claude/icg_upgrade/src/tests/test_g03_pair_tension.py` — 45 테스트
- `/home/claude/icg_upgrade/src/tests/test_g05_step15b_step4b.py` — 13 테스트
- `/home/claude/icg_upgrade/src/tests/test_g08_crowd_modifier.py` — 34 테스트
- `/home/claude/icg_upgrade/src/tests/test_g09_villain_signature_emergence.py` — 32 테스트
- `/home/claude/icg_upgrade/src/tests/test_phase23_pilot.py` — 5 파일럿 테스트

### 2-2. 기존 모듈 확장
- `/home/claude/icg_upgrade/src/engine/arc/arc_state_engine.py` — 약 300줄 추가
  - 신규 상수: `_PAIR_WEIGHT`, `_CHAR_TO_PAIR`, PR-03~06 델타, 임계값 2종
  - 신규 함수: `is_pair_tension_enabled`, `clamp_pair_value`, `calc_edt_pressure`, `get_pair_for_character`, `get_relevant_pair`, `update_pair_tension`, `_select_highest_pair_over_threshold`, `check_pair_tension_trigger`, `attenuate_crowd_momentum`, `update_emergence_deficit`, `get_emergence_deficit_modifier`
  - `_default_arc_state` 확장 (pair_tension/edt_pressure/emergence_deficit_days)
  - `update_after_episode` 시그니처 확장 (hero_ids/form_triggered/zero_block_appeared/villain_defeated)
  - `build_arc_context` 확장 (3 신규 필드 노출)

- `/home/claude/icg_upgrade/src/engine/narrative/battle_calc.py` — 219줄 추가
  - 신규 상수: `_CROWD_MOMENTUM_DIVISOR=4`, `_CROWD_MOMENTUM_MAX_ABS=5`, `_VILLAIN_SIGNATURE_BONUS_TABLE`, `_EMERGENCE_DEFICIT_*`
  - 신규 함수: `crowd_momentum_modifier`, `villain_signature_bonus`, `emergence_information_deficit`, `emergence_outcome_demotion`, `apply_v23_modifiers`

- `/home/claude/icg_upgrade/src/engine/narrative/episode_type_engine.py`
  - `EpisodeTypeResult` 필드 추가: `triggered_pair`, `pair_trigger_flag`
  - 신규 함수: `_step1_5_b_pair_tension`
  - `_step4_dss_correction` 시그니처 확장 + 조건 B(PR-01) 통합

- `/home/claude/icg_upgrade/src/engine/narrative/prompt_tpl.py`
  - `render_user_prompt` 6 신규 파라미터 추가 (모두 기본값으로 백워드 호환)
  - characters.yaml의 belief 블록 자동 추출

- `/home/claude/icg_upgrade/src/engine/narrative/claude_client.py`
  - `generate_episode` 시그니처 확장 (3 신규 파라미터, None이면 환경변수 자동 감지)
  - 하위호환 TypeError fallback 유지

- `/home/claude/icg_upgrade/src/config/prompts/narrative_user.j2`
  - 2개 신규 블록 추가: Character Belief Sheet (RULE BS-01~05), Pair Relationship Tension (RULE PR-01~07)
  - Feature Flag로 가드: `narrative_depth_enabled`, `pair_tension_enabled`

---

## 3. 신규 Feature Flag (전체 기본값 false)

| Flag | 영향 갭 | 동작 |
|---|---|---|
| `NARRATIVE_DEPTH_ENABLED` | G01 + G02 | Character Belief Sheet 블록 프롬프트 출력 |
| `PAIR_TENSION_ENABLED` | G03 + G05 | pair_tension 갱신/STEP 1.5-B 트리거/STEP 4-B 조건B/프롬프트 출력 |
| `CROWD_MODIFIER_ENABLED` | G08 | Hero Power에 round(cm/4) 보정 (±5 클램프) |
| `VILLAIN_SIGNATURE_BONUS_ENABLED` | G09 | Villain Power에 Lv1:0/Lv2:+8/Lv3:+18 보정 |
| `EMERGENCE_DEFICIT_ENABLED` | G09 | Information Deficit (-10/-5) + OUTCOME Demotion |

**중요**: 모든 Flag OFF 시 기존 287개 테스트 100% 통과 보장. 점진적 ON 전환 가능.

---

## 4. Supabase 마이그레이션

**경로**: `/home/claude/icg_upgrade/migrations/2026_05_14_phase23_pair_tension.sql`

추가 컬럼:
- `icg.arc_state.pair_tension JSONB` (기본값 `{PAIR_A:0, PAIR_B:0, PAIR_C:0}`)
- `icg.arc_state.edt_pressure NUMERIC(5,2)`
- `icg.arc_state.emergence_deficit_days INTEGER`
- `icg.daily_analysis.pair_tension JSONB`
- `icg.daily_analysis.edt_pressure NUMERIC`
- `icg.daily_analysis.triggered_pair TEXT`
- `icg.daily_analysis.battle_modifiers JSONB`

추가 인덱스: `idx_daily_analysis_triggered_pair`
롤백 SQL: 동일 파일 하단 포함

---

## 5. 테스트 결과 세부

### 5-1. 단위 테스트 (Wave 1)
| 모듈 | 테스트 수 | 결과 |
|---|---|---|
| test_g01_belief_canon | 17 | PASS |
| test_g02_prompt_integration | 10 | PASS |
| test_g03_pair_tension | 45 | PASS |
| test_g05_step15b_step4b | 13 | PASS |
| test_g08_crowd_modifier | 34 | PASS |
| test_g09_villain_signature_emergence | 32 | PASS |
| **소계** | **151** | **PASS** |

### 5-2. 파일럿 테스트 (Wave 2)
| 시나리오 | 결과 |
|---|---|
| BATTLE — VS Bonus + crowd_modifier 통합 | PASS |
| EMERGENCE — Information Deficit + OUTCOME Demotion | PASS |
| AFTERMATH — PR-05 모든 페어 -10 + edt_pressure 재계산 | PASS |
| CONFLICT — STEP 1.5-B trigger → STEP 4-B 격상 | PASS |
| 다단계 시퀀스 — EMERGENCE→BATTLE→BATTLE→BATTLE deficit 전이 | PASS |
| **소계** | **5/5 PASS** |

### 5-3. 전수 회귀 (Wave 3)
| 환경 | 테스트 수 | 결과 | 소요 시간 |
|---|---|---|---|
| 베이스라인 (Flag 모두 미설정) | 287 | PASS | 2.5초 |
| 신규 + 베이스라인 (Flag 미설정) | 443 | PASS | 3.1초 |
| 신규 + 베이스라인 (5 Flag 전체 ON) | 443 | PASS | 3.0초 |

**결론**: 백워드 호환성 완전 보장. Flag ON 상태에서도 기존 시나리오 회귀 0건.

---

## 6. 운영 배포 권고 순서

마스터의 명령으로 운영 환경 적용 시, 다음 순서를 권고합니다.

### Step 1: 코드 배포 (Flag 전체 OFF 상태)
- icg_upgrade/src 내용을 운영 ICG 저장소로 동기화 (PR 권고)
- Feature Flag 환경변수 설정 없이 배포 → 기존 동작 100% 유지

### Step 2: Supabase 마이그레이션
- `migrations/2026_05_14_phase23_pair_tension.sql` 실행
- 신규 컬럼은 모두 nullable + DEFAULT 보유 → 기존 행 영향 없음

### Step 3: characters.yaml belief 머지
```bash
cd /path/to/icg
python -m scripts.merge_belief_into_canon
```
- Idempotent 보장 (재실행 안전)
- 강제 덮어쓰기: `python -m scripts.merge_belief_into_canon --force`

### Step 4: Feature Flag 점진 ON
권고 순서 (각 Flag 활성 후 최소 1 에피소드 안정성 관찰):
1. `VILLAIN_SIGNATURE_BONUS_ENABLED=true` (저영향, Villain Power만 변동)
2. `CROWD_MODIFIER_ENABLED=true` (저영향, ±5 범위)
3. `EMERGENCE_DEFICIT_ENABLED=true` (EMERGENCE 발행 시점에만 발동)
4. `NARRATIVE_DEPTH_ENABLED=true` (프롬프트 변동, 모델 출력에 영향)
5. `PAIR_TENSION_ENABLED=true` (가장 큰 변화: 에피소드 타입 결정에 영향)

### Step 5: 운영 관찰 항목
- `arc_state.pair_tension` 값 변동 (PR-03/04/05/06 누적)
- `triggered_pair`가 발생하는 에피소드 빈도 (CONFLICT 격상)
- EMERGENCE 직후 EP 2개 동안 hero_power 감산 확인
- 모델 출력에 belief sheet 6요소 반영 여부 (수동 QA)

### 롤백 절차
- Feature Flag만 false 처리 → 즉시 기존 동작 복귀
- DB 롤백 필요 시 `ROLLBACK SQL` 섹션 실행

---

## 7. 핵심 적응 결정 사항

| 항목 | EDT 원본 | ICG 적용값 | 사유 |
|---|---|---|---|
| crowd_momentum 범위 | -10~+10 | -20~+20 (F&G 직접 매핑) | ICG 기존 스키마 보존 |
| crowd_modifier 공식 | cm/2 | round(cm/4) | EDT 효과 크기 동일 유지 (상한 ±5) |
| villain_signature 표현 | int(1/2/3) | 동일 | EDT와 일치 |
| arc_state 초기값 | 옵션A(0) | 동일 | ICG 마이그레이션 단순화 |
| PAIR_C 짝꿍 | Gold Bond↔Zero Block | Zero Block 미정의 시 PAIR_C 비활성 | ICG 캐릭터풀 차이 흡수 |

---

## 8. 후속 작업 권고 (분리 진행)

다음 갭들은 본 작업에서 분리되어 후속 진행이 필요합니다.

| 갭 | 내용 | 우선순위 | 비고 |
|---|---|---|---|
| G04 | SEASON1_SPINE M1~M5 마일스톤 시스템 | 중 | 11B v1.0 이식 |
| G06 | LAYER10 run spine status 추적 | 중 | 06v2.9 |
| G07 | Phase1-B ⑤-확장 마일스톤 권고 | 중 | 07v2.6 |
| G10 | EMERGENCE Information Deficit Reasoning 가이드 | 저 | 모델 가이드 강화 |
| G13 | SovereignCollapse 그림자 트리거 (Ep58 권고) | 저 | M3 마일스톤 |
| G14 | 17v1.7 STEP3-F-2 form3_check_case 6종 호출 통합 | 중 | EDT W3-C 잔여 |

본 작업의 코드/테스트 기반 위에서 점진 확장 가능합니다.

---

## 9. 마스터 의사결정 대기 항목

다음 사항은 마스터의 결정이 필요합니다.

1. **운영 ICG 저장소 동기화 방식**
   - PR 생성 (권고) vs 직접 push
2. **Feature Flag 활성화 일정**
   - 즉시 전체 ON vs 위 Step 4 순서대로 점진
3. **Notion/Linear 등록**
   - 본 작업의 EDT-7/EDT-8/EDT-9 중 어느 Linear 이슈에 코멘트할지
4. **Supabase 마이그레이션 실행 시점**
   - 코드 배포와 동시 vs 별도 메인터넌스 윈도우
5. **후속 갭(G04/G06/G07/G10/G13/G14) 진행 여부**
   - 다음 세션 / 명령 대기

---

**보고 종료. 명령을 대기합니다.**
