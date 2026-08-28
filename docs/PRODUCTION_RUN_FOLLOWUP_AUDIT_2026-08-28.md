# 2026-08-28 재실행 로그 후속 품질 감사

## 1. 판정

재실행에서 pct-of-pct 결함은 해소됐고 `next_hook`, 실제 시장 수치, 가설 구조도 이전 결과보다 개선됐다. 그러나 ProductionQualityGate가 정확히 5개 결함을 검출하고도 STEP 4를 성공 처리하여 persist와 image까지 진행했다. 따라서 이번 실행의 핵심 결함은 **검출 실패가 아니라 fail-open 배포 설정**이다.

발행 판단은 `차단 필요`다. 검출된 위반은 다음과 같다.

1. 근거 없는 알고리즘 인과 표현 3건
2. 필수 게스트 `SENTINEL_YIELD` 누락
3. 정적 동작 비율 80% 이상
4. 별도 수동 점검으로 확인된 운영 placeholder thread 2건
5. P7 narration의 `BTC +1.` 숫자 중간 절단

## 2. 개선이 확인된 항목

- SPY `+1190%`, NASDAQ `+936%`, CRYPTO_BASIS `+201%`는 사라졌다.
- FEAR_GREED는 `+8 score`, VIX/BTC는 각자의 변화율로 표시돼 단위 구분이 개선됐다.
- `next_hook`과 독자용 unresolved thread가 생성됐다.
- `NO_BATTLE`에서 `BATTLE` panel type이 제거됐다.
- relationship 입력이 없을 때 `relationship_reuse_score=0`으로 계산됐다.
- 첫 연속성 점수 68.8을 감지해 두 번째 생성으로 81.25까지 개선했다.

## 3. fail-open 원인

운영 로그는 `StoryContinuity strict=True`지만 ProductionQuality 결과는 warning으로 출력된 뒤 `DONE`으로 끝났다. 코드에서 continuity strict와 production strict가 서로 다른 환경 변수에 묶여 있었고, GitHub Actions workflow에는 `SERIAL_NARRATIVE_P0_ENABLED` 매핑이 없었다.

그 결과:

```text
CONTINUITY_STRICT_ENABLED=true
SERIAL_NARRATIVE_P0_ENABLED=false 또는 미전달
→ 연속성 실패만 재시도/차단
→ production violation은 warning
→ script 저장 → persist → image 진행
```

보완 후에는 `CONTINUITY_STRICT_ENABLED=true` 자체가 ProductionQualityGate도 fail-closed로 만든다. 또한 workflow env와 feature flag snapshot에 `SERIAL_NARRATIVE_P0_ENABLED`를 명시해 stage 간 설정을 관측할 수 있다.

## 4. 스토리 잔여 결함

### 4.1 알고리즘 인과

P1과 Telegram은 전 회차 문구를 그대로 회수하는 과정에서 “알고리즘 압력 구간”을 사실처럼 재사용했다. 이전 회차 문자열이라도 현재 evidence가 지지하지 않으면 면책되지 않는다. hook payoff는 원문 복제가 아니라 “전 회차에서 알고리즘 압력으로 묘사했던 구간”처럼 픽션/과거 서술로 한정하거나, 해당 인과를 제거해야 한다.

### 4.2 게스트 계약

분석에서 `SENTINEL_YIELD(WARNER)`가 선택되고 planner도 이를 요구했지만 모든 인물 패널에는 EDT만 존재한다. Gate는 이를 정확히 찾았으므로 strict 연결로 발행을 막아야 한다. 재시도 feedback에는 필수 char ID, 요구 패널, `npc` role을 명시해야 한다.

### 4.3 정적 동작

P1 팔짱·관찰, P2 tracing/비교, P3 서서 관찰, P4 응시, P5 보고 숨 고르기, P6 로그 기록으로 구성돼 저항과 상호작용이 약하다. 가설은 생겼지만 그 가설이 깨지거나 타 캐릭터의 반론으로 수정되지 않는다. Sentinel이 P3에서 금리 근거로 반론하고 EDT가 P5에서 판단을 수정하는 구조가 적합하다.

### 4.4 운영 placeholder thread

다음 문장은 독자용 서사가 아니라 내부 상태를 영어 문장으로 직렬화한 것이다.

- `Previous battle outcome remains unresolved emotionally: PEACEFUL_GROWTH.`
- `Track continuing pressure from villain CHAR_VILLAIN_004`

특히 두 번째 문장은 `NO_BATTLE`과 모순된다. 원인은 continuity bundle이 battle outcome과 villain ID로 synthetic thread를 자동 생성한 데 있다. 보완 후에는 작가가 생성한 hook/thread만 continuity truth로 보존한다.

### 4.5 숫자 중간 절단

P7 narration이 `BTC +1.`에서 끝난다. 문자열 자동 축약이 마지막 `.`을 문장 경계로 찾을 때 소수점까지 종결점으로 오인한 결과다. 보완 후에는 공백 또는 문자열 끝 앞의 문장부호만 종결점으로 인정하며, `+1.`처럼 끝나는 출력도 ProductionQualityGate가 별도 차단한다.

## 5. 연속성 점수 해석

81.25점은 이전보다 유효하지만 완전한 의미 회수를 보장하지 않는다. matched term에 `battle`, `outcome`, `peaceful`, `growth`가 포함된 것은 synthetic English placeholder가 점수를 올렸다는 증거다. 즉, 시스템이 만든 운영 문자열을 시스템이 다시 회수해 점수를 얻었다. Synthetic thread 제거 후에는 독자에게 보이는 실제 hook과 thread만 평가해야 한다.

첫 시도 68.8의 `missing_requirements=[]` 때문에 retry 로그가 비어 있던 문제도 있다. 총점 미달이지만 개별 하한을 넘긴 경우 `continuity_score_below_threshold`를 명시하도록 변경한다. Production violation code도 같은 retry reason 로그에 합쳐 기록한다.

## 6. 보완 후 기대 동작

```text
attempt 1
  continuity=degraded 또는 production violations>0
  → QualityRetry(reason codes 포함)

attempt 2
  violations=0
  → script 저장 가능

attempt 2
  violations>0
  → ProductionQualityError
  → STEP 4 fail
  → persist/image 실행 금지
```

각 attempt는 `_production_quality`에 strict 여부, pass/fail, violation code와 detail을 저장한다. 따라서 다음 운영 로그에서는 단순 `warning` 이후 `DONE`이 나타나면 안 된다.

## 7. 재검증 완료 조건

- workflow 로그에 `SERIAL_NARRATIVE_P0_ENABLED` 상태가 출력된다.
- `CONTINUITY_STRICT_ENABLED=true`에서 production violation을 주입하면 STEP 4가 실패한다.
- `UNSUPPORTED_ALGORITHM_CAUSALITY`, `REQUIRED_CAST_MISSING`, `STATIC_ACTION_STREAK`가 남은 두 번째 결과는 저장되지 않는다.
- unresolved/resolved thread에 `PEACEFUL_GROWTH`, `CHAR_VILLAIN_###`, 영어 운영 template이 없다.
- 모든 narration이 완전한 문장/수치로 끝나며 `BTC +1.` 형태가 없다.
- 성공 결과에는 Sentinel이 `npc`로 등장하거나 planner가 선택을 명시적으로 해제한 근거가 있다.
- persist/image는 STEP 4 quality status가 pass일 때만 실행된다.
