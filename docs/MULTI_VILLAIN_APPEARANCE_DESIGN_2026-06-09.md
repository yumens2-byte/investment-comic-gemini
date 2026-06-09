# 다중 빌런 출몰 분석 및 설계 (2026-06-09)

## 1. 목적

현재 프로젝트는 히어로는 `ALLIANCE` 시나리오에서 2명까지 동시 출몰할 수 있지만, 빌런은 `villain_id` / `primary_villain` 1명 중심으로 설계되어 있다. 이 문서는 **빌런도 다중 출몰 가능**하도록 현재 제한 지점을 분석하고, 후방 호환을 유지하면서 단계적으로 `primary villain + support/shadow villains` 구조로 확장하는 설계를 정의한다.

## 2. 현재 구조 요약

| 영역 | 현재 동작 | 다중 빌런 관점의 제한 |
| --- | --- | --- |
| Canon | 히어로 5명, 빌런 6명 후보 풀 보유 | 후보 풀은 충분하나 선택 결과는 단일 빌런 중심 |
| 기본 선택 | `select_characters_for_event()`가 `(hero_id, villain_id)` 단일 튜플 반환 | 빌런 후보 점수/랭킹을 복수로 보존하지 않음 |
| Scenario v2 | `NO_BATTLE`, `ONE_VS_ONE`, `ALLIANCE` | `ALLIANCE`도 히어로 2명 + 빌런 1명 구조 |
| Appearance v2 | 모든 빌런 후보를 점수화한 뒤 top 1만 `primary_villain`으로 채택 | `all_candidates`에는 후보가 남지만 최종 출몰 리스트가 없음 |
| Battle | `battle()` / `battle_alliance()` 모두 `villain_id: str` 1개와 `villain_base` 1개 입력 | 다중 빌런 파워 합산·시너지·감쇠 모델 없음 |
| Prompt | `build_active_character_cards()`가 `villain_id` 1개만 받음 | 빌런 active card를 복수로 주입할 수 없음 |
| Story beat | `build_story_beat_plan()`이 `villain_id` 1개만 받음 | 패널별 다중 빌런 배치/역할 구분이 없음 |
| Persist/trace | `selected_villain_id`, `primary_villain` 중심 | `selected_villain_ids`, `support_villains` 계열 필드 필요 |

## 3. 설계 목표

1. **MVP 최대치**: 한 에피소드에서 빌런 최대 2명까지 동시 출몰한다.
   - `primary_villain`: 전투/서사의 주 압력.
   - `support_villain`: 같은 날 동시에 감지된 보조 압력.
2. **확장 최대치**: 시각·서사 안정성을 위해 기본 운영 최대는 빌런 2명으로 두고, `MULTI_VILLAIN_MAX=3` 플래그를 통해 3명까지 실험 가능하게 한다.
3. **후방 호환**: 기존 `villain_id`, `primary_villain`, `selected_villain_id`는 유지하고, 신규 리스트 필드를 추가한다.
4. **결정론 유지**: Claude/Gemini가 임의로 빌런을 추가하지 않도록 출몰 빌런 리스트와 역할을 코드에서 확정한다.
5. **시각 혼잡도 제어**: 히어로 2명 + 빌런 2명 + 중립 1명 이상이 동시에 한 컷에 몰리지 않도록 패널 배치 규칙을 둔다.

## 4. 권장 최대 출몰 수

### 4.1 메인 전투 캐릭터

| 시나리오 | 현재 최대 | 다중 빌런 설계 후 MVP | 비고 |
| --- | ---: | ---: | --- |
| `NO_BATTLE` | 히어로 1 + 빌런 0 | 히어로 1 + 빌런 0 | 전투 없음 유지 |
| `ONE_VS_ONE` | 히어로 1 + 빌런 1 | 히어로 1 + 빌런 1 | 기본형 유지 |
| `ALLIANCE` | 히어로 2 + 빌런 1 | 히어로 2 + 빌런 1~2 | 고위험 복합 충격에서만 2빌런 허용 |
| 신규 `VILLAIN_PACT` | 없음 | 히어로 2 + 빌런 2 | 다중 빌런 전용 시나리오로 권장 |

### 4.2 게스트 포함 활성 캐릭터

MVP 권장 상한은 **총 5명**이다.

```text
히어로 2명 + 빌런 2명 + 중립/게스트 1명 = 5명
```

기존에는 히어로 2명 + 빌런 1명 + 중립 2명 = 5명이 최대였다. 다중 빌런 설계에서는 장면 혼잡을 피하기 위해 빌런이 2명 출몰하는 날에는 중립 게스트를 1명으로 제한하는 것이 안전하다.

## 5. 신규 데이터 모델

