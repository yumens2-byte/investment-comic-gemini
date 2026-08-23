# 미국시장 Invest Universe 스토리·퍼포먼스 품질 고도화 상세 설계

- 작성일: 2026-08-23
- 상태: 구현 승인 전 상세 설계안
- 선행 문서: `US_INVEST_UNIVERSE_STORY_ACTION_QUALITY_AUDIT_2026-08-23.md`
- 1차 구현 범위: 구조화된 패널 퍼포먼스 계약, 결정론적 검증, 이미지 프롬프트 컴파일, 의미 보존 재시도, 품질 관측성
- 제외 범위: 생성 후 멀티모달 Vision QA의 실제 API 연동, DB migration, 카논 이미지 재제작

---

## 1. 설계 결정 요약

### 1.1 해결할 문제

현재 `StoryBeatPlan`은 패널의 극적 기능을 정의하고 `EpisodeScript.Panel.action`은 자유문장으로 이미지 행동을 전달한다. 두 객체 사이에는 다음을 보장하는 계약이 없다.

- 누가 누구에게 어떤 목적을 갖고 행동하는가.
- 행동의 어느 순간을 그려야 하는가.
- 접촉점, 주도 사지, 무게 방향, 시선이 무엇인가.
- 이전 패널의 손상·위치·소품 상태가 다음 패널에 이어지는가.
- 카메라가 필수 행동을 실제로 보여줄 수 있는가.
- 이미지 재시도가 필수 캐릭터와 상호작용을 보존하는가.

### 1.2 핵심 결정

1. `EpisodeScript`는 즉시 파괴적으로 변경하지 않는다.
2. 기존 패널을 입력으로 받는 **결정론적 `PanelPerformanceSpec` 컴파일 단계**를 추가한다.
3. 신규 Story Planner v2가 활성화되면 더 풍부한 구조 필드를 직접 공급하고, 비활성화 시 legacy `action`에서 안전한 기본값을 파생한다.
4. 스키마 오류와 의미 오류를 분리하고 안정적인 오류 코드를 사용한다.
5. 처음에는 shadow mode로 점수와 경고만 기록한다.
6. strict mode에서도 `DISCLAIMER`, `TEXT_CARD`, `NO_BATTLE`을 전투 규칙으로 오판하지 않는다.
7. 재시도는 캐릭터 제거가 아니라 배경·효과 복잡도를 줄이는 방식으로 수행한다.

### 1.3 성공 조건

- 기존 feature flag가 모두 꺼진 실행 결과는 현재와 동일하다.
- flag가 켜지면 모든 character panel에 valid `PanelPerformanceSpec`이 존재한다.
- `interaction_required=true`인 패널은 subject와 target REF를 모든 retry에서 보존한다.
- hard validation 오류는 이미지 API 호출 전에 발견된다.
- episode metadata와 JSONL 로그에서 패널별 품질 상태와 오류 코드를 추적할 수 있다.

---

## 2. 대상 아키텍처와 실행 순서

```text
STEP 3 analysis
  NarrativeContextPack
  StoryBeatPlan v1/v2
        │
        ▼
STEP 4 narrative
  Claude EpisodeScript
        │
        ├─ validate_story_grounding
        ├─ validate_story_continuity
        └─ validate_story_beat_compliance        [신규]
        │
        ▼
STEP 5 image preflight
  compile_episode_performance                    [신규]
        ├─ PanelPerformanceSpec[]
        ├─ validate_panel_performance
        └─ validate_episode_visual_continuity
        │
        ▼
  build_for_episode(script, performance_specs)  [확장]
        └─ performance-aware prompt
        │
        ▼
  generate_episode
        ├─ transport retry
        ├─ complexity repair retry
        └─ quality status JSONL                  [확장]
```

### 2.1 파일별 책임

| 파일 | 변경 | 책임 |
|---|---|---|
| `engine/narrative/schema.py` | 확장 | StoryBeatPlan v2 선택 필드와 하위 호환 모델 |
| `engine/narrative/beat_compliance.py` | 신규 | 계획과 EpisodeScript 간 결정론적 준수 검사 |
| `engine/image/performance_schema.py` | 신규 | action/staging/continuity/quality 모델 |
| `engine/image/performance_compiler.py` | 신규 | panel + beat + 이전 state → performance spec |
| `engine/image/performance_validator.py` | 신규 | 패널/에피소드 정적 검증과 오류 코드 생성 |
| `engine/image/prompt_builder.py` | 확장 | spec 기반 PERFORMANCE/CONTINUITY 블록 렌더링 |
| `engine/image/gemini_client.py` | 확장 | 의미 보존 retry와 quality metadata 로그 |
| `scripts/run_market.py` | 확장 | feature flag, preflight, shadow/strict gate, metadata 연결 |
| `tests/fixtures/performance/` | 신규 | 정상·실패·경계 fixture |

