# 미국시장 Invest Universe 스토리·캐릭터 동작 품질 고도화 상세 분석

- 작성일: 2026-08-23
- 범위: `시장 데이터 → 서사 계획 → EpisodeScript → 이미지 프롬프트 → Gemini 이미지` 구간
- 목적: 미국시장 데이터를 영웅 서사로 변환할 때 **이야기의 인과·연속성**과 **캐릭터 동작의 명료성·일관성**을 함께 높이기 위한 기준선과 실행 계획을 확정한다.
- 이번 산출물의 성격: 구현 전 진단/설계. 모델 출력 샘플과 운영 로그를 이용한 정량 베이스라인 측정은 다음 단계에서 수행한다.

---

## 1. Executive summary

현재 프로젝트는 시장 데이터 근거, 8컷 비트 계획, 캐릭터 카논, REF 이미지, 패널별 구도 지시를 이미 갖춘 좋은 기반이다. 특히 `StoryBeatPlan`, continuity score, character identity lock은 단순 이미지 생성기를 연재형 콘텐츠 파이프라인으로 발전시키는 핵심 자산이다.

그러나 두 목표 사이의 계약이 아직 느슨하다.

1. **스토리라인:** 고정 8비트가 모든 이벤트에 동일하게 적용되고, 비트가 요구하는 감정 변화와 실제 `EpisodeScript`를 구조적으로 검증하지 않는다. 시장 원인과 전투 결과는 존재하지만, 캐릭터의 욕망·전술·대가가 패널 단위 상태 변화로 연결되지 않는다.
2. **캐릭터 동작:** 이미지 프롬프트는 자유문장 `action`에 동작 품질을 의존한다. 포즈, 접촉, 시선, 무게중심, 전후 상태를 기계적으로 확인할 수 없으며, 다중 캐릭터 장면에서 누가 누구에게 무엇을 하는지 모호해질 수 있다.
3. **공통 병목:** 서사 비트의 `visual_symbol`/`emotional_shift`와 이미지 입력의 `action`/`camera` 사이에 명시적 변환 계층이 없다. 따라서 글은 맞지만 그림이 정적이거나, 그림은 화려하지만 이야기의 전환점을 표현하지 못할 수 있다.
4. **운영 품질:** 생성 성공/비용은 기록하지만, identity·pose·interaction·continuity별 품질 점수와 실패 사유가 없다. 현재 재시도는 실패 응답 중심이며, 생성됐지만 잘못된 이미지에 대한 자동 복구 루프가 없다.

### 최우선 제안

`StoryBeatPlan → PanelPerformanceSpec → ImagePrompt`라는 중간 계약을 도입한다. 각 패널에 `objective`, `tactic`, `turn`, `subject`, `verb`, `target`, `contact`, `body_mechanics`, `screen_direction`, `continuity_from/to`를 구조화하고, 생성 전 정적 검증과 생성 후 비전 QA를 통과시킨다.

---

## 2. 현재 파이프라인 분석

### 2.1 실제 데이터 흐름

```text
미국시장 snapshot / delta / evidence
  └─ Narrative Context Pack
      └─ deterministic StoryBeatPlan (8 beats)
          └─ Claude EpisodeScript (8~10 panels)
              ├─ continuity / grounding validation
              └─ image.prompt_builder
                  ├─ style lock
                  ├─ panel visual spec
                  ├─ identity lock + local/Notion canon
                  ├─ free-text dynamic action
                  └─ Gemini + character REF images
```

### 2.2 현재 강점

