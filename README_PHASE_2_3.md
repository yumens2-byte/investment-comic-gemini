# ICG Phase 2.3 — 스토리라인 고도화 (EDT→ICG 이식)

이 압축본은 ICG 저장소 루트 구조와 동일합니다.
압축을 해제하면 기존 파일을 덮어쓰는 형태로 그대로 적용됩니다.

---

## 적용 방법

### 1) 압축 해제 + 덮어쓰기
```bash
cd /path/to/investment-comic-gemini
unzip -o icg_phase23_release.zip
```
- `-o` 옵션으로 기존 파일 강제 덮어쓰기 (수정된 5개 모듈 + 1개 템플릿).
- 신규 파일 9개(SQL 1, 스크립트 1, 테스트 7)는 새 경로에 추가됨.

### 2) 변경 확인
```bash
git status
git diff --stat
```

### 3) Supabase 마이그레이션 (배포 시점에)
```bash
psql $DATABASE_URL -f migrations/2026_05_14_phase23_pair_tension.sql
```

### 4) characters.yaml belief 머지 (배포 시점에)
```bash
python -m scripts.merge_belief_into_canon
```
- Idempotent 보장 (재실행 안전).
- 강제 덮어쓰기: `--force` 플래그.

### 5) Feature Flag 활성화 (점진적 권고)
환경변수 5종, 기본값 false. ON 권고 순서:
1. `VILLAIN_SIGNATURE_BONUS_ENABLED=true`
2. `CROWD_MODIFIER_ENABLED=true`
3. `EMERGENCE_DEFICIT_ENABLED=true`
4. `NARRATIVE_DEPTH_ENABLED=true`
5. `PAIR_TENSION_ENABLED=true`

---

## 파일 변경 분류

### 신규 (NEW)
| 경로 | 용도 |
|---|---|
| `migrations/2026_05_14_phase23_pair_tension.sql` | Supabase 스키마 확장 + 롤백 SQL |
| `scripts/merge_belief_into_canon.py` | characters.yaml belief 머지 (idempotent) |
| `tests/test_g01_belief_canon.py` | 17 테스트 — belief 머지 검증 |
| `tests/test_g02_prompt_integration.py` | 10 테스트 — 프롬프트 렌더링 검증 |
| `tests/test_g03_pair_tension.py` | 45 테스트 — pair_tension 핵심 로직 |
| `tests/test_g05_step15b_step4b.py` | 13 테스트 — STEP 1.5-B/4-B 통합 |
| `tests/test_g08_crowd_modifier.py` | 34 테스트 — crowd_momentum modifier |
| `tests/test_g09_villain_signature_emergence.py` | 32 테스트 — VS bonus + EMR deficit |
| `tests/test_phase23_pilot.py` | 5 파일럿 — 4 시나리오 + 시퀀스 |
| `PHASE_2_3_COMPLETION_REPORT.md` | 마스터 보고서 (커밋 후 삭제 또는 docs/ 이동 권장) |

### 수정 (MODIFIED)
| 경로 | 변경 요약 |
|---|---|
| `engine/arc/arc_state_engine.py` | +300줄. PAIR_TENSION/EDT_PRESSURE/EMERGENCE_DEFICIT 함수군, `update_after_episode` 시그니처 확장 |
| `engine/narrative/battle_calc.py` | +219줄. crowd_modifier/VS_bonus/EMR_deficit/OUTCOME_demotion 함수 + `apply_v23_modifiers` 통합 |
| `engine/narrative/episode_type_engine.py` | STEP 1.5-B 신설, STEP 4-B 조건 B(PR-01) 통합, `EpisodeTypeResult` 필드 2개 추가 |
| `engine/narrative/prompt_tpl.py` | `render_user_prompt` 6 파라미터 추가, characters.yaml belief 자동 추출 |
| `engine/narrative/claude_client.py` | `generate_episode` 3 파라미터 추가 (환경변수 자동 감지) |
| `config/prompts/narrative_user.j2` | Character Belief Sheet + Pair Relationship Tension 블록 2개 추가 |

---

## 신규 Feature Flag

| Flag | 영향 갭 | 기본값 | 동작 |
|---|---|---|---|
| `NARRATIVE_DEPTH_ENABLED` | G01 + G02 | false | Belief Sheet 블록 프롬프트 출력 |
| `PAIR_TENSION_ENABLED` | G03 + G05 | false | pair_tension 갱신 / STEP 1.5-B 트리거 / STEP 4-B 조건B |
| `CROWD_MODIFIER_ENABLED` | G08 | false | Hero Power에 round(cm/4) 보정 |
| `VILLAIN_SIGNATURE_BONUS_ENABLED` | G09 | false | Villain Power에 Lv 1:0/2:+8/3:+18 보정 |
| `EMERGENCE_DEFICIT_ENABLED` | G09 | false | Information Deficit + OUTCOME Demotion |

전부 false면 기존 287/287 테스트 100% 통과 (백워드 호환).

---

## 테스트 결과

| 환경 | 테스트 수 | 결과 |
|---|---|---|
| 베이스라인 (Flag 모두 OFF) | 287 | PASS |
| 신규 + 베이스라인 (Flag OFF) | 443 | PASS |
| 신규 + 베이스라인 (Flag 5종 전체 ON) | 443 | PASS |

압축 해제 후 운영 환경에서 회귀 확인:
```bash
pytest tests/ -q
```

---

## 롤백

### 코드 롤백
- `git revert <commit>` 또는 환경변수 5종 false 처리 → 즉시 기존 동작 복귀.

### DB 롤백
- `migrations/2026_05_14_phase23_pair_tension.sql` 하단 `ROLLBACK SQL` 섹션 실행.
- 신규 컬럼이 nullable + DEFAULT 보유이므로 기존 행 영향 없음.

---

## 후속 작업 (별도 PR 권장)

| 갭 | 내용 | 우선순위 |
|---|---|---|
| G04 | SEASON1_SPINE M1~M5 마일스톤 | 중 |
| G06 | LAYER10 run spine status | 중 |
| G07 | Phase1-B ⑤-확장 마일스톤 권고 | 중 |
| G10 | EMERGENCE Information Deficit Reasoning 가이드 | 저 |
| G13 | SovereignCollapse 그림자 트리거 (Ep58) | 저 |
| G14 | 17v1.7 STEP3-F-2 form3_check_case 6종 통합 | 중 |

---

**Phase 2.3 (Wave 6 갭 이식) 완료. 운영 반영을 위한 마스터의 명령을 대기합니다.**