### 5.1 CharacterSelectionResult 확장

현재 `primary_villain` 단일 필드를 유지하면서 아래 필드를 추가한다.

```python
@dataclass(frozen=True)
class CharacterSelectionResult:
    primary_villain: str | None
    support_villains: list[str]
    villain_roles: dict[str, str]
    villain_selection_reason: dict[str, str]

    @property
    def villains(self) -> list[str]:
        return [v for v in [self.primary_villain, *self.support_villains] if v]
```

권장 role:

| role | 의미 | 전투 반영 |
| --- | --- | --- |
| `PRIMARY_THREAT` | 오늘의 핵심 빌런 | 100% 파워 반영 |
| `SECONDARY_THREAT` | 보조 빌런 / 복합 리스크 | 55~70% 감쇠 반영 |
| `SHADOW_SIGNAL` | 컷 말미 예고/배후 | 전투 미반영, prompt/next hook만 반영 |

### 5.2 ctx / DB JSON 필드

`analysis_ctx_json` 및 `character_selection`에 아래 필드를 추가한다.

```json
{
  "villain_id": "CHAR_VILLAIN_004",
  "villain_ids": ["CHAR_VILLAIN_004", "CHAR_VILLAIN_001"],
  "character_selection": {
    "primary_villain": "CHAR_VILLAIN_004",
    "support_villains": ["CHAR_VILLAIN_001"],
    "villains": ["CHAR_VILLAIN_004", "CHAR_VILLAIN_001"],
    "villain_roles": {
      "CHAR_VILLAIN_004": "PRIMARY_THREAT",
      "CHAR_VILLAIN_001": "SECONDARY_THREAT"
    }
  }
}
```

후방 호환 원칙:

- `villain_id`는 항상 `villain_ids[0]`와 동일하게 유지한다.
- `selected_villain_id`는 기존 대시보드/요약용으로 유지한다.
- 신규 요약에는 `selected_villain_ids`를 추가한다.
- 기존 템플릿이 리스트를 모르더라도 최소 1빌런 서사는 유지되어야 한다.

## 6. 다중 빌런 선택 알고리즘

### 6.1 후보 점수화

`character_appearance_engine.score_villain()`은 이미 6개 빌런 후보를 모두 점수화할 수 있으므로, MVP에서는 이 결과를 재사용한다.

선택 규칙:

1. `NO_BATTLE`이면 `villains=[]`.
2. `ONE_VS_ONE`이면 기존처럼 top 1만 사용한다.
3. `ALLIANCE` 또는 신규 `VILLAIN_PACT`에서만 top 2를 검토한다.
4. 2번째 빌런은 아래 조건을 모두 만족할 때만 출몰한다.
   - `score >= VILLAIN_SUPPORT_THRESHOLD`.
   - primary와 점수 차이가 `VILLAIN_SUPPORT_MAX_GAP` 이하.
   - primary와 market domain이 중복되지 않거나, 중복되더라도 story role이 다르다.
   - 최근 2회 연속 같은 보조 빌런이면 감쇠 또는 제외한다.

권장 상수:

```python
VILLAIN_PRIMARY_THRESHOLD = 60
VILLAIN_SUPPORT_THRESHOLD = 50
VILLAIN_SUPPORT_MAX_GAP = 25
MULTI_VILLAIN_MAX_DEFAULT = 2
```

### 6.2 도메인 중복 제어

다중 빌런은 “복합 리스크”를 표현해야 하므로 같은 원인만 반복하지 않게 한다.

| 빌런 | 대표 도메인 | 동시 출몰 예시 |
| --- | --- | --- |
| Debt Titan | rates / debt | Volatility Hydra와 동시: 금리+변동성 복합 충격 |
| Oil Shock Titan | commodity / inflation | War Dominion과 동시: 지정학+유가 충격 |
| Liquidity Leviathan | liquidity / credit | Debt Titan과 동시: 유동성+금리 압박 |
| Volatility Hydra | volatility / equity stress | Algorithm Reaper와 동시: 변동성+기계적 매도 |
| Algorithm Reaper | quant / momentum | Volatility Hydra와 동시: VIX 급등+나스닥 급락 |
| War Dominion | geopolitics / risk-off | Oil Shock Titan과 동시: 전쟁 리스크+원유 급등 |

## 7. Battle 계산 설계

### 7.1 신규 함수: `battle_multi_villain()`

기존 `battle_alliance()`를 유지하고, 다중 빌런 전용 함수를 추가한다.

```python
def battle_multi_villain(
    hero_ids: list[str],
    hero_bases: list[int],
    villain_ids: list[str],
    villain_bases: list[int],
    market_context: dict,
    arc_context: dict,
) -> BattleResult:
    ...
```

