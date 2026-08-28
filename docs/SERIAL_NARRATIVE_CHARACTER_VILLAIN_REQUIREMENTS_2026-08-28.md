# Invest Universe 연재 서사·캐릭터 로테이션·빌런 전달력 개선 요구사항 정의서

- 문서 버전: 1.0
- 작성일: 2026-08-28
- 상태: 구현 착수 전 요구사항 기준선
- 대상: 미국시장 8컷 투자 코믹의 `캐릭터 선택 → StoryBeatPlan → EpisodeScript → 이미지/발행` 구간
- 문제 제기: 스토리라인이 얕고 회차가 단편처럼 끊기며, 동작이 딱딱하고, 특정 “누나” 캐릭터가 반복 노출되고, 빌런의 정체·시장 의미가 독자에게 충분히 전달되지 않는다.

---

## 1. 목적과 제품 원칙

이 문서는 위 현상을 단순히 “프롬프트를 더 길게 쓰는 문제”로 취급하지 않는다. **연재 기억, 배역 편성, 적대자 설명, 장면 상태 전이**를 생성 파이프라인이 검증 가능한 계약으로 다루도록 제품 요구사항을 확정한다.

개선 후 한 회차는 다음 네 질문에 답해야 한다.

1. **왜 지금 이 인물이 주인공인가?** 시장 신호·장기 아크·최근 등장 이력으로 설명할 수 있어야 한다.
2. **빌런은 누구이며 무엇을 의미하는가?** 첫 독자도 이름, 시장 메커니즘, 위협, 약점을 이해해야 한다.
3. **이번 행동으로 무엇이 달라졌는가?** 각 컷의 목표·행동·반작용·대가가 다음 컷의 상태를 바꿔야 한다.
4. **다음 회차를 왜 봐야 하는가?** 이번 갈등 일부는 회수되고, 남은 질문은 다음 회차의 실제 사건으로 이어져야 한다.

### 1.1 핵심 원칙

- **시장 근거 우선:** 캐릭터 드라마는 사실을 설명하는 은유이며, 근거 없는 예측을 만들지 않는다.
- **연재는 반복이 아니라 누적:** 이전 회차의 상처, 관계, 획득 정보, 소품 상태와 빌런 계획이 다음 회차의 시작 조건이 된다.
- **배역 다양성은 무작위성이 아님:** 단순 순환이 아니라 적합도와 최근 과다 노출을 함께 계산한다.
- **빌런은 설명 카드가 아니라 인과의 주체:** 등장, 능력 시연, 메커니즘 설명, 대가를 장면 안에서 보여준다.
- **동작은 형용사가 아니라 상태 변화:** “역동적으로 공격” 대신 누가, 무엇을 위해, 무엇으로, 어디를, 어떤 반작용과 대가를 만들었는지 명시한다.

---

## 2. 현행 분석과 근본 원인

### 2.1 증상별 진단

| 독자 체감 | 현행 구조의 원인 | 제품 영향 |
|---|---|---|
| 매일 비슷한 단편 | 모든 사건이 고정 `HOOK → ... → NEXT_HOOK → DISCLAIMER` 8비트를 사용 | 사건 종류가 달라도 리듬과 결말이 동일하게 보임 |
| 누나 캐릭터 반복 | `NO_BATTLE`의 기본 분기가 `CHAR_HERO_002`이고, 지원 우선순위에도 반복 포함; 최근 노출량을 감점하는 계약 없음 | 세계관이 한 캐릭터 중심으로 축소되고 다른 영웅의 애착 형성 실패 |
| 빌런을 이해하기 어려움 | 계획의 `villain_motivation`이 “시장 근거로 압박” 수준이며 이름·메커니즘·목표·약점의 독자 노출을 보장하지 않음 | 전투 원인과 투자 정보가 분리되고 빌런 교체 시 혼란 발생 |
| 동작이 딱딱함 | `Panel.action`이 자유문장이고 전후 상태, 동작 단계, 접촉, 무게중심, 반응을 강제하지 않음 | 관련 포스터의 나열처럼 보이고 이미지 생성도 정적 포즈로 수렴 |
| 다음 화가 새 이야기처럼 시작 | 직전 hook 문자열 회수는 있으나 시즌 목표·중기 갈등·캐릭터별 상태의 진행 계약이 약함 | `NEXT_HOOK`이 예고 문구에 머물고 실제 payoff가 되지 않음 |
| 대립 관계가 흔들림 | 빌런-카운터 히어로 매핑이 모듈별로 다르고 canon과 불일치하는 항목 존재 | 동일 빌런에 대한 대표 라이벌과 관계 기억이 회차마다 바뀔 수 있음 |