| 영역 | 현재 자산 | 평가 |
|---|---|---|
| 데이터 근거 | evidence card, prohibited claims, market grounding guardrail | 허구 세계관과 실제 투자 사실을 분리할 토대가 있음 |
| 이야기 골격 | 8개 dramatic function과 패널 순서 검증 | 에피소드 최소 완결성을 보장 |
| 연속성 | previous hook, unresolved/resolved threads, arc pivot, continuity score/retry | 연재물의 회차 연결을 운영 가능한 형태로 만들었음 |
| 캐릭터성 | canon prompt의 identity, voice, metaphor, signature action, forbidden | 캐릭터를 단순 외형 REF 이상으로 정의 |
| 이미지 일관성 | REF 다중 입력, identity lock, hero/villain 위치·시선 규칙 | 외형 드리프트 억제 기반이 있음 |
| 장면 연출 | 패널 타입별 composition/lighting/camera, outcome별 chart direction | 시장 상태를 시각 톤에 반영 |
| 안전성 | 이미지 내 텍스트 금지, 실존 인물/성인물 negative block | 합성 단계와 이미지 생성의 책임 분리가 명확 |

### 2.3 핵심 구조적 단절

| 경계 | 전달되는 것 | 유실되는 것 | 결과 |
|---|---|---|---|
| Context → BeatPlan | 시장 원인, evidence ID, 결과 | 근거별 확신도·상충 여부·캐릭터가 오해할 수 있는 범위 | 설명문 중심 전개 |
| BeatPlan → EpisodeScript | 기능, 감정 변화, dialogue intent | 구체적 목표/전술/대가/상태 전이 | 비트 준수 여부를 사후 검증하기 어려움 |
| EpisodeScript → ImagePrompt | 자유문장 action, characters, camera | 동작 주체/대상/접촉점/관절/시선/연속 동선 | 정적 포즈·해부 오류·상호작용 모호성 |
| Image → 운영 | 파일, 토큰, 비용, 성공 여부 | 캐릭터 동일성·행동 가독성·서사 충실도 | 저품질 성공작이 그대로 발행될 위험 |

---

## 3. 트랙 A — 스토리라인 상세 진단

### A1. 고정 8비트가 이벤트 성격을 평준화한다 — 심각도 High

현재 `HOOK → MARKET_CAUSE → CHARACTER_REACTION → CONFLICT → TURNING_POINT → OUTCOME → NEXT_HOOK → DISCLAIMER`가 시나리오와 무관하게 고정된다. `NO_BATTLE`도 대사 의도만 달라질 뿐 극적 기능은 동일하다.

**영향**

- CPI/FOMC 같은 예정 이벤트, 지정학 쇼크, 완만한 리스크온, 전일 전투의 aftermath가 같은 리듬을 갖는다.
- 독자가 “오늘도 4~6컷에서 싸우고 7컷에서 예고한다”는 패턴을 빠르게 학습한다.
- 정보 전달과 드라마 모두 중간 수준으로 수렴한다.

**개선안**

`episode_archetype`별 비트 템플릿을 분기한다.

| Archetype | 권장 비트 |
|---|---|
| `SHOCK_INVASION` | anomaly → denial → reveal → first impact → failed tactic → sacrifice → unstable containment |
| `DATA_DUEL` | claim → counter-evidence → test → contradiction → reinterpretation → verdict → open question |
| `AFTERMATH_COST` | damage scan → blame → hidden cost → relationship fracture → repair choice → new rule → residue |
| `RALLY_TRAP` | relief → temptation → warning ignored → overextension → reversal → narrow escape → unresolved signal |
| `NO_BATTLE_INTEL` | observation → hypothesis → evidence → falsification → revised model → watch condition → next checkpoint |

8번째 면책 패널은 퍼블리싱 요구로 유지하되, 1~7컷의 극적 구조는 유연하게 한다.

### A2. 시장 원인이 캐릭터 동기로 번역되지 않는다 — 심각도 Critical

현재 빌런 동기는 사실상 “시장 evidence에서 압박을 이끈다”이고, 히어로 내적 갈등은 “고정 outcome을 부정하지 않고 대응한다”이다. 이는 생성 제약이지 인물의 동기가 아니다.

**필요한 번역 계층**

```text
market fact
  → market mechanism
  → who benefits / who is threatened
  → character belief
  → immediate objective
  → tactic
  → cost or contradiction
```

