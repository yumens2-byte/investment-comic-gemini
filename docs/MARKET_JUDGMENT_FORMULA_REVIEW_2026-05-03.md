# 시장 판단 계산식 검토 리포트 (2026-05-03)

## 범위
- `engine/analysis/delta_engine.py`
- `engine/analysis/event_classifier.py`
- `engine/narrative/scenario_selector.py` (`compute_risk_level_from_delta`)
- `engine/narrative/battle_calc.py`

## 핵심 결론
1. **현재 risk_level 계산식은 WTI 절대값 임계(70/100) 의존이 커서 `MEDIUM` 상시화 가능성이 높음.**
2. **event_type 판정은 `pct`(변화율), risk_level 판정은 `curr`(절대값) 중심이라 축이 분리되어 있음.**
3. **발행 게이트(메이저 이벤트 한정) 전략과 맞추려면 risk 계산도 ‘이벤트성(변화율/충격도)’ 비중을 올리는 것이 적합.**

## 모듈별 점검

### 1) delta_engine
- `pct = (curr-prev)/abs(prev)` 방식은 부호 안정성 측면에서 합리적.
- 단, `prev==0`이면 `pct=None` 처리되어 downstream에서 0으로 대체될 가능성 있음(정보 손실 주의).

### 2) event_classifier
- 이벤트 분류는 WTI%, VIX 레벨+%, DGS10 레벨, SPY% 등 **이벤트성 지표**를 사용.
- 메이저 이벤트 중심 운영에 맞는 구조.

### 3) scenario_selector.compute_risk_level_from_delta
현행 규칙:
- HIGH: `VIX>=30` 또는 `WTI>=100`
- MEDIUM: `VIX>=20` 또는 `WTI>=70`
- LOW: 그 외

리스크:
- WTI가 70~95 구간인 기간이 길면 VIX가 낮아도 MEDIUM 고정.
- 결과적으로 NO_BATTLE(LOW+NORMAL/INTEL) 빈도 축소 → 서사 휴지기 감소 가능.

### 4) battle_calc
- 캐릭터/지표 연동 보너스 구조는 명확.
- 다만 `event_type`/`risk_level` 불일치가 누적되면 전투 강도 체감이 스토리 톤과 엇갈릴 수 있음.

## 파일럿 테스트 관점 체크리스트
- [ ] 최근 30거래일 기준 risk_level 분포(LOW/MEDIUM/HIGH)
- [ ] event_type 분포(BATTLE/SHOCK/AFTERMATH/INTEL/NORMAL ...)
- [ ] risk_level과 event_type 상관(예: NORMAL인데 HIGH 빈발 여부)
- [ ] 발행 스킵률(메이저 게이트 적용 후)

## 개선 제안 (다음 단계)
1. **WTI 절대값 대신 WTI 변화율(%)/z-score 병행**
2. **VIX level + VIX pct 동시 반영**
3. **복합 점수식(가중합)으로 LOW/MEDIUM/HIGH 컷오프 재정의**
4. **2~4주 파일럿 후 컷오프 튜닝**

## 즉시 운영 권고
- 코드 즉시 변경보다 먼저, 현재 식으로 2주 로그를 수집해 분포를 확인한 뒤 임계값을 조정하는 것이 안전.