### 2.2 확인된 구조적 결손

1. **편성 결손:** 캐릭터 점수에는 시장 적합성이 있으나 최근 5/10회 등장 비율, 연속 주연 횟수, 마지막 주연 이후 경과 회차, 미회수 개인 아크가 최종 선정의 공통 입력으로 강제되지 않는다.
2. **시리즈 결손:** `next_hook`과 최대 3개 thread는 존재하지만 `season_arc → mini_arc → episode` 계층, 에피소드별 약속/회수 기한, 실패 시 carry-over 정책이 없다.
3. **빌런 전달 결손:** 풍부한 canon belief와 trigger metric은 존재하지만 최종 대사·내레이션·행동에 어느 항목을 언제 노출할지 정하는 독자 인지 계약이 없다.
4. **퍼포먼스 결손:** 패널 스키마가 카메라와 자유문장 action만 받으므로 anticipation-impact-reaction-recovery 및 `exiting_state → entering_state` 연결을 검증할 수 없다.
5. **품질 측정 결손:** 생성 성공 여부와 별개로 배역 편중, 빌런 이해도, thread payoff, 행동 가독성을 발행 gate로 쓰지 않는다.

---

## 3. 목표, 비목표, 성공 지표

### 3.1 목표

- 3~6회 단위의 미니 아크가 누적되는 **연재형 이야기**를 만든다.
- 어떤 단일 영웅도 근거 없이 주연/지원 역할을 독점하지 않도록 한다.
- 첫 등장 또는 장기 미등장 빌런은 독자가 1회차 안에 핵심 정보를 이해하도록 한다.
- 패널마다 의도와 물리적 상태 변화가 보이는 동작을 만든다.
- 기존 시장 근거, 전투 결과 고정, 면책 고지와 발행 안정성을 유지한다.

### 3.2 비목표

- 시장 데이터와 무관한 판타지 장편을 만드는 것
- 모든 캐릭터를 한 회차에 균등 출연시키는 것
- 고정 전투 결과를 드라마를 위해 변경하는 것
- 실존 인물이나 실제 기관을 빌런으로 의인화하는 것
- 초기 단계에서 패널 수나 마지막 면책 패널을 변경하는 것

### 3.3 운영 KPI 및 품질 gate

| 지표 | 정의 | 목표/차단 기준 |
|---|---|---|
| `lead_share_10` | 최근 발행 10회 중 동일 영웅 주연 비율 | 기본 40% 이하; 50% 초과 시 신규 생성 차단 |
| `consecutive_lead` | 동일 영웅 연속 주연 횟수 | 기본 최대 2회; 근거 있는 `ARC_LOCK`만 최대 3회 |
| `cast_coverage_10` | 최근 10회 중 한 번 이상 유의미 역할을 가진 영웅 수 | 5명 중 4명 이상 |
| `villain_intro_completeness` | 이름/시장 현상/작동 방식/위협 중 노출 충족률 | 신규·60일 미등장 빌런 100%, 재등장 75% 이상 |
| `thread_payoff_rate_5` | 최근 5회에서 만기 thread 중 회수/의도적 연장 비율 | 80% 이상 |
| `serial_causality_score` | 이전 결과가 현재 시작 조건·선택·대가에 반영된 비율 | 85점 이상 |
| `action_readability_score` | 주체/동사/대상/단계/반작용/상태 전이 충족 점수 | 전투 컷 90점, 비전투 컷 80점 이상 |
| `static_pose_rate` | 행동 필수 패널 중 중립 자세 또는 접촉 불명확 비율 | 10% 이하 |