`BattleResult`는 후방 호환 때문에 `villain_id`를 primary로 유지하고, `to_dict()`에 확장 필드를 추가한다.

```json
{
  "hero_id": "CHAR_HERO_001",
  "villain_id": "CHAR_VILLAIN_004",
  "villain_ids": ["CHAR_VILLAIN_004", "CHAR_VILLAIN_001"],
  "villain_power_breakdown_by_id": {
    "CHAR_VILLAIN_004": {"base": 72, "vix_spike": 12},
    "CHAR_VILLAIN_001": {"base": 70, "rate_pressure": 10, "support_decay": -24}
  }
}
```

### 7.2 파워 합산식

권장 MVP 산식:

```text
primary_villain_power = calc_villain_power(primary) * 1.00
support_villain_power = calc_villain_power(support) * 0.60
villain_pact_bonus = 0~10  # 도메인이 서로 다르고 모두 임계 초과 시
villain_power = primary_villain_power + support_villain_power + villain_pact_bonus
```

상한:

```text
villain_power <= int(primary_villain_power * 1.75)
```

이 상한이 필요한 이유:

- 빌런 2명의 base power를 단순 합산하면 히어로 2명 연합을 항상 압도할 수 있다.
- `ALLIANCE`의 1.25 빌런 강화와 중복되면 밸런스가 급격히 붕괴한다.
- 다중 빌런은 “더 강한 적”이 아니라 “복합 원인”을 보여주는 장치여야 한다.

### 7.3 Outcome 확장

기존 outcome은 유지하되, 다중 빌런 전용 outcome tag를 별도 필드로 둔다.

```json
{
  "outcome": "DRAW",
  "encounter_type": "MULTI_VILLAIN",
  "villain_pact_state": "DUAL_PRESSURE"
}
```

권장 `villain_pact_state`:

| 값 | 의미 |
| --- | --- |
| `NONE` | 단일 빌런 |
| `DUAL_PRESSURE` | 2빌런 동시 압박 |
| `SHADOW_BACKER` | 2번째 빌런은 전투보다 배후/예고 역할 |
| `PACT_BREAK` | 두 빌런의 이해관계 충돌로 시너지 약화 |

## 8. Prompt / Story 설계

### 8.1 Active character cards

`build_active_character_cards()`는 아래처럼 확장한다.

```python
def build_active_character_cards(
    *,
    canon: dict,
    hero_ids: list[str],
    villain_id: str | None = None,
    villain_ids: list[str] | None = None,
    neutral_guest_ids: list[str] | None = None,
) -> list[dict]:
    ordered_ids = [*hero_ids]
    ordered_ids.extend(villain_ids or ([villain_id] if villain_id else []))
    ordered_ids.extend(neutral_guest_ids or [])
```

### 8.2 Story beat plan

`build_story_beat_plan()`은 `villain_id` 단일 인자를 유지하되, 신규 `villain_ids`를 선택 인자로 추가한다.

권장 패널 배치:

| 패널 | 다중 빌런 배치 |
| --- | --- |
| P1 Hook | primary villain의 징후만 암시 |
| P2 Market Cause | secondary villain을 데이터 원인으로 소개 |
| P3 Character Reaction | 히어로가 복합 압력을 인식 |
| P4 Conflict | primary villain 정면 충돌 |
| P5 Turning Point | secondary villain이 압력을 증폭 또는 배신 |
| P6 Outcome | 결과는 deterministic battle_result 고정 |
| P7 Next Hook | shadow/backer가 있으면 예고만 |
| P8 Disclaimer | 캐릭터 없음 또는 최소화 |

필수 규칙:

- 한 패널에 `히어로 2 + 빌런 2 + 게스트 1` 전원을 동시에 넣지 않는다.
- P4/P5만 2빌런 동시 컷을 허용한다.
- `support_villain`은 primary보다 큰 대사량을 갖지 않는다.
- Claude에게 “새 빌런 추가 금지, 제공된 villain_ids만 사용”을 명시한다.

## 9. 이미지/슬라이드 안전 규칙

다중 빌런은 이미지 생성 실패와 캐릭터 혼선을 키우므로 아래 규칙을 둔다.

1. **구도 제한**: 2빌런 컷은 와이드/분할 구도 또는 좌우 레이어로 제한한다.
2. **시선 법칙**: 기존 `hero_left, villain_right`를 유지하되, secondary villain은 후경 또는 상단 실루엣으로 배치한다.
3. **색상 충돌 방지**: primary villain의 대표 색을 전경, secondary villain은 보조 aura로 표현한다.
4. **REF 우선순위**: active character cards 순서는 `heroes → primary villain → support villains → neutral guests`로 고정한다.
5. **fallback**: 이미지 프롬프트가 너무 길면 support villain은 “background omen”으로 축약한다.