의존 방향은 `narrative → image`가 아니라, 공통 데이터가 필요하면 스키마를 `engine/common`으로 올린다. 이미지 모듈이 narrative 구현 함수를 import하지 않도록 한다.

---

## 3. 데이터 계약

### 3.1 StoryBeat v2 확장

기존 필드는 유지하고 아래 필드를 모두 optional로 추가한다. v1 생성자는 수정 없이 계속 동작한다.

```python
class StoryStateTransition(BaseModel):
    entering_state: str = Field(max_length=240)
    objective: str = Field(max_length=160)
    tactic: str = Field(max_length=160)
    obstacle: str = Field(max_length=160)
    turn: str = Field(max_length=200)
    exiting_state: str = Field(max_length=240)
    cost: str | None = Field(default=None, max_length=160)

class StoryBeat(BaseModel):
    # existing fields remain
    state_transition: StoryStateTransition | None = None
    information_job: Literal[
        "SHOW_NUMBER",
        "EXPLAIN_MECHANISM",
        "SHOW_CONSEQUENCE",
        "EMOTIONAL_PAYOFF",
        "DISCLAIMER",
    ] | None = None
    relationship_trigger: RelationshipTrigger | None = None
```

### 불변 조건

- `panel_idx=8`이면 `information_job=DISCLAIMER` 또는 `None`만 허용한다.
- `DISCLAIMER` 비트는 objective/tactic을 요구하지 않는다.
- `market_evidence_ids`가 있으면 `information_job`은 `None`이 아니어야 한다.
- `relationship_trigger.trigger_panel`은 현재 `panel_idx`와 같아야 한다.
- v2 plan에서는 P1의 `entering_state`와 P7의 `exiting_state`가 필수다.

### 3.2 PanelPerformanceSpec

```python
ActionPhase = Literal[
    "ANTICIPATION", "ACTION", "IMPACT", "REACTION", "RECOVERY", "OBSERVATION", "NONE"
]
ShotSize = Literal["ECU", "CU", "MS", "MWS", "FS", "WS"]
ScreenDirection = Literal["L_TO_R", "R_TO_L", "FRONTAL", "NONE"]

class BodyMechanics(BaseModel):
    lead_limb: str | None = Field(default=None, max_length=80)
    support_limb: str | None = Field(default=None, max_length=80)
    weight_direction: str | None = Field(default=None, max_length=80)
    torso: str | None = Field(default=None, max_length=120)
    gaze: str = Field(max_length=160)
    expression: str = Field(max_length=120)
    secondary_motion: str | None = Field(default=None, max_length=160)

class StagingSpec(BaseModel):
    primary_interaction_pair: list[str] = Field(default_factory=list, max_length=2)
    screen_axis_id: str = Field(default="AXIS_A", pattern=r"^AXIS_[A-Z0-9_]+$")
    screen_direction: ScreenDirection = "NONE"
    shot_size: ShotSize
    focal_point: str = Field(max_length=160)
    negative_space: Literal["LEFT", "RIGHT", "TOP", "BOTTOM", "NONE"] = "NONE"
    depth_order: list[str] = Field(default_factory=list)
    full_body_required: bool = False

class VisualContinuityState(BaseModel):
    location: str = Field(max_length=120)
    character_positions: dict[str, Literal["LEFT", "RIGHT", "CENTER", "OFFSCREEN"]]
    prop_states: dict[str, str] = Field(default_factory=dict)
    injury_states: dict[str, str] = Field(default_factory=dict)
    environment_states: dict[str, str] = Field(default_factory=dict)

class PanelPerformanceSpec(BaseModel):
    version: Literal["performance-spec-1"] = "performance-spec-1"
    panel_idx: int = Field(ge=1, le=10)
    narrative_purpose: str = Field(max_length=200)
    subject_id: str | None = None
    action_verb: str = Field(max_length=120)
    target_id: str | None = None
    intent: str = Field(max_length=160)
    action_phase: ActionPhase
    contact_point: str | None = Field(default=None, max_length=160)
    interaction_required: bool = False
    body_mechanics: BodyMechanics
    staging: StagingSpec
    entering_state: VisualContinuityState
    exiting_state: VisualContinuityState
    must_show: list[str] = Field(default_factory=list, max_length=8)
    must_not_show: list[str] = Field(default_factory=list, max_length=8)
    required_character_ids: list[str] = Field(default_factory=list)
    optional_character_ids: list[str] = Field(default_factory=list)
    source: Literal["PLANNER_V2", "LEGACY_COMPILED"]
```

### 3.3 패널 유형별 필수 규칙

