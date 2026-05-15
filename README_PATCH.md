# ICG Phase 2.3.1 Hotfix Patch — Iron Nuna 정적 포즈 + role='support' + Notion mirror DB ID

## 변경 파일 4종 (icg_src/)

| 파일 | 변경 사항 |
|---|---|
| `.github/workflows/run_market.yml` | NOTION_TRACKER_DS 정정 (485ba577→4c08a06f) |
| `config/prompts/narrative_user.j2` | ALLIANCE 블록 role/char_id 강화 |
| `engine/image/prompt_builder.py` | DYNAMIC ACTION 블록 신설 + DESIGN SPECS 가드 범위 명확화 (외형 한정) |

## 변경 안 한 파일 (의도적)
- `engine/narrative/schema.py` — PanelCharacter.action 필드 추가는 Phase 2.4 권고 (docs/GEMINI_PRO_AND_SCHEMA_EVALUATION.md 참조)

## 동시에 처리된 Notion 페이지 (이미 운영 반영)
- `3439208cbdc3816bb578d7355b3a1966` (narrative_user_template) — ALLIANCE 블록 강화 적용 완료
- `3439208cbdc381ccb85cf8e177a1a3d2` (character_ref_prompts) — `## CHAR_HERO_002` 동적 REF 프롬프트 추가 완료

## 검증 결과
- ruff: All checks passed
- pytest (Flag OFF): 443/443 PASS
- pytest (Flag ALL ON): 443/443 PASS
- YAML 구문: OK
- Jinja2 구문: OK

## 적용 절차

### Step 1 — 코드 반영 (마스터 수행)
```bash
cd /path/to/investment-comic-gemini
unzip -o icg_phase23_1_hotfix.zip
git status   # 4개 파일 변경 확인
git add .github/ config/ engine/ docs/
git commit -m "fix(phase23.1): Iron pose, role='support', notion mirror DB ID, dynamic action"
git push
```

### Step 2 — Iron Nuna REF 이미지 재생성 (마스터 수행)
GitHub Actions → **Generate Character REF Images** workflow_dispatch:
- `characters`: `CHAR_HERO_002`
- `force`: `true`

실행 후:
1. `assets/characters/hero_iron_securities_nuna.png` 신규 이미지 확인
2. 새 이미지가 동적 포즈인지 검수 (소총 사격 + ETF 방패 방어 + 캐이프 휘날림)
3. 검수 통과 시 git commit (워크플로가 자동 commit하는지 확인 필요)
4. 부적합 시 Notion `## CHAR_HERO_002` 섹션 수정 후 재실행

### Step 3 — Phase 2.3 다음 Flag ON 검토 (마스터 의사결정)
`docs/PHASE_2_3_NEXT_FLAG_GUIDE.md` 참조.
권장 순서: `VILLAIN_SIGNATURE_BONUS_ENABLED` → `CROWD_MODIFIER_ENABLED` → `EMERGENCE_DEFICIT_ENABLED` → (NARRATIVE_DEPTH 이미 ON) → `PAIR_TENSION_ENABLED`.

### Step 4 — 다음 운영 EP 발행 (검증)
정기 cron 또는 수동 트리거.
- STEP 4 로그에서 Flag 상태 확인
- STEP 5 Persist 단계에서 Notion mirror 성공 여부 확인 ("페이지 생성 실패" 메시지 사라져야 정상)
- STEP 6 Image에서 Iron Nuna 등장 패널 시각 확인 (동적 포즈 + DYNAMIC ACTION 묘사 반영)
- Claude 1차 시도 성공 (role='support' 재시도 없어야 정상)

## 마스터 의사결정 대기 항목
1. Iron Nuna 검수 후 나머지 10종 (히어로 4 + 빌런 6) 동적 REF 확장 일정
2. 1주 운영 후 Gemini Pro 업그레이드 여부
3. Phase 2.4 schema 확장 시기