## 10. 구현 단계

### Phase A — Trace/Prompt 준비

1. `CharacterSelectionResult`에 `support_villains`, `villains`, `villain_roles` 추가.
2. `resolve_character_selection()`에서 top 2 빌런 후보를 선택하되, feature flag `MULTI_VILLAIN_ENABLED=false` 기본값 유지.
3. `ctx`에 `villain_ids` 추가. `villain_id = villain_ids[0]` 유지.
4. `build_active_character_cards()`에 `villain_ids` 선택 인자 추가.
5. 테스트: 단일 빌런 기존 테스트가 깨지지 않는지 확인.

### Phase B — Story/Persist 확장

1. `build_story_beat_plan()`에 `villain_ids` 선택 인자 추가.
2. `character_selection` persistence summary에 `selected_villain_ids` 추가.
3. `analysis_ctx_json` 저장 payload에 `villain_ids` 포함.
4. Prompt fallback 블록에 “Multiple Villain Rules” 추가.
5. 테스트: 다중 빌런 trace와 prompt card 순서 검증.

### Phase C — Battle 산식 도입

1. `battle_multi_villain()` 추가.
2. `BattleResult.to_dict()` 확장 또는 `MultiVillainBattleResult` 도입.
3. `run_market.py`에서 `len(villain_ids) > 1`이면 다중 빌런 battle 경로 사용.
4. Phase 2.3 modifier와 중복 적용되는 항목을 검토한다.
5. 테스트: 2빌런 파워 상한, support decay, outcome 안정성 검증.

### Phase D — 운영 실험

1. `MULTI_VILLAIN_ENABLED=true` + `MULTI_VILLAIN_MAX=2`로 staging 실행.
2. `CHARACTER_CANON_PROMPT_V2_ENABLED=true` 환경에서 active cards 길이와 이미지 프롬프트 길이 점검.
3. 10개 샘플 에피소드에서 장면 혼잡도, 빌런 식별성, 승패 밸런스 점검.
4. 운영 기준 통과 후 production flag 활성화.

## 11. 테스트 설계

| 테스트 파일 | 추가/변경 테스트 |
| --- | --- |
| `tests/test_character_appearance_engine.py` | `ALLIANCE`에서 support villain 1명이 threshold 충족 시 `villains`가 2개인지 검증 |
| `tests/test_character_canon_prompt.py` | `build_active_character_cards(villain_ids=[...])`가 빌런 카드 2개를 순서대로 반환하는지 검증 |
| `tests/test_battle_calc.py` | `battle_multi_villain()`이 support decay와 villain power cap을 적용하는지 검증 |
| `tests/test_prompt_tpl.py` | 다중 빌런 prompt fallback에 금지 규칙과 role이 포함되는지 검증 |
| `tests/test_character_selection_persistence.py` | `selected_villain_ids` 저장/요약 호환성 검증 |
| `tests/test_story_planner.py` | P4/P5에만 다중 빌런 동시 required character가 배치되는지 검증 |

## 12. 리스크 및 완화책

| 리스크 | 영향 | 완화책 |
| --- | --- | --- |
| 이미지 프롬프트 과밀 | 캐릭터가 섞이거나 누락됨 | 2빌런 컷을 P4/P5로 제한, support는 후경 처리 |
| 승패 밸런스 붕괴 | 히어로가 반복 패배 | support decay, villain power cap 적용 |
| 기존 DB/대시보드 호환성 저하 | 운영 도구가 `villain_id`만 읽음 | `villain_id`는 primary로 유지하고 리스트 필드만 추가 |
| Claude가 새 빌런을 임의 추가 | Canon/스토리 일관성 저하 | prompt에 “provided villain_ids only” 규칙 추가 |
| 같은 빌런 조합 반복 | 서사 피로도 | 최근 조합 cooldown 및 pair diversity 적용 |

## 13. 최종 권고

- **즉시 구현 권장 범위는 “2빌런 MVP”**이다.
- `VILLAIN_PACT`를 새 시나리오로 추가하되, 초기에는 `ALLIANCE` 내부 subtype으로 운영해도 된다.
- 기존 단일 필드(`villain_id`, `primary_villain`, `selected_villain_id`)는 절대 제거하지 않는다.
- 다중 빌런은 모든 위험일에 켜지지 않고, `HIGH risk + 복수 도메인 임계 초과`일 때만 발생해야 한다.
- 최종 운영 상한은 **히어로 2명 + 빌런 2명 + 중립 1명 = 총 5명**을 권장한다.