| 패널 유형 | phase | subject/target | body mechanics | continuity |
|---|---|---|---|---|
| `COVER` | `ANTICIPATION` 또는 `OBSERVATION` | subject 필수, target 선택 | gaze/expression 필수 | 위치만 필수 |
| `TENSION` | `OBSERVATION`/`ANTICIPATION` | subject 필수 | gaze/expression 필수 | prop 상태 권장 |
| `BATTLE` | `ACTION`/`IMPACT`/`REACTION` | subject 필수, interaction이면 target 필수 | lead/support/weight/torso 필수 | 전후 상태 필수 |
| `CLIMAX` | `IMPACT`/`REACTION` | subject 필수, target 권장 | 전체 필수 | 손상/소품 상태 필수 |
| `AFTERMATH` | `RECOVERY`/`OBSERVATION` | subject 선택 | gaze/expression 필수 | 이전 손상 보존 필수 |
| `TEXT_CARD` | `NONE` | 둘 다 없음 | 기본 empty mechanics | 위치/상태 empty 허용 |
| `DISCLAIMER` | `NONE` | 둘 다 없음 | 기본 empty mechanics | 위치/상태 empty 허용 |

### 3.4 QualityIssue 계약

```python
class QualityIssue(BaseModel):
    code: str
    severity: Literal["INFO", "WARNING", "ERROR"]
    panel_idx: int | None = None
    field: str | None = None
    message: str
    repair_hint: str | None = None

class PerformanceValidationResult(BaseModel):
    status: Literal["PASS", "DEGRADED", "FAIL"]
    score: int = Field(ge=0, le=100)
    issues: list[QualityIssue]
```

오류 code는 로그 집계 키이므로 문구와 달리 변경하지 않는다.

---

## 4. 컴파일 알고리즘

### 4.1 입력 우선순위

한 필드에 여러 출처가 있으면 다음 순서를 적용한다.

1. StoryBeat v2 `state_transition`/structured performance hint.
2. EpisodeScript panel의 명시 필드.
3. characters/role/panel_type 기반 결정론적 파생.
4. 안전한 default.

LLM을 추가 호출해 누락 필드를 채우지 않는다. 컴파일은 재현 가능해야 한다.

### 4.2 legacy action 파싱

자유문장의 완전한 의미 파싱을 시도하지 않는다. 다음의 제한된 규칙만 적용한다.

1. panel characters에서 hero/npc 첫 인물을 subject 후보로 선택한다.
2. `BATTLE`/`CLIMAX`이고 villain이 있으면 첫 villain을 target으로 선택한다.
3. action에서 known verb lexicon을 case-insensitive 검색한다.
4. 접촉 동사이면 `interaction_required=true`, contact point는 `unspecified visible contact`로 표시한다.
5. lexicon에 없으면 panel type 기본 verb를 사용하고 `PERF_W_ACTION_GENERIC` warning을 생성한다.

### 동사 사전 v1

| 계열 | 예시 | 기본 phase | interaction |
|---|---|---|---|
| strike | punch, kick, slam, strike, smash | IMPACT | true |
| projectile | fire, shoot, launch, beam | ACTION | target 존재 시 true |
| defend | block, shield, parry, brace | REACTION | target 선택 |
| move | leap, dash, charge, dodge | ACTION | false |
| observe | scan, watch, analyze, inspect | OBSERVATION | false |
| recover | kneel, rise, breathe, retreat | RECOVERY | false |

파서는 카논의 signature action을 새 사실처럼 삽입하지 않는다. 카논은 `must_show`와 prompt appearance/action vocabulary 보조에만 사용한다.

### 4.3 기본 body mechanics

동작 계열별 fallback은 구체적이되 캐릭터 외형과 충돌하지 않아야 한다.

```python
DEFAULT_MECHANICS = {
    "strike": {
        "lead_limb": "the named attacking limb",
        "support_limb": "opposite foot planted behind the hips",
        "weight_direction": "through the target at the contact point",
        "torso": "visible hip-and-shoulder rotation",
    },
    "projectile": {
        "lead_limb": "weapon or casting hand aimed at target",
        "support_limb": "stable counterbalance",
        "weight_direction": "braced against recoil",
        "torso": "aligned behind the projectile path",
    },
}
```

`the named attacking limb`처럼 unresolved placeholder가 남으면 strict mode에서 오류다.

### 4.4 visual continuity state 병합

```text
P1 exiting_state
  └─ copy forward all persistent keys
      └─ apply P2 explicit entering overrides
          └─ validate unexplained differences
              └─ apply P2 action mutations to exiting_state
```

### 지속성 정책

- `prop_states`, `injury_states`, `environment_states`는 다음 컷에 기본 전파한다.
- 위치는 같은 `screen_axis_id`에서 전파한다.
- location이 바뀌면 `SCENE_CHANGE`가 있어야 하며 environment는 reset할 수 있다.
- `broken`, `lost`, `removed`, `injured` 상태는 명시적 repair/recovery 없이 원복할 수 없다.
- `TEXT_CARD`와 `DISCLAIMER`는 continuity chain에서 제외한다.