`ARC_LOCK`은 시장 적합도, 미니 아크상 필수성, 종료 회차를 포함한 사유 코드가 있을 때만 허용하며 운영 로그에 남긴다.

---

## 4. 사용자/독자 요구사항

### UR-01 신규 독자 이해

신규 독자로서 나는 사전 설정집 없이도 이번 회차의 주인공, 빌런, 시장 갈등을 이해하고 싶다.

**수용 기준**

- 표지~3컷 안에 주연의 역할과 갈등 대상이 시각 또는 대사로 식별된다.
- 신규/장기 미등장 빌런은 4컷 이전에 이름과 시장 현상이 함께 제시된다.
- 빌런 정보는 숫자만 나열하지 않고 “지표 변화 → 시장 작동 → 영웅에게 생긴 물리적/전술적 제약”으로 표현한다.

### UR-02 기존 독자 보상

기존 독자로서 나는 지난 회차의 선택과 손실이 사라지지 않고 다음 사건에 영향을 주길 원한다.

**수용 기준**

- 1~2컷 중 적어도 한 컷은 이전 회차의 구체적 결과를 현재 상태로 보여준다.
- 이전 `next_hook`은 그대로 언급하는 것만으로 회수 처리하지 않는다. 사건, 정보, 선택 중 하나로 변환되어야 한다.
- 시즌/미니 아크의 진행 단계가 회차 종료 시 실제로 전진하거나, 지연 사유와 새 만기를 기록한다.

### UR-03 다양한 캐릭터 애착

독자로서 나는 특정 캐릭터만 반복해서 보기보다 시장 상황에 맞는 여러 영웅의 능력과 약점을 보고 싶다.

**수용 기준**

- 최근 노출 제한을 위반한 캐릭터가 선정되면 대체 후보와 점수 차, 예외 사유가 기록된다.
- 지원 캐릭터는 배경 장식이 아니라 최소 한 번 `DECISION`, `ACTION`, `CONSEQUENCE` 중 하나를 담당해야 유의미 등장으로 집계한다.

### UR-04 살아 있는 전투와 대화

독자로서 나는 포즈를 취한 인물보다 행동하고 반응하는 인물을 보고 싶다.

**수용 기준**

- 연속 행동 장면은 최소 `ANTICIPATION → IMPACT/REVEAL → REACTION/RECOVERY`의 3단계를 가진다.
- 각 단계는 동일 행동을 다른 카메라로 반복하지 않고 상태를 변화시킨다.
- 대화 장면도 손동작, 시선 회피/교환, 자리 이동, 소품 조작 중 하나로 관계 변화를 시각화한다.

---

## 5. 기능 요구사항

### 5.1 연재 아크 계약

#### FR-ARC-01 아크 계층

시스템은 아래 3계층을 저장·조회해야 한다.

```yaml
season_arc:
  arc_id: SEASON_2026_H2
  dramatic_question: "회복 시스템은 연쇄 충격을 견딜 수 있는가?"
  status: ACTIVE
  target_episode_range: [12, 24]
mini_arc:
  mini_arc_id: MA_004
  premise: "유동성 봉쇄의 근원을 추적한다"
  primary_villain: CHAR_VILLAIN_003
  planned_length: 4
  current_phase: ESCALATION
  completion_condition: "봉쇄 메커니즘과 우회 비용이 모두 드러남"
episode_contract:
  episode_role: COMPLICATION
  promise_to_payoff: "지난 화의 끊긴 자금 경로 정체 공개"
  due_threads: [THREAD_031]
  new_threads_limit: 1
```

#### FR-ARC-02 미니 아크 진행

- 미니 아크 기본 길이는 3~6회로 한다.
- 단계는 `SETUP → ESCALATION → REVERSAL → COST/PAYOFF`를 기본으로 하되 시장 급변 시 `PIVOT`을 허용한다.
- 같은 단계가 2회 연속 유지되면 두 번째 회차는 새로운 정보, 관계 변화 또는 비가역적 비용을 반드시 만들어야 한다.
- `PIVOT`은 기존 갈등 삭제가 아니라 보류/흡수/종결 중 하나로 이전 thread의 상태를 기록해야 한다.

#### FR-ARC-03 Thread 원장