예: `10Y yield 상승` → 할인율 상승/밸류에이션 압박 → 장기 성장주 영웅이 위협받음 → “유동성보다 현금흐름이 방패”라는 믿음 시험 → 경매장의 금리 사슬을 끊으려 함 → duration shield 전개 → 방어에는 성공하지만 동료의 공격 기회를 잃음.

### A3. 패널 사이 상태 전이 계약이 없다 — 심각도 Critical

각 비트는 독립적인 설명을 가지지만 P3의 행동이 P4의 상황을 어떻게 바꿨는지 명시하지 않는다. 이 때문에 장면이 연속 행동이 아니라 관련 있는 포스터 7장처럼 보일 수 있다.

**신규 필드 제안**

```yaml
panel_state:
  entering_state: "Debt chains pin hero's left arm"
  objective: "reach the auction bell"
  tactic: "redirect the yield beam through the shield"
  obstacle: "villain anchors chains to the floor"
  turn: "shield cracks but frees the left arm"
  exiting_state: "hero kneeling, left arm free, shield broken"
  cost: "defense unavailable next panel"
```

`P(n).exiting_state`가 `P(n+1).entering_state`와 호환되는지 정적으로 검사한다.

### A4. 비트 준수가 프롬프트 권고에 머문다 — 심각도 High

스키마는 비트 순서와 마지막 disclaimer를 검증하지만, 생성된 패널이 `required_character`, `market_evidence_ids`, `emotional_shift`, `visual_symbol`을 실제 반영했는지는 강제하지 않는다.

**개선안**

- `validate_beat_compliance(script, plan)` 추가.
- 패널별 required character 포함 여부는 hard gate.
- evidence ID는 `market_ref`와 연결하고 허용 evidence registry에서 확인.
- visual symbol/action/emotional shift는 키워드가 아닌 별도 structured field로 보존.
- P1~P7 전체 compliance 85점 미만이면 좁은 repair retry 수행.

### A5. 캐릭터 관계 변화가 장면으로 증명되지 않는다 — 심각도 Medium

`relationship_delta`는 결과 요약 dict이며 어떤 대사/행동이 변화를 만들었는지 provenance가 없다.

**개선안**

`relationship_delta`를 `{pair_id, before, trigger_panel, observable_action, after, confidence}` 형태로 바꾸고, `trigger_panel`의 행동이 실제 스크립트에 존재하도록 검증한다.

### A6. 정보 패널과 드라마 패널의 책임이 섞인다 — 심각도 Medium

이미지는 텍스트를 금지하지만 `market_ref`, key text, narration을 가진 이야기 스키마는 이미지 프롬프트에 시각적 분위기로만 전달된다. 이는 올바른 방향이지만, 숫자 근거를 어느 패널에서 읽고 어느 패널에서 느끼게 할지 명시되지 않았다.

**개선안**

- `information_job`: `SHOW_NUMBER | EXPLAIN_MECHANISM | SHOW_CONSEQUENCE | EMOTIONAL_PAYOFF`.
- `SHOW_NUMBER`는 PIL overlay가 중심, 생성 이미지는 넓은 negative space를 확보.
- `SHOW_CONSEQUENCE`는 숫자 대신 물리적 은유를 사용.
- 한 패널에 정보 job은 최대 1개로 제한.

---

## 4. 트랙 B — 이미지 생성 캐릭터 동작 상세 진단

### B1. 자유문장 action은 동작을 충분히 고정하지 못한다 — 심각도 Critical

현재 프롬프트는 action을 “exact action”으로 렌더링하라고 강조하지만, action 자체의 완전성은 검증하지 않는다. “Hero attacks villain dynamically”도 유효 입력이다.

**Action Grammar v1**

```yaml
performance:
  subject: CHAR_HERO_003
  verb: "drives right shoulder into"
  target: CHAR_VILLAIN_002
  intent: "break the oil armor seal"
  phase: IMPACT        # ANTICIPATION | ACTION | IMPACT | REACTION | RECOVERY
  contact_point: "hero right shoulder ↔ villain sternum plate"
  lead_limb: "right shoulder"
  support_limb: "left foot planted behind hip"
  weight_direction: "forward and down"
  torso: "30-degree forward twist"
  gaze: "hero at contact point; villain at hero"
  expression: "effort vs sudden shock"
  secondary_motion: "cape and oil spray trail backward"
  interaction_required: true
```