### 4.5 복잡도 예산

```text
complexity = required_characters * 2
           + optional_characters
           + visible_props
           + effects
           + (2 if interaction_required else 0)
           + (1 if non-default axis/camera move else 0)
```

- `0~7`: 정상.
- `8~10`: warning, optional character/secondary effect 제거 권장.
- `11+`: strict mode fail.
- required character와 primary interaction은 예산 완화를 위해 제거할 수 없다.

---

## 5. 결정론적 검증 규칙

### 5.1 Hard errors

| 코드 | 조건 | repair |
|---|---|---|
| `PERF_E_SUBJECT_MISSING` | character panel인데 subject 없음 | panel characters에서 명시 선택 |
| `PERF_E_TARGET_MISSING` | interaction_required인데 target 없음 | target 또는 interaction=false 지정 |
| `PERF_E_SUBJECT_TARGET_SAME` | subject_id == target_id | 올바른 target 선택 |
| `PERF_E_REQUIRED_CHAR_MISSING` | required ID가 panel characters에 없음 | 스크립트 또는 spec 수정 |
| `PERF_E_CONTACT_MISSING` | IMPACT 상호작용인데 contact 없음 | 접촉점 추가 |
| `PERF_E_BODY_MECHANICS_INCOMPLETE` | battle 필수 mechanics 누락 | 누락 필드 추가 |
| `PERF_E_CAMERA_CROP` | full body 동작 + ECU/CU | FS/MWS로 변경 |
| `PERF_E_INTERACTION_FRAME` | interaction인데 두 인물/접촉점 프레임 보장 없음 | staging 수정 |
| `PERF_E_AXIS_JUMP` | 이유 없는 screen axis 반전 | neutral transition/cross reason 추가 |
| `PERF_E_PROP_RESURRECTION` | 파괴/분실 소품이 설명 없이 정상화 | repair beat 또는 상태 유지 |
| `PERF_E_COMPLEXITY_BUDGET` | complexity ≥ 11 | optional/background/effect 단순화 |

### 5.2 Warnings

| 코드 | 조건 |
|---|---|
| `PERF_W_ACTION_GENERIC` | legacy action을 구체 동사로 분류하지 못함 |
| `PERF_W_CONTACT_GENERIC` | contact point가 `unspecified visible contact` |
| `PERF_W_NO_SECONDARY_MOTION` | ACTION/IMPACT인데 후속 움직임 없음 |
| `PERF_W_STATIC_STREAK` | 연속 2개 character panel이 OBSERVATION/neutral pose |
| `PERF_W_SHOT_REPEAT` | 동일 shot size가 4컷 연속 |
| `PERF_W_SIGNATURE_REPEAT` | 최근 3회 같은 signature action을 climax에 사용 |
| `PERF_W_OPTIONAL_OVERLOAD` | optional character가 2명 이상 |
| `PERF_W_NEGATIVE_SPACE_CONFLICT` | overlay 예정 영역과 focal point가 겹침 |

### 5.3 Camera compatibility matrix

| phase / requirement | ECU | CU | MS | MWS | FS | WS |
|---|---:|---:|---:|---:|---:|---:|
| 얼굴 reaction | 허용 | 권장 | 허용 | 허용 | 비권장 | 금지 |
| 손 접촉점 | 조건부 | 권장 | 권장 | 허용 | 허용 | 비권장 |
| 상체 strike | 금지 | 조건부 | 권장 | 권장 | 허용 | 비권장 |
| kick/full body | 금지 | 금지 | 조건부 | 권장 | 권장 | 허용 |
| 2인 전신 interaction | 금지 | 금지 | 조건부 | 권장 | 권장 | 허용 |
| 3인 staging | 금지 | 금지 | 금지 | 조건부 | 권장 | 권장 |

`조건부`는 필수 부위와 focal point가 명시될 때만 허용한다.

### 5.4 점수 계산

정적 preflight score는 이미지 결과 점수와 분리한다.

```text
score = 100
      - ERROR * 25
      - WARNING_HIGH * 10
      - WARNING * 5
      - INFO * 0
```

- ERROR 1개 이상: `FAIL`.
- ERROR 0, score < 85: `DEGRADED`.
- ERROR 0, score ≥ 85: `PASS`.
- shadow mode는 상태와 무관하게 진행한다.
- strict mode는 FAIL 차단, DEGRADED는 진행하되 로그와 metadata에 남긴다.

---

## 6. StoryBeat compliance 설계

### 6.1 검사 결과