각 thread는 자유문장 배열이 아니라 다음 필드를 가진다.

```yaml
thread_id: THREAD_031
type: MYSTERY       # MYSTERY | RELATIONSHIP | INJURY | DEBT | VILLAIN_PLAN | PROP
setup_episode_id: ICG-2026-08-27-001
setup_panel_idx: 7
owner_character_ids: [CHAR_HERO_004]
promise: "사라진 유동성 경로의 배후를 밝힌다"
status: DUE         # OPEN | DUE | PAID | EXTENDED | ABANDONED
payoff_due_in: 2
payoff_episode_id: null
extension_reason: null
```

- 회차당 신규 thread는 기본 1개, 최대 2개다.
- `DUE` thread를 무시한 스크립트는 hard fail이다.
- `EXTENDED`는 새로운 단서와 새 만기를 모두 요구한다.
- `ABANDONED`는 운영자 승인과 독자에게 납득 가능한 종결 장면을 요구한다.

#### FR-ARC-04 에피소드 인과성

각 회차는 `previous_consequence`, `current_trigger`, `irreversible_change`, `next_pressure`를 가져야 한다. 네 항목 중 `previous_consequence` 또는 `irreversible_change`가 비어 있으면 발행할 수 없다.

---

### 5.2 캐릭터 로테이션과 역할 분배

#### FR-CAST-01 단일 선정 서비스

모든 시나리오는 동일한 `CharacterCastingService` 결과를 사용해야 하며, 모듈별 fallback/상극 매핑을 중복 보유하지 않는다. canon의 `mirror_villain`/`mirror_hero`를 단일 원본으로 사용하고 시작 시 양방향 정합성을 검증한다.

#### FR-CAST-02 선정 점수

주연 점수는 최소 다음 요소를 포함한다.

```text
lead_score = market_fit(0..50)
           + arc_relevance(0..25)
           + unresolved_personal_stake(0..15)
           + relationship_payoff(0..10)
           + absence_bonus(0..15)
           - recent_lead_penalty(0..35)
           - consecutive_penalty(0..30)
```

- 시장 적합성이 1순위이나 동점/근소 차(기본 10점 이내)에서는 노출이 적은 캐릭터를 우선한다.
- `NO_BATTLE`의 중립 fallback을 특정 캐릭터로 고정하지 않는다. 관찰 역량, 진행 중 개인 아크, 최근 노출을 함께 평가한다.
- 선정 결과는 후보별 점수, 제외 이유, 예외 사유를 저장한다.

#### FR-CAST-03 역할 예산

한 회차의 권장 활성 배역은 주연 1, 조연 0~1, 주 빌런 0~1, 보조 빌런 0~1이다. 각 등장 인물은 다음 중 하나의 고유 역할을 가져야 한다.

- `LEAD_DECISION`: 핵심 선택
- `COUNTERPOINT`: 주연 믿음에 반론
- `SPECIALIST_ACTION`: 고유 능력으로 상태 변경
- `EMOTIONAL_WITNESS`: 대가를 목격하고 관계 변화 유발
- `ANTAGONIST_AGENT`: 빌런 계획 수행

역할 없는 카메오를 생성하지 않는다. 같은 회차에서 두 캐릭터가 동일 설명을 반복하지 않는다.

#### FR-CAST-04 편중 예외

동일 영웅 3회 연속 주연은 다음을 모두 만족할 때만 가능하다.

1. 활성 미니 아크의 owner다.
2. 다른 후보로 대체하면 진행 중 thread payoff가 불가능하다.
3. 세 번째 회차가 해당 주연 구간의 payoff 또는 퇴장 회차다.
4. `ARC_LOCK` 사유와 해제 회차가 저장된다.

---

### 5.3 빌런 정보 전달 계약

#### FR-VIL-01 Villain Reader Card

활성 빌런마다 생성 시점에 다음 정보를 구조화한다.