필수값이 없는 상호작용 장면은 이미지 생성 전에 차단한다.

### B2. 카메라와 동작의 충돌을 검사하지 않는다 — 심각도 High

예를 들어 발 동작이 중요한데 `CLOSE_UP`, 양 캐릭터 접촉을 보여줘야 하는데 single-character composition이 선택될 수 있다.

**호환 규칙 예시**

- `full_body_required=true`이면 `CLOSE_UP` 금지.
- `contact_point`가 있으면 두 캐릭터와 접촉점이 프레임 안에 있어야 한다.
- `REACTION`은 충격 원인과 반응자를 동시에 보여주거나 eyeline match를 지정한다.
- 3인 이상은 `primary_interaction_pair`를 필수로 하고 나머지는 depth layer에 배치한다.

### B3. 화면 방향과 동선 연속성이 약하다 — 심각도 High

전역 gaze/position law는 대치 구도를 일관되게 하지만, 패널 간 이동 방향과 180도 규칙은 정의하지 않는다. 매 컷 hero-left/villain-right를 기계적으로 강제하면 추격·우회·역전이 부자연스러워질 수 있다.

**개선안**

- `screen_axis_id`, `subject_screen_direction`, `cross_axis_reason` 추가.
- 축 전환은 neutral shot 또는 명시적 camera move 뒤에서만 허용.
- 포지션 법칙은 identity rule이 아니라 기본 staging rule로 낮추고, 의도적 역전은 `story_reason`과 함께 허용.

### B4. REF 이미지가 외형뿐 아니라 정적 자세 bias를 줄 수 있다 — 심각도 High

프롬프트에서 REF는 외형 전용이라고 반복하지만 생성 모델은 시각 입력의 자세를 강하게 모사할 수 있다. 텍스트 강조만으로 이 bias를 제거하기 어렵다.

**개선안**

1. 캐릭터별 **turnaround/neutral identity sheet**와 **action pose sheet**를 분리한다.
2. action reference는 동일 캐릭터가 아니라 저작권 안전한 스켈레톤/실루엣/깊이맵을 사용한다.
3. 입력 순서를 `scene instruction → pose guide → identity refs`로 실험하고 A/B 측정한다.
4. 3인 장면에서는 인물별 crop REF와 전체 staging guide를 분리한다.

### B5. 해부학·접촉·소품 상태를 검증하지 않는다 — 심각도 Critical

negative block은 일반 안전성에 집중하며 손가락 수, 관절 방향, 무기 소유자, 접촉 위치, 복제 캐릭터를 구조적으로 다루지 않는다.

**생성 후 Vision QA 필수 항목**

| 축 | 검사 질문 | hard fail 예 |
|---|---|---|
| Identity | 필수 identifier와 색상 규칙이 유지되는가 | 얼굴/무기/상징 누락 |
| Count | 요청한 캐릭터 수와 각 ID가 맞는가 | 복제 hero, villain 누락 |
| Pose | 요구 phase와 lead limb가 보이는가 | 공격인데 중립 자세 |
| Interaction | subject/target/contact가 명확한가 | 서로 다른 방향 공격 |
| Anatomy | 손·팔·다리·관절이 가능한 구조인가 | 추가 팔, 뒤집힌 관절 |
| Prop | 무기 소유/상태가 전후 컷과 맞는가 | 깨진 방패가 다음 컷에서 복구 |
| Composition | focal point와 negative space가 맞는가 | 자막 영역을 얼굴이 침범 |
| Safety | 금지 텍스트/실존 인물/상표가 없는가 | 읽을 수 있는 가짜 숫자 |

### B6. 재시도 전략이 의미 품질을 낮출 수 있다 — 심각도 Critical