```python
class BeatComplianceItem(BaseModel):
    panel_idx: int
    required_characters_ok: bool
    evidence_binding_ok: bool
    dramatic_function_ok: bool
    continuity_payoff_ok: bool
    state_transition_ok: bool
    issues: list[QualityIssue]

class BeatComplianceResult(BaseModel):
    score: int
    status: Literal["PASS", "DEGRADED", "FAIL"]
    panels: list[BeatComplianceItem]
```

### 6.2 결정론적 항목

- required character: panel character ID와 exact match.
- evidence binding: beat evidence ID가 panel의 신규 `evidence_ids`에 존재. legacy에서는 `market_ref` 포함 여부를 warning 수준으로만 검사.
- continuity payoff: 기존 continuity scorer 결과 재사용.
- state transition: Pn exit와 Pn+1 enter가 호환.
- disclaimer: 마지막 panel type과 publishing disclaimer validator 재사용.

### 6.3 LLM에 맡기지 않을 것

- battle outcome 일치.
- ID 존재 여부.
- evidence 숫자 일치.
- 패널 순서.
- 캐릭터 수.
- 소품 상태의 명시적 일치.

감정 변화의 미학적 완성도와 은유 적합성은 1차 구현의 hard gate에서 제외한다.

---

## 7. 이미지 프롬프트 컴파일 상세

### 7.1 블록 우선순위

```text
1. CRITICAL SAFETY / NO TEXT
2. CHARACTER IDENTITY LOCK
3. REQUIRED CHARACTER COUNT
4. PERFORMANCE CONTRACT
5. CONTACT & BODY MECHANICS
6. STAGING / CAMERA / SCREEN AXIS
7. VISUAL CONTINUITY
8. CHARACTER DESIGN APPEARANCE
9. ENVIRONMENT / LIGHTING / STYLE
10. NEGATIVE BLOCK
```

현재 style보다 identity와 performance를 위로 올린다. 서로 충돌할 경우 안전성 > identity > required count > action > style 순이다.

### 7.2 PERFORMANCE CONTRACT 렌더링 예

```text
== PERFORMANCE CONTRACT — HARD REQUIREMENT ==
SUBJECT: CHAR_HERO_003
ACTION PHASE: IMPACT
ACTION: drives the right shoulder into CHAR_VILLAIN_002
INTENT: break the oil armor seal
TARGET: CHAR_VILLAIN_002
VISIBLE CONTACT: hero right shoulder ↔ villain sternum plate
REACTION: villain torso bends away from the contact while feet lag behind
Do not replace this interaction with posing, aiming, or separate attacks.
Both required characters and the contact point must be visible in one readable silhouette.
== END PERFORMANCE CONTRACT ==
```

### 7.3 BODY MECHANICS 렌더링 예

```text
== BODY MECHANICS ==
LEAD: right shoulder crosses toward the contact point.
BASE: left foot remains planted behind the hips.
WEIGHT: forward and down through the target.
TORSO: 30-degree hip-and-shoulder rotation, spine remains plausible.
GAZE: hero looks at contact; villain looks toward hero.
SECONDARY MOTION: cape and oil spray trail opposite the force direction.
Show anticipation, impact, and reaction through asymmetry. No neutral standing pose.
== END BODY MECHANICS ==
```

### 7.4 negative prompt 동적 추가

고정 negative에 패널 spec 기반 문장을 더한다.

- interaction: `No separated characters, no parallel unrelated attacks, no missing target.`
- full body: `No cropped feet, no cropped attacking limb.`
- prop continuity: `Shield remains broken; no intact duplicate shield.`
- count: `Exactly 2 named characters; no clones, crowds, or extra hero.`
- overlay: `Keep the TOP area visually quiet; no face or weapon crossing it.`

negative끼리 충돌하는지 검사한다. 예를 들어 `No crowds`와 배경 crowd 요청이 동시에 있으면 `PERF_E_PROMPT_CONFLICT`다.

### 7.5 prompt budget

- 공통 style/negative: 최대 600 tokens.
- identity: 캐릭터당 최대 220 tokens.
- performance + mechanics: 최대 300 tokens.
- staging + continuity: 최대 180 tokens.
- 전체 텍스트 목표: 1,500 tokens 이하, hard cap 2,000.
- cap 초과 시 optional atmosphere → redundant identity prose → secondary motion 순서로 축약한다.
- required identifiers, action, contact, count는 축약하지 않는다.

---

## 8. 의미 보존 재시도 설계

### 8.1 재시도 분리

| 종류 | 예 | 정책 |
|---|---|---|
| Transport | timeout, 429, 5xx | 동일 prompt/REF로 exponential backoff |
| Safety | blocked/empty candidate | 안전 문구 정리, 금지 표현 제거; 의미 계약 유지 |
| Complexity | 이미지 없음 또는 후속 QA 실패 | 배경/효과/optional 요소 단계적 축소 |
| Quality | identity/action/contact 실패 | 실패 code에 맞춘 targeted repair prompt |