```yaml
villain_reader_card:
  char_id: CHAR_VILLAIN_003
  display_name_ko: 리퀴디티 레비아탄
  market_phenomenon: "자금 흐름 경색"
  trigger_evidence_ids: [metric:HY_SPREAD, metric:DXY]
  mechanism: "위험 자금의 조달 비용을 높이고 이동 경로를 좁힌다"
  immediate_goal: "영웅의 방어망으로 들어오는 자금 경로 봉쇄"
  signature_threat: "네 개의 머리가 서로 다른 자금 통로를 잠근다"
  limitation_or_weakness: "막힌 자금은 우회 경로를 찾으며 머리 간 통제가 갈라진다"
  reader_familiarity: NEW
```

`immediate_goal`은 시장 결과를 의인화하되 사실 근거 밖의 실제 음모를 주장해서는 안 된다.

#### FR-VIL-02 단계적 노출

신규 또는 60일 이상 미등장 빌런은 한 회차 안에서 다음 순서를 충족한다.

1. **SIGNATURE:** 실루엣/효과/피해로 정체를 암시한다.
2. **IDENTITY:** 이름과 대응 시장 현상을 명시한다.
3. **MECHANISM:** 능력이 시장과 영웅에게 어떻게 작동하는지 보여준다.
4. **STAKES:** 막지 못할 경우의 구체적 결과를 제시한다.

재등장 빌런은 `IDENTITY`를 짧게 하고 기존 계획의 진전 또는 새로운 전술을 반드시 보여준다. canon 설정 전체를 매번 반복하지 않는다.

#### FR-VIL-03 정보 배치

- 한 패널에 새 빌런 개념은 최대 1개다.
- 설명은 최소 2개 채널을 사용한다: 시각 은유, 대사, 내레이션, 시장 수치 overlay.
- 빌런 자기소개 독백만으로 completeness를 충족한 것으로 판정하지 않는다.
- 자연현상형 빌런은 의도·음모를 부여하지 않고 `현상 → 발현 조건 → 약화 조건`으로 설명한다.

#### FR-VIL-04 다중 빌런 구분

- 주 빌런은 원인/결정, 보조 빌런은 증폭/방해 중 하나만 담당한다.
- 두 빌런은 서로 다른 시각 실루엣, 시장 도메인, 행동 동사를 가져야 한다.
- 8컷에서 신규 빌런 2명을 동시에 완전 소개하지 않는다. 보조 빌런이 신규면 teaser만 허용하고 다음 회차 thread로 등록한다.

---

### 5.4 에피소드 구조 다양화

#### FR-STORY-01 아키타입 선택

고정 비트 하나 대신 사건과 아크 단계에 따라 아래 아키타입을 사용한다.

| 아키타입 | 적합 조건 | 1~7컷 핵심 흐름 |
|---|---|---|
| `VILLAIN_REVEAL` | 신규 빌런/정체 공개 | 피해 → 단서 → 시그니처 → 정체 → 메커니즘 → 첫 대가 → 추적 약속 |
| `CHASE_AND_DISCOVERY` | 열린 mystery 추적 | 잔상 → 추적 선택 → 장애 → 잘못된 가설 → 발견 → 비용 → 더 큰 문 |
| `TACTICAL_REVERSAL` | 전투 escalation/reversal | 계획 → 준비 → 첫 성공 → 역카운터 → 희생 선택 → 불완전 결과 → 후유증 |
| `AFTERMATH_AND_RIFT` | 전투 직후/관계 thread | 손상 확인 → 책임 공방 → 숨은 비용 → 관계 균열 → 선택 → 새 규칙 → 잔여 갈등 |
| `DATA_MYSTERY` | NO_BATTLE/INTEL | 이상 신호 → 가설 → 검증 → 반증 → 재해석 → 감시 조건 → 다음 체크포인트 |
| `TEAM_SPOTLIGHT` | 로테이션/조연 payoff | 주연 한계 → 조연 관찰 → 역할 충돌 → 협력 실험 → 고유 행동 → 관계 변화 → 새 책임 |

8컷은 면책으로 유지한다. 최근 3회 내 동일 아키타입은 최대 2회 사용하며, 2회째는 다른 `episode_role`이어야 한다.

#### FR-STORY-02 장면 목적