마지막 단순화 시도에서 첫 REF만 남기고 primary character만 렌더링하도록 허용한다. 전투 패널은 응답 성공률이 올라가도 상대 캐릭터와 핵심 상호작용이 사라질 수 있다. 이는 기술적 성공을 서사 실패로 바꾸는 방식이다.

**개선안**

- API/안전 실패 retry와 quality repair retry를 분리한다.
- interaction-required 패널에서는 상대 제거를 금지한다.
- 복잡도 완화는 캐릭터 제거 대신 배경 단순화, 이펙트 감소, 카메라 정면화 순으로 수행한다.
- 최종 fallback은 “성공 이미지”가 아니라 `needs_manual_review` 상태로 격리한다.

---

## 5. 통합 목표 아키텍처

```text
NarrativeContextPack
  ↓ evidence/mechanism mapper
EpisodePremise
  - archetype, thesis, dramatic_question
  - character_wants, beliefs_under_test, irreversible_cost
  ↓ archetype planner
StoryBeatPlan v2
  - entering_state/objective/tactic/turn/exiting_state
  - evidence binding and relationship trigger
  ↓ script writer + deterministic validation
EpisodeScript v2
  ↓ performance compiler
PanelPerformanceSpec
  - action grammar, body mechanics, staging, axis, continuity
  ↓ prompt renderer
Gemini image
  ↓ multimodal Vision QA
quality pass / targeted repair / manual review
```

### 5.1 `PanelPerformanceSpec` 최소 스키마

```python
class PanelPerformanceSpec(BaseModel):
    panel_idx: int
    narrative_purpose: str
    entering_state: str
    exiting_state: str
    subject_id: str | None
    action_verb: str
    target_id: str | None
    action_phase: Literal["ANTICIPATION", "ACTION", "IMPACT", "REACTION", "RECOVERY"]
    contact_point: str | None
    body_mechanics: BodyMechanics
    primary_interaction_pair: list[str]
    screen_axis_id: str
    screen_direction: Literal["L_TO_R", "R_TO_L", "FRONTAL", "NONE"]
    shot_size: Literal["ECU", "CU", "MS", "MWS", "FS", "WS"]
    focal_point: str
    negative_space: Literal["LEFT", "RIGHT", "TOP", "BOTTOM", "NONE"]
    must_show: list[str]
    must_not_show: list[str]
```

### 5.2 품질 게이트 순서

1. **Schema gate:** 필수 구조/enum/길이.
2. **Evidence gate:** 실제 시장 주장과 evidence binding.
3. **Story gate:** objective→tactic→turn→cost, beat compliance, continuity.
4. **Performance gate:** 주체·동사·대상, 카메라 호환, 축/동선.
5. **Prompt gate:** identity/action/negative block 포함과 충돌 탐지.
6. **Vision gate:** 생성 결과의 identity, count, action, anatomy, interaction.
7. **Publish gate:** hard fail 0건, 전체 점수 기준 통과, warning 기록.

---

## 6. 평가 체계와 합격 기준

### 6.1 오프라인 평가 세트

최소 30개 episode fixture를 만든다.

- 5 archetype × 3 outcome × 단일/다중 캐릭터 2종 = 30개.
- 실제값을 고정한 context pack, 기대 beat/state/performance spec 포함.
- 캐릭터당 최소 4개 action phase와 2개 카메라 각도 포함.
- 정상 케이스뿐 아니라 evidence 상충, REF 누락, 3인 장면, 전회차 hook 변경을 포함.

### 6.2 Story Quality Score (100)

| 항목 | 배점 | 측정 |
|---|---:|---|
| Evidence fidelity | 20 | 미지원 사실 0, evidence binding 비율 |
| Causal clarity | 20 | fact→mechanism→choice→outcome 연결 |
| Character agency | 15 | 각 주요 인물의 objective/tactic/cost 존재 |
| Escalation & payoff | 15 | 상태 전이와 setup/payoff 회수 |
| Continuity | 15 | 전회차 hook/thread/relationship 회수 |
| Variety | 10 | 최근 N회 archetype/장면/대사 중복률 |
| Readability | 5 | 컷당 정보 job 1개, 텍스트 한도 |