decorator 내부 retry count에 의존해 호출자가 prompt를 바꾸지 않는다. 시도 루프가 명시적으로 `AttemptPlan`을 만든다.

```python
class AttemptPlan(BaseModel):
    attempt: int
    strategy: Literal["FULL", "REDUCE_ENV", "REDUCE_EFFECTS", "FRONTALIZE"]
    required_ref_paths: list[Path]
    optional_ref_paths: list[Path]
    prompt_suffix: str
```

### 8.2 3단계 전략

1. `FULL`: 전체 spec, required + optional REF.
2. `REDUCE_ENV`: required REF 유지, optional 캐릭터/배경 crowd 제거, 환경 단순화.
3. `REDUCE_EFFECTS`: required REF 유지, 입자·광선 감소, 접촉 실루엣과 정면/측면 staging 강조.

4번째 자동 생성은 하지 않는다. 실패 상태를 저장하고 manual fallback으로 넘긴다.

### 금지되는 완화

- required character REF 제거.
- target 제거.
- interaction을 single-character pose로 변경.
- battle outcome 방향 변경.
- 손상된 소품 원복.
- identity identifier 제거.

### 8.3 idempotency

`episode_id + panel_idx + performance_spec_hash + attempt`를 generation key로 사용한다. 동일 key가 success이면 재호출하지 않는다. prompt/spec이 달라지면 hash가 달라져 새 artifact로 취급한다.

---

## 9. 관측성과 저장 계약

### 9.1 JSONL 레코드 확장

```json
{
  "episode_id": "ICG-2026-08-23-001",
  "panel": 4,
  "panel_type": "BATTLE",
  "performance_spec_version": "performance-spec-1",
  "performance_spec_hash": "sha256:...",
  "performance_source": "PLANNER_V2",
  "required_character_ids": ["CHAR_HERO_003", "CHAR_VILLAIN_002"],
  "optional_character_ids": [],
  "interaction_required": true,
  "complexity_score": 7,
  "preflight_status": "PASS",
  "preflight_score": 95,
  "quality_issue_codes": ["PERF_W_NO_SECONDARY_MOTION"],
  "attempt": 1,
  "attempt_strategy": "FULL",
  "status": "success",
  "cost_usd": 0.039,
  "latency_sec": 8.2
}
```

prompt 원문, secret, base64 REF는 로그에 기록하지 않는다. `performance_spec_hash`는 정렬된 JSON의 SHA-256으로 계산한다.

### 9.2 Episode metadata

```json
{
  "_performance_quality": {
    "version": "performance-quality-1",
    "mode": "shadow",
    "episode_status": "DEGRADED",
    "episode_score": 87,
    "panel_results": [],
    "issue_counts": {
      "PERF_W_ACTION_GENERIC": 2
    }
  }
}
```

Pydantic `EpisodeScript` 검증 전에 underscore metadata를 주입하지 않는다. `model_dump()` 이후 asset/persist payload에만 추가한다.

### 9.3 로그 지표

- error/warning code별 count.
- panel type별 preflight pass rate.
- character count별 generation success rate.
- attempt strategy별 성공률과 비용.
- legacy compiled vs planner v2 품질 차이.
- interaction required 패널의 fallback/manual review율.

---

## 10. Feature flag와 운영 모드

| 환경변수 | 기본 | 설명 |
|---|---|---|
| `PERFORMANCE_SPEC_ENABLED` | `false` | spec compile과 prompt block 활성화 |
| `PERFORMANCE_QUALITY_MODE` | `shadow` | `shadow | warning | strict` |
| `STORY_BEAT_COMPLIANCE_ENABLED` | `false` | beat compliance 실행 |
| `PERFORMANCE_RETRY_V2_ENABLED` | `false` | 의미 보존 retry 사용 |
| `PERFORMANCE_PROMPT_MAX_TOKENS` | `2000` | prompt hard cap |
| `PERFORMANCE_COMPLEXITY_MAX` | `10` | strict 최대 복잡도 |

### 모드 의미

- `shadow`: spec/validation 결과 기록, 기존 prompt와 retry 사용.
- `warning`: 신규 prompt/retry 사용, validation FAIL도 진행하되 warning.
- `strict`: preflight FAIL이면 API 호출 차단, manual review 상태 저장.

잘못된 값은 묵시적으로 strict로 가지 않고 fail-fast configuration error를 발생시킨다.

---

## 11. `scripts/run_market.py` 통합 상세

현재 STEP 4 narrative quality 이후 STEP 5에서 `build_for_episode(script_dict)`와 Gemini 생성이 호출된다. 다음 순서로 변경한다.