1~7컷은 각각 `INFORMATION`, `DECISION`, `ACTION`, `CONSEQUENCE`, `RELATIONSHIP`, `PAYOFF`, `SETUP` 중 하나의 주 목적을 가진다. `INFORMATION`만 2컷 이상 연속할 수 없고, 최소 한 컷은 `DECISION`, 최소 한 컷은 `CONSEQUENCE`여야 한다.

#### FR-STORY-03 캐릭터 내적 진행

주연의 canon `want/need/fear/lie/truth` 중 이번 미니 아크가 시험할 한 쌍을 선택한다. 한 회차에서 완전 성장시키지 않고 다음 단계 중 하나만 이동한다.

`BELIEF_ASSERTED → BELIEF_TESTED → COST_PAID → CONTRADICTION_SEEN → CHOICE_CHANGED`

현재 단계와 이를 증명한 패널을 저장한다. 대사로 선언만 한 변화는 인정하지 않는다.

---

### 5.5 동작·퍼포먼스 계약

#### FR-ACT-01 패널 상태 전이

행동/관계 패널은 다음 계약을 가진다.

```yaml
performance:
  entering_state: "방패가 유동성 사슬에 묶여 왼팔을 쓸 수 없음"
  subject: CHAR_HERO_002
  objective: "동료에게 우회 경로를 열어 준다"
  tactic: "소총 반동으로 사슬 고정점을 비튼다"
  action_phase: IMPACT
  verb: "오른손 소총 개머리판으로 고정점을 내려친다"
  target: "사슬 고정점"
  contact_point: "개머리판과 바닥 앵커"
  body_mechanics: "오른발 전방, 무게중심 아래, 상체 좌회전"
  reaction: "앵커가 꺾이며 반동으로 오른쪽 어깨가 밀린다"
  exiting_state: "왼팔은 풀리지만 소총을 놓친 상태"
  cost: "다음 패널에서 원거리 공격 불가"
```

`exiting_state`는 다음 패널 `entering_state`와 호환되어야 하며, 소품·부상·위치가 설명 없이 복구되면 hard fail이다.

#### FR-ACT-02 행동 단계

- 전투/추격 묶음은 3개 이상 패널에서 `ANTICIPATION`, `ACTION/IMPACT`, `REACTION/RECOVERY`를 포함한다.
- 한 패널은 핵심 동작 단계 하나만 표현한다.
- `IMPACT`에는 접촉점 또는 명시적 비접촉 효과 경로가 필요하다.
- `REACTION`에는 원인과 반응 방향이 필요하다.
- 대화 장면은 `blocking_change`(접근, 이탈, 가로막기, 소품 건네기 등)를 사용한다.

#### FR-ACT-03 카메라 호환성

- 전신 역학/발 위치가 중요하면 `CLOSE_UP`을 금지한다.
- 접촉 장면은 주체, 대상, 접촉점이 같은 프레임에 보여야 한다.
- 화면 축을 넘으면 중립 컷 또는 `axis_cross_reason`이 필요하다.
- 같은 행동을 카메라만 바꿔 두 번 생성하는 것을 금지한다.

#### FR-ACT-04 이미지 실패 완화

상호작용 필수 패널에서 기술 재시도를 위해 빌런 또는 조연을 삭제하지 않는다. 완화 순서는 `배경 단순화 → 이펙트 감소 → 카메라 단순화 → 수동 검토 격리`로 한다.

---

### 5.6 검증, 발행 gate, 관측성

#### FR-QA-01 생성 전 검증

다음 오류는 스크립트 또는 이미지 생성 전에 차단한다.

- 최근 주연 점유율/연속 주연 제한 위반 및 유효한 예외 없음
- canon과 다른 빌런-히어로 mirror 관계
- 신규 빌런 reader card 또는 필수 소개 단계 누락
- 만기 thread 미회수 및 연장 계약 없음
- 이전 패널 상태와 다음 패널 상태 불일치
- 행동 필수 패널의 subject/verb/target 또는 reaction 누락
- 고정 시장 근거/전투 결과 변경

#### FR-QA-02 생성 후 검증

이미지 QA는 identity, 인물 수, action phase, 접촉/시선, 해부학, 소품 상태, 빌런 실루엣, 자막 공간을 검사한다. 의미 실패는 API 성공과 별도로 `QUALITY_REPAIR` 또는 `MANUAL_REVIEW` 상태로 보낸다.