**출시 기준:** 평균 85+, 어떤 항목도 70 미만 금지, evidence hard failure 0.

### 6.3 Action Quality Score (100)

| 항목 | 배점 | 측정 |
|---|---:|---|
| Identity | 20 | identifier/color/face/weapon |
| Action legibility | 20 | 주체·동사·대상·phase 식별 |
| Interaction/contact | 15 | 시선, 접촉점, 반작용 |
| Anatomy | 15 | limb/count/joint 오류 |
| Composition | 10 | focal point, crop, overlay 공간 |
| Motion & weight | 10 | 무게중심, anticipation/follow-through |
| Inter-panel continuity | 10 | 위치, 소품 손상, 방향, 상처 상태 |

**출시 기준:** 단일 컷 82+, 에피소드 평균 88+, identity/anatomy hard failure 0.

### 6.4 운영 지표

- `first_pass_story_rate`
- `first_pass_image_quality_rate`
- `repair_retry_rate{reason}`
- `identity_failure_rate{char_id}`
- `static_pose_rate{panel_type}`
- `interaction_failure_rate{character_count}`
- `story_archetype_frequency_30d`
- `visual_similarity_rate_30d`
- `manual_review_rate`
- `cost_per_publishable_panel` (단순 생성 패널이 아닌 게시 가능 패널 기준)

---

## 7. 단계별 구현 로드맵

### Phase 0 — 베이스라인 계측 (2~3일, P0)

- 최근/fixture 30개 에피소드를 Story/Action rubric으로 수동 이중 평가.
- Gemini 로그에 `episode_id`, `panel_type`, `character_count`, `retry_reason` 추가.
- 실패 taxonomy를 `IDENTITY | STATIC_POSE | INTERACTION | ANATOMY | CONTINUITY | TEXT | SAFETY`로 고정.
- 결과물: baseline report와 목표 수치 확정.

### Phase 1 — 계약 강화 (4~6일, P0)

- `EpisodePremise`, `PanelState`, `PanelPerformanceSpec` Pydantic 모델 추가.
- action grammar validator와 camera compatibility validator 추가.
- `StoryBeatPlan`을 archetype 기반 v2로 확장하되 feature flag로 shadow 실행.
- 기존 EpisodeScript와 병행해 하위 호환 유지.

### Phase 2 — 프롬프트 컴파일러 (3~5일, P0)

- 자유문장 action을 구조화 spec에서 결정론적으로 렌더링.
- `must_show`, `must_not_show`, body mechanics, interaction block 분리.
- multi-character complexity budget 도입.
- retry에서 필수 캐릭터 제거 금지; 실패 원인별 repair prompt 적용.

### Phase 3 — 생성 후 Vision QA (4~7일, P1)

- 저비용 multimodal judge + deterministic checks 조합.
- 점수와 근거를 JSONL/episode metadata에 저장.
- hard fail 자동 repair 최대 2회, 이후 manual review.
- judge 편향을 막기 위해 10% 표본 인간 평가와 일치율 측정.

### Phase 4 — 연재 다양성/학습 루프 (3~5일, P1)

- 최근 30회 archetype, setting, signature action, dialogue pattern registry.
- 반복 패널/구도 억제 penalty.
- 캐릭터별 성공 action/camera 조합을 저장하되 카논 변경은 인간 승인.

---

## 8. 권장 PR 분할

1. **PR-1: quality schemas and validators** — 모델/정적 검사/fixture만 추가.
2. **PR-2: story archetype planner v2 shadow mode** — 기존 결과를 바꾸지 않고 비교 로그 생성.
3. **PR-3: performance prompt compiler** — 10% canary, 기존 prompt builder fallback 유지.
4. **PR-4: vision QA and reasoned retry** — 게시 gate는 처음에 warning-only.
5. **PR-5: strict publish gate** — 2주 shadow 지표가 기준을 충족한 뒤 활성화.