```python
performance_specs = None
performance_quality = None

if settings.performance_spec_enabled:
    performance_specs = compile_episode_performance(
        episode_script=script_dict,
        story_beat_plan=ctx.get("story_beat_plan"),
        canon=active_canon,
    )
    performance_quality = validate_episode_performance(
        script_dict,
        performance_specs,
        mode=settings.performance_quality_mode,
    )

    if performance_quality.status == "FAIL" and mode == "strict":
        persist_manual_review(...)
        raise PerformanceQualityGateError(...)

panel_prompts = build_for_episode(
    script_dict,
    performance_specs=performance_specs,
)
```

### 실패 처리

- compile exception: flag false와 동일하게 silently fallback하지 않는다.
- shadow: error log + 기존 prompt로 진행.
- warning: episode `DEGRADED`, 기존 prompt fallback 허용.
- strict: API 호출 전 중단.
- 기존 critical market data gate와 continuity gate의 우선순위를 앞에 유지한다.

---

## 12. 테스트 상세 명세

### 12.1 단위 테스트

### `tests/test_performance_schema.py`

- interaction인데 target 없는 spec reject.
- DISCLAIMER의 NONE phase 허용.
- BATTLE에서 body mechanics 누락 결과가 hard issue.
- required와 optional ID 중복 reject.
- subject==target reject.

### `tests/test_performance_compiler.py`

- explicit v2 beat가 legacy action보다 우선.
- punch/kick/beam/block/observe/recover 동사 분류.
- unknown action이 generic warning과 안전 default 생성.
- panel characters에서 subject/target을 안정적 순서로 선택.
- 이전 exiting prop state가 다음 entering state로 전파.

### `tests/test_performance_validator.py`

- CU + full body kick → `PERF_E_CAMERA_CROP`.
- impact without contact → `PERF_E_CONTACT_MISSING`.
- broken shield resurrection 탐지.
- axis jump 탐지와 neutral transition 허용.
- 3인 MS staging reject.
- TEXT_CARD/DISCLAIMER false positive 없음.

### `tests/test_performance_prompt_builder.py`

- identity보다 performance가 뒤로 밀리지 않는 우선순위 snapshot.
- required count, subject, target, contact가 prompt에 존재.
- optional character만 complexity repair에서 제거.
- prompt cap 축약 후에도 hard fields 유지.
- dynamic negative conflict 탐지.

### `tests/test_gemini_retry_v2.py`

- 모든 attempt에 required refs 존재.
- attempt 2에서 optional refs만 제거.
- attempt 3에서 target이 유지.
- transport retry는 prompt를 변경하지 않음.
- 3회 실패 후 manual review 결과.

### 12.2 통합 테스트

| Fixture | 기대 |
|---|---|
| one-vs-one shoulder impact | PASS, 2 refs all attempts |
| alliance 3 characters | primary pair 고정, support optional |
| no-battle analysis | OBSERVATION, target/contact 불필요 |
| climax broken shield | 다음 aftermath에서도 broken 유지 |
| disclaimer | NONE phase, no character REF |
| close-up kick | strict preflight fail |
| unknown legacy action | DEGRADED, generic warning, 생성 가능 |

### 12.3 회귀 테스트

- 모든 flag off 상태에서 기존 `tests/test_story_planner.py`, `tests/test_gemini_client.py`, prompt builder 테스트가 byte-compatible 또는 승인된 snapshot-compatible.
- StoryBeat v1 JSON이 변경 없이 model validate.
- 기존 output asset naming과 publish stage 입력이 동일.
- Notion loader 실패 시 local canon fallback 유지.

### 12.4 Property tests

- 어떤 character ordering에서도 subject/target이 동일 role priority로 결정.
- required ID는 어떤 retry strategy에서도 refs에서 사라지지 않음.
- state merge 이후 입력 객체가 mutate되지 않음.
- serialized spec을 다시 읽으면 hash가 동일.
- 모든 enum 조합에서 validator가 exception 대신 structured result 반환.

---

## 13. Fixture 설계

```text
tests/fixtures/performance/
  legacy/
    battle_punch.json
    unknown_action.json
    no_battle.json
  planner_v2/
    one_vs_one_impact.json
    alliance_three_actor.json
    aftermath_prop_damage.json
  invalid/
    camera_crop.json
    missing_target.json
    axis_jump.json
    prop_resurrection.json
```

fixture는 `episode_script`, `story_beat_plan`, `expected_spec`, `expected_issues` 네 top-level key를 사용한다. 시장 숫자는 고정하고 실시간 API를 호출하지 않는다.

---

## 14. 배포 및 rollback

### Stage 1 — Shadow 7일

- 트래픽 100%에서 spec compile/validation만 실행.
- prompt와 retry는 기존 로직.
- 목표: compile 성공률 ≥ 99%, false-positive hard error ≤ 3%.

### Stage 2 — Warning canary 10%

- 신규 prompt/retry 활성화.
- 목표: generation success 하락 ≤ 5%p, required-character 누락 0, 비용 증가 ≤ 15%.