#### FR-QA-03 에피소드 품질 레코드

```yaml
episode_quality:
  casting:
    lead_share_10: 0.3
    consecutive_lead: 1
    exception_code: null
  serial:
    due_threads: [THREAD_031]
    paid_threads: [THREAD_031]
    serial_causality_score: 92
  villain:
    intro_mode: FULL
    completeness: 1.0
    missing_fields: []
  performance:
    readability_score: 94
    state_transition_errors: []
  publish_decision: PASS
```

대시보드는 캐릭터별 최근 5/10/20회 주연·지원 비율, 아키타입 사용률, 빌런별 마지막 등장일, 열린 thread와 만기, 품질 repair율을 제공해야 한다.

---

## 6. 비기능 요구사항

### NFR-01 결정 가능성과 재현성

동일 snapshot, arc state, continuity window와 설정 버전은 동일한 편성 점수 및 hard validation 결과를 만들어야 한다. LLM은 후보 점수나 gate 판정을 임의 변경할 수 없다.

### NFR-02 하위 호환성

- 기존 EpisodeScript/DB 레코드는 adapter로 읽을 수 있어야 한다.
- 신규 필드는 feature flag 아래 shadow 기록부터 시작한다.
- 기존 면책, factuality guardrail, fixed outcome 검증을 약화하지 않는다.

### NFR-03 비용과 지연

- 편성/아크/thread 검증은 로컬 결정론 로직으로 처리한다.
- 추가 LLM pass는 기본 1회를 넘지 않으며, 가능한 경우 기존 story generation 응답의 구조화 필드로 받는다.
- 품질 repair는 패널별 최대 2회 후 수동 검토로 격리한다.

### NFR-04 설명 가능성

운영자는 “왜 누나가 또 나왔는가/왜 나오지 않았는가”, “왜 이 빌런인가”, “왜 발행이 막혔는가”를 저장된 점수·근거·사유 코드로 답할 수 있어야 한다.

---

## 7. 우선순위와 구현 단계

### P0 — 편중과 단편성 즉시 차단

1. canon 기반 단일 mirror mapping과 시작 시 정합성 검사
2. 최근 10회 주연 이력, 연속 주연 penalty, `ARC_LOCK` 예외 계약
3. thread ID/만기/회수 원장과 `DUE` hard gate
4. Villain Reader Card 및 신규 빌런 4단계 소개 검증
5. `entering_state/exiting_state/cost`와 action grammar 필수화

### P1 — 연재와 연출 품질 확장

1. 시즌/미니 아크/회차 계층 및 단계 전이
2. 6개 episode archetype과 최근 사용 중복 제한
3. 캐릭터 belief progression 및 역할 예산
4. 생성 후 퍼포먼스/빌런 실루엣 Vision QA

### P2 — 운영 최적화

1. 품질 대시보드와 독자 이해도 표본 평가
2. 점수 가중치 A/B 및 캐릭터별 노출 목표 조정
3. 장기 아크 자동 제안(승인은 운영자)

---

## 8. 테스트 및 인수 시나리오

### AC-01 누나 연속 노출 제어

**Given** `CHAR_HERO_002`가 최근 2회 연속 주연이고 시장 적합도 45점, 다른 영웅이 40점이다.  
**When** 다음 NO_BATTLE 편성을 계산한다.  
**Then** 최근 노출 penalty 후 대체 영웅을 주연으로 선택한다. 활성 thread상 교체 불가하면 종료 회차가 있는 `ARC_LOCK`을 남긴다.

### AC-02 압도적 시장 적합성 예외

**Given** 동일 영웅이 2회 연속 주연이지만 신규 충격에 대한 시장 적합도 격차가 20점 이상이다.  
**When** 편성을 계산한다.  
**Then** 3회째 선정을 허용할 수 있으나 payoff/퇴장 역할과 해제 회차를 강제한다.

### AC-03 신규 빌런 소개

