# Phase 2.3 — 다음 Flag ON 권고 가이드

## 현재 상태 (2026-05-16 기준)
- `NARRATIVE_DEPTH_ENABLED = true` ✅ ON (운영 검증 완료)
- 나머지 4종 = false

## 첫 ON Flag 운영 검증 결과
첫 에피소드(ICG-2026-05-16-001) 발행 결과, Belief Sheet 11종이 narrative에 정확히 반영됨:
- P4 narration: EDT `belief.truth` ("시스템은 한 명의 강함이 아니라 모두의 회복력으로 선다")
- P5 narration: V004 `belief.defeat_visual` ("다섯 머리가 서로 충돌하며 자가 분열했다")
- P5 key_text: V004 `belief.truth` ("공포는 가장 빠르게 사라지는 감정이다")
- P6 narration: EDT `belief.truth` 변주

## 다음 Flag 권장 순서

권장 순서는 **저영향 → 고영향** 순으로, 각 단계 ON 후 **최소 1 EP 발행 + 결과 관찰**:

### Step 2 — `VILLAIN_SIGNATURE_BONUS_ENABLED = true` (권장)
**영향**: Villain Power +0/+8/+18 (Lv.1/2/3별 가산)  
**관찰 항목**:
- Lv.1 빌런: 변화 없음 (+0)
- Lv.2 빌런: Villain Power 상승 → Balance 약 -8 변동
- Lv.3 빌런: Villain Power 큰 상승 → Balance 약 -18 변동
- `daily_analysis.battle_modifiers.villain_signature_bonus` 컬럼에 적용된 값 기록됨

**기대 효과**: 빌런 Lv.별 위협감 차별화. 약한 빌런과 강한 빌런이 균형에 명확히 다른 영향.

**롤백**: Repository Variables `false`로 → 다음 cron 실행부터 비활성.

### Step 3 — `CROWD_MODIFIER_ENABLED = true`
**영향**: Hero Power ±0~5 (Fear & Greed 지수 기반)  
**관찰 항목**:
- F&G < 25 (Extreme Fear): Hero Power -5 (군중 공포로 영웅 약화)
- F&G > 75 (Extreme Greed): Hero Power +5 (군중 자신감으로 영웅 강화)
- 25 ≤ F&G ≤ 75: 변화 없음 (±0)
- `battle_modifiers.crowd_momentum_modifier` 컬럼 기록

**기대 효과**: 시장 심리가 전투 결과에 영향. 패닉장은 영웅도 흔들림.

### Step 4 — `EMERGENCE_DEFICIT_ENABLED = true`
**영향**: EMERGENCE 발행 후 2 EP 동안 Hero Power 감산 (-10/-5)  
**관찰 항목**:
- 새 빌런 첫 등장 EP: 변화 없음 (EMERGENCE 본 자체)
- 다음 EP (Day 1): Hero Power -10 (정보 부족 페널티 최대)
- 그 다음 EP (Day 2): Hero Power -5 (정보 부족 페널티 감소)
- Day 3+: 변화 없음
- `arc_state.emergence_deficit_days` 컬럼이 자동 감소

**기대 효과**: 새 위협 등장 직후 영웅이 적응 시간 필요. 정보 비대칭 묘사.

### Step 5 — `PAIR_TENSION_ENABLED = true` (최대 변화 — 마지막)
**영향**:
- pair_tension 누적 (PAIR_A: EDT↔Leverage, PAIR_B: Iron Nuna↔Futures Girl, PAIR_C: Gold Bond↔Zero Block)
- edt_pressure 자동 계산 (PAIR_A×1.0 + PAIR_B×0.5 + PAIR_C×0.3)
- STEP 1.5-B: pair_tension ≥ 70 시 triggered_pair 발동 → CONFLICT 격상
- STEP 4-B: PR-01 가중 적용

**관찰 항목**:
- `arc_state.pair_tension` JSONB 갱신 추적
- `daily_analysis.triggered_pair` 발생 빈도 모니터링
- ALLIANCE 시나리오에서 계획된 사이드킥(PAIR_A 멤버) 등장 확률 상승 기대

**기대 효과**: 캐릭터 관계 동학이 시나리오 분기에 영향. ICG의 가장 큰 narrative 변화.

**경고**: 한 번 활성 후 pair_tension 값이 DB에 누적되므로, OFF로 돌려도 누적 데이터는 남음 (단순히 사용 안 함). 완전 초기화 필요 시 `UPDATE icg.arc_state SET pair_tension = '{"PAIR_A":0,"PAIR_B":0,"PAIR_C":0}'::jsonb`.

## ON 작업 절차

각 단계마다:
1. GitHub Repo → **Settings** → **Secrets and variables** → **Actions** → **Variables**
2. 해당 변수 (예: `VILLAIN_SIGNATURE_BONUS_ENABLED`) 값을 `true`로 수정
3. 다음 cron 실행 (KST 01:30) 또는 즉시 검증 시 **Run Market** workflow_dispatch
4. STEP 4 로그에서 "🎛️ Phase 2.3 Feature Flags:" 라인 확인
5. 에피소드 발행 후 Supabase 쿼리로 modifier 적용 확인

## 운영 모니터링 SQL

```sql
-- 최근 7일 battle_modifiers 적용 추이
SELECT 
  analysis_date,
  episode_id,
  battle_modifiers,
  pair_tension,
  edt_pressure,
  triggered_pair
FROM icg.daily_analysis
WHERE analysis_date >= CURRENT_DATE - 7
  AND battle_modifiers IS NOT NULL
ORDER BY analysis_date DESC;

-- 현재 arc_state 누적값
SELECT pair_tension, edt_pressure, emergence_deficit_days
FROM icg.arc_state WHERE id = 1;
```

## 긴급 롤백

5종 모두 한 번에 끄기: Repository Variables에서 5개 모두 `false` (또는 삭제)  
→ 다음 cron부터 즉시 비활성. DB/Notion/코드 롤백 불필요.