### Stage 3 — Warning 100%

- 최소 100 episode 또는 14일.
- 목표: static pose와 interaction failure 각각 30% 이상 감소.

### Stage 4 — Strict

- BATTLE/CLIMAX부터 strict.
- NO_BATTLE/TEXT_CARD는 별도 false-positive 검증 후 적용.
- manual review rate 5% 이하 유지.

### Rollback

1. `PERFORMANCE_RETRY_V2_ENABLED=false`.
2. `PERFORMANCE_QUALITY_MODE=shadow`.
3. 필요 시 `PERFORMANCE_SPEC_ENABLED=false`.

스키마는 additive이므로 rollback에 DB migration이 필요하지 않다. 신규 metadata를 구버전 reader가 무시하는지 배포 전에 확인한다.

---

## 15. 보안·비용·성능 고려

### 보안

- prompt, Notion 카논 원문, REF bytes를 quality log에 기록하지 않는다.
- 오류 메시지에는 환경변수 값과 로컬 secret 경로를 포함하지 않는다.
- hash는 spec 변경 탐지용이며 사용자/secret 식별자를 넣지 않는다.

### 비용

- 1차 구현은 LLM pass를 추가하지 않는다.
- prompt 증가분과 retry 감소/증가를 `cost_per_publishable_panel`로 비교한다.
- Vision QA는 후속 단계에서 panel 전체가 아니라 preflight PASS 결과에만 적용한다.

### 성능

- compile/validation 목표 p95 < 50ms/episode.
- YAML/Notion canon은 episode 단위 1회 로드하고 패널별 재로드하지 않는다.
- spec hash와 prompt compile은 pure function으로 유지해 캐시 가능하게 한다.

---

## 16. 구현 순서와 완료 정의

### PR-A — Schema + compiler + validator

**완료 정의**

- 모델과 오류 코드 구현.
- legacy panel 7종 compile 지원.
- 단위/fixture/property tests 통과.
- pipeline 미연결, 동작 변화 없음.

### PR-B — Shadow pipeline integration

**완료 정의**

- run_market에서 metadata 생성.
- JSONL 필드 확장.
- shadow 오류가 기존 발행을 막지 않음.
- resume 경로에서도 metadata 보존.

### PR-C — Performance prompt

**완료 정의**

- block 우선순위, budget, dynamic negative 구현.
- warning canary flag.
- snapshot 테스트와 30 fixture 수동 검수.

### PR-D — Retry v2

**완료 정의**

- 명시적 AttemptPlan.
- required REF invariant 테스트.
- 3회 실패 manual review 결과.
- 기존 decorator retry와 중복 호출 제거.

### PR-E — Story Planner v2

**완료 정의**

- episode archetype과 state transition 생성.
- beat compliance shadow score.
- 기존 continuity/outcome/grounding gate 회귀 없음.

---

## 17. 미결정 사항과 권장 기본값

| 항목 | 권장 기본값 | 결정 필요 이유 |
|---|---|---|
| action spec 생성 주체 | deterministic compiler 우선 | 추가 LLM 비용/비결정성 방지 |
| strict 시작 패널 | BATTLE, CLIMAX | 품질 효과가 크고 규칙이 명확 |
| required character | beat required + subject + target | retry 의미 보존 |
| optional character | background/support only | 복잡도 완화 가능 |
| 자동 시도 수 | 총 3회 | 비용 상한과 수율 균형 |
| complexity hard max | 10 | 초기 shadow 결과로 재조정 |
| prompt hard cap | 2,000 tokens | identity/action 보존과 비용 균형 |
| manual review 저장 방식 | 기존 episode artifact metadata | DB migration 없이 시작 |

---

## 18. 구현 착수 체크리스트

- [ ] `PanelPerformanceSpec` 필드와 enum 승인
- [ ] hard error code 목록 freeze
- [ ] required/optional character 판정 승인
- [ ] panel type × action phase matrix 승인
- [ ] legacy verb lexicon 카논 캐릭터 샘플 검토
- [ ] prompt block 우선순위와 token cap 승인
- [ ] shadow/warning/strict 전환 지표 승인
- [ ] manual review 상태를 publish gate가 차단하는지 확인
- [ ] resume/retry 경로에서 spec hash 보존 확인
- [ ] 30개 평가 fixture 담당자 및 human review rubric 확정

### 최종 권고

첫 구현은 PR-A와 PR-B까지만 진행한다. 먼저 구조 계약과 실패 데이터가 안정적으로 쌓이는지 확인한 뒤 prompt와 retry 동작을 바꿔야 원인과 효과를 분리할 수 있다. 특히 기존 마지막 retry의 필수 상대 제거 문제는 PR-D를 기다리지 않고, interaction 패널에서만 즉시 차단하는 작은 hotfix로 선반영할 수 있다.