각 PR은 독립 rollback이 가능해야 하며 `STORY_PLANNER_V2_ENABLED`, `PERFORMANCE_SPEC_ENABLED`, `IMAGE_VISION_QA_ENABLED`, `IMAGE_QUALITY_STRICT_ENABLED` 플래그를 사용한다.

---

## 9. 즉시 수정 후보와 우선순위

| 우선순위 | 작업 | 기대효과 | 위험 |
|---|---|---|---|
| P0 | interaction-required retry에서 상대 캐릭터 제거 금지 | 서사적으로 틀린 성공 이미지 방지 | 생성 실패율 단기 상승 |
| P0 | action grammar + camera compatibility validator | 정적 포즈/모호한 접촉 감소 | 스키마 마이그레이션 필요 |
| P0 | BeatPlan↔EpisodeScript compliance 검사 | 계획과 결과의 괴리 감소 | retry 비용 증가 |
| P0 | 생성 후 identity/action QA 로그 | 실패 원인 가시화 | judge 비용/지연 |
| P1 | archetype별 story planner | 반복감 감소, 이벤트 특성 강화 | 회귀 평가 세트 필요 |
| P1 | panel entering/exiting state | 컷 간 연속성 강화 | 프롬프트 길이 증가 |
| P1 | pose guide/identity REF 분리 실험 | REF 정적 자세 bias 감소 | 자산 제작 필요 |
| P2 | 30일 novelty registry | 장기 반복 억제 | 저장/유사도 인프라 |

---

## 10. 리스크와 설계 원칙

1. **프롬프트를 길게 만드는 것이 품질 향상은 아니다.** 구조화 후 패널에 필요한 블록만 컴파일한다.
2. **LLM judge 단독 판정은 금지한다.** 스키마/count/evidence는 결정론적으로, 미학/pose는 vision judge로 나눈다.
3. **시장 사실과 세계관 은유를 분리한다.** 캐릭터 능력은 허구여도 `market_ref`의 인과 주장은 evidence에 묶는다.
4. **정체성과 자세를 분리한다.** identity REF가 pose를 지배하지 않도록 입력 자산과 평가 축을 분리한다.
5. **기술적 생성 성공과 게시 가능 성공을 구분한다.** 비용 지표도 `cost_per_publishable_panel`을 사용한다.
6. **다중 캐릭터는 복잡도 예산을 갖는다.** 한 컷의 primary interaction은 하나, 보조 인물은 반응 역할로 제한한다.
7. **연속성은 반복이 아니다.** 같은 구도를 복제하는 대신 소품 상태, 상처, 방향, 관계의 결과를 이어간다.

---

## 11. 다음 착수 시 체크리스트

- [ ] 30개 평가 fixture의 archetype/outcome/character 조합 확정
- [ ] 현재 출력 30개 Story/Action baseline 이중 채점
- [ ] `PanelPerformanceSpec` 필드와 hard/soft gate 합의
- [ ] interaction-required와 optional-character 정의
- [ ] Gemini 입력 순서/REF 수/pose guide A/B 실험 설계
- [ ] Vision QA JSON schema와 human agreement 목표 확정
- [ ] canary 비율, 비용 상한, latency 상한 확정
- [ ] shadow → warning → strict 전환 조건 확정

### 권장 첫 구현 범위

첫 구현은 **(1) 구조화 action spec, (2) camera/action 정적 검사, (3) retry에서 필수 상대 제거 금지, (4) 품질 사유 로그**까지만 묶는다. 이 범위는 스토리 모델을 전면 교체하지 않고도 동작 실패를 측정하고 줄이며, 이후 archetype planner와 Vision QA가 사용할 안정적인 계약을 만든다.

후속 구현 계약, 파일별 변경점, 검증 알고리즘, 오류 코드, feature flag 및 테스트 명세는 [스토리·퍼포먼스 품질 고도화 상세 설계](US_INVEST_UNIVERSE_STORY_PERFORMANCE_DETAILED_DESIGN_2026-08-23.md)를 따른다.