**Given** 리퀴디티 레비아탄이 처음 등장한다.  
**When** 스크립트를 생성한다.  
**Then** 4컷 이전에 이름과 자금 경색 현상이 나오고, 능력 작동과 영웅의 제약이 시각화되며, 실패 결과가 제시된다. 하나라도 없으면 repair한다.

### AC-04 자연현상형 빌런 정확성

**Given** 오일 쇼크 타이탄이 활성화된다.  
**When** 빌런 동기를 만든다.  
**Then** 음모나 의도를 발명하지 않고 가격 임계 발현, 피해, 회귀 시 약화 조건으로 설명한다.

### AC-05 이전 hook의 실질 회수

**Given** 이전 hook이 “끊긴 자금 경로에서 두 번째 신호가 잡힌다”다.  
**When** 다음 회차를 만든다.  
**Then** 단순 복창이 아니라 신호의 발견이 현재 trigger/선택/결과 중 하나를 바꾸고 해당 thread가 `PAID` 또는 근거 있는 `EXTENDED`가 된다.

### AC-06 행동 연속성

**Given** P4에서 방패가 깨지고 P5에서 주인공이 반격한다.  
**When** 상태 전이를 검증한다.  
**Then** P5는 깨진 방패 상태를 유지하고 다른 전술 또는 대가를 사용해야 한다. 온전한 방패가 설명 없이 나오면 hard fail이다.

### AC-07 조연의 유의미한 등장

**Given** `TEAM_SPOTLIGHT`에 지원 영웅이 배정된다.  
**When** 회차 품질을 계산한다.  
**Then** 지원 영웅이 고유 `SPECIALIST_ACTION`으로 상태를 바꾸거나 관계 선택을 만들지 못하면 등장 집계에서 제외되고 스크립트를 repair한다.

### AC-08 다중 빌런 인지 부하

**Given** 주 빌런은 재등장이고 보조 빌런은 신규다.  
**When** 8컷 회차를 계획한다.  
**Then** 주 빌런의 진행을 완결하고 신규 보조 빌런은 signature teaser만 보여 주며 별도 thread로 등록한다.

---

## 9. 요구사항 추적표

| 사용자 문제 | 핵심 요구사항 | 검증 지표/시나리오 |
|---|---|---|
| 누나 캐릭터만 반복 | FR-CAST-01~04 | `lead_share_10`, AC-01/02 |
| 빌런 정보 부족 | FR-VIL-01~04 | completeness, AC-03/04/08 |
| 스토리가 단편처럼 보임 | FR-ARC-01~04, FR-STORY-01~03 | payoff rate, causality, AC-05 |
| 동작이 딱딱함 | FR-ACT-01~04 | readability/static pose, AC-06 |
| 조연이 장식적 | FR-CAST-03, FR-STORY-03 | cast coverage, AC-07 |

---

## 10. 완료 정의(Definition of Done)

다음 조건을 모두 만족할 때 요구사항 구현이 완료된 것으로 본다.

- 최근 20회 fixture로 편성 시 단일 영웅의 10회 주연 점유율이 예외 없이 50%를 넘지 않는다.
- 모든 신규 빌런 fixture가 소개 completeness 100%를 통과한다.
- 5개 연속 회차 통합 fixture에서 이전 consequence와 thread payoff가 끊기지 않는다.
- 전투/대화 fixture 모두 상태 전이와 action readability gate를 통과한다.
- 기존 factuality, fixed outcome, disclaimer, continuity 회귀 테스트가 유지된다.
- shadow 7일 동안 지표만 기록한 뒤 warning 10%, warning 100%, strict 순으로 승격한다.
- strict 전환 후 2주 동안 `thread_payoff_rate_5 ≥ 80%`, `static_pose_rate ≤ 10%`, 캐릭터 편중 기준을 유지한다.

### 최종 권고

첫 구현은 프롬프트 문구 조정이 아니라 **(1) 단일 편성 서비스와 노출 이력, (2) ID·만기를 가진 thread 원장, (3) Villain Reader Card, (4) 패널 상태 전이 계약**의 네 축으로 시작한다. 이 네 계약이 먼저 있어야 “누나 반복”, “빌런 설명 부족”, “단편성”, “딱딱한 동작”을 각각 측정하고 생성 전에 차단할 수 있다.
