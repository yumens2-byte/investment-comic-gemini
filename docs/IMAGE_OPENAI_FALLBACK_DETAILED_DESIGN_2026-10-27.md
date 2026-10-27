# Run Market 이미지 OpenAI 최종 폴백 상세설계 (2026-10-27)

상태: 상세설계 (구현 전, 마스터 승인 대기)

## 0. 확정된 요구사항

| 항목 | 결정 |
|---|---|
| 트리거 | `run_market` STEP 6 이미지 생성 중 Gemini 한도/잔액 소진(최종 한도초과) |
| 폴백 키 | GitHub Secret `OPENAI_API_KEY` 단독 (ORG/PROJECT ID 불필요, SDK에서 선택값) |
| 이어서 생성 | 이미 성공한 Gemini 패널은 보존·재사용, 실패 패널부터 남은 패널만 OpenAI로 생성 |
| 모델/품질 | `gpt-image-2` / `medium` (환경변수로 전환 가능) |
| 화풍 | Gemini 화풍에 맞춤 (STYLE LOCK 동일 + Gemini 성공 패널을 스타일 앵커로 주입) |

## 1. 사실 근거 (코드·SDK 소스 확인)

- 호출 경로: `scripts/run_market.py:step_image` → `engine/image/gemini_client.py:generate_episode` → `generate_panel` → `_generate_one`.
- Gemini 오류 객체(`google-genai` 2.33.0 `errors.APIError`): `code`(HTTP), `status`(예: `RESOURCE_EXHAUSTED`), `message`, `details` 보유.
- 현행 429 처리: 일반 `except Exception` 분기 → `actual_cost=None` 정산 → DB가 `unknown`(`PROVIDER_OUTCOME_UNKNOWN`) 기록 → `inspect`가 scope 전체를 `scope requires reconciliation`으로 차단. **현 구조로는 어떤 재호출도 불가.**
- Ledger 제약: 1회 >$0.10 → `terminal`, 패널당 3회, scope 30회/$3, 일 60회/$6, 월 300회/$30. 패널 식별(fingerprint) = sha256(prompt+`[model=gemini-2.5-flash-image;aspect=..]`, REF 해시). 같은 패널에 다른 fingerprint 행이 있으면 `artifact identity changed`. visual quality enforce 모드는 이 fingerprint를 DB에 동결(`engine/quality/visual.py`).
- `openai` 3.40.0 SDK: `images.edit(image=[...최대 16장], prompt≤32000자, model, quality, size, output_format='png')`. gpt-image-2 계열은 임의 해상도(16의 배수, 1:3~3:1) 지원 → 4:5 = `1024x1280`. `input_fidelity`는 gpt-image-2에서 생략해야 함. 응답 `usage.input_tokens_details.{text_tokens,image_tokens}`, `usage.output_tokens` 제공. `gpt-image-1`은 2026-10-23 종료.
- 프롬프트에는 이미 `== STYLE LOCK ==` (Notion `GLOBAL_STYLE_BLOCK`)와 REF 규칙이 포함됨 (`engine/image/prompt_builder.py`).
- 하류 조립은 1080×1350 캔버스에 contain 배치 → 해상도 차이로 깨지지 않음.

## 2. 상태 전이 (이어서 생성)

```
episode 시작 provider=GEMINI
  P1..Pk-1  Gemini 성공 (PNG + success receipt 보존)
  Pk        Gemini → QUOTA_EXHAUSTED
              ├ ledger: state=failed, cost=0, reason=QUOTA_EXHAUSTED
              ├ provider := OPENAI (episode 내 sticky, 이후 Gemini 재호출 없음)
              └ 같은 패널 Pk를 OpenAI로 재예약·생성 (패널당 2회 사용)
  Pk+1..Pn  OpenAI 직접 생성 (패널당 1회)
  실패/중단 시 resume_episode 또는 재실행 → 성공 패널 reuse, 누락 패널만 생성
```

- Gemini 추가 재시도는 하지 않음: 잔액 소진은 재시도로 회복되지 않으며 패널당 3회 예산을 보존하기 위함.
- 폴백은 일반 경로(`retry_plan is None`)에서만 동작. 검토된 재시도 계획 경로(`reserve_retry`)는 현행대로 HOLD.
- 재실행 시 episode 시작 provider는 다시 GEMINI. 단, `generation-summary.json`의 동일 scope에 `QUOTA_EXHAUSTED`가 이미 기록돼 있으면 처음부터 OPENAI로 시작(재차 Gemini 429 과금 위험·호출 낭비 방지).

## 3. 오류 분류

### 3.1 Gemini → 폴백 트리거 (`classify_gemini_quota(exc) -> bool`)
아래 중 하나일 때만 `QUOTA_EXHAUSTED`:
1. `exc.code == 429` 또는 `exc.status == "RESOURCE_EXHAUSTED"`
2. `exc.code in {400, 403}` 이고 `exc.status in {"FAILED_PRECONDITION","PERMISSION_DENIED"}` 이며 message에 `billing|prepay|credit|spend|quota` 포함

그 외(401 인증, 400 INVALID_ARGUMENT, 5xx, timeout, 콘텐츠 거절)는 **현행 동작 유지**(폴백 금지).
※ 잔액 소진 시 Gemini의 실제 응답 형태는 저장소에 증거가 없음 → 폴백 발생 시 `code/status/message[:300]`을 private diagnostic에 기록해 첫 실측으로 분류표 확정.

### 3.2 OpenAI 결과 처리

| 결과 | 정산 | 동작 |
|---|---|---|
| PNG 성공 + usage 있음 | success, 실측 비용 | 저장·다음 패널 |
| usage 없음 | unknown | GenerationHold (현행 원칙) |
| `RateLimitError`(429, `insufficient_quota` 포함) | failed, cost 0 | `IMAGE_PROVIDERS_EXHAUSTED` Hold (양 공급자 소진) |
| `BadRequestError` code `moderation_blocked` | unknown (과금 여부 미확인 → fail-closed) | Hold, `PROVIDER_REFUSAL` 증거 기록 |
| 401/403 인증·권한·조직 미인증 | terminal, cost 0 | Hold (`PROVIDER_TERMINAL`) |
| 5xx / timeout / 연결 | unknown | Hold (현행 원칙) |
| PNG 검증 실패 | failed, 실측 비용 | 현행 invalid-image 규칙 |

OpenAI 실패 시 3차 공급자 없음.

## 4. 화풍 정합 (Gemini 스타일 맞춤)

1. **동일 입력**: Gemini와 같은 `prompt_text`(STYLE LOCK 포함), 같은 REF 이미지 순서.
2. **스타일 앵커**: 해당 에피소드에서 Gemini가 생성한 성공 패널 1장을 마지막 입력 이미지로 추가.
   - 선택 규칙: 폴백 시점 기준 가장 최근 성공 Gemini 패널(패널 번호 최대). 에피소드 내 고정(모든 OpenAI 패널 동일 앵커).
   - 앵커 없음(P1부터 소진): `assets/style/gemini_style_anchor.png`(승인된 과거 Gemini 패널, 신규 등록 필요)가 있으면 사용, 없으면 REF+STYLE LOCK만 사용.
3. **OpenAI 전용 프리앰블** (prompt 앞에 고정 문구, 코드 상수):
   ```
   INPUT IMAGES: images 1..N are character references (appearance only).
   The final image is a STYLE REFERENCE ONLY: match its line weight, inking,
   cel shading, color palette, lighting and rendering finish exactly.
   Do not copy its characters, composition, pose or background.
   ```
4. **출력 정규화**: 앵커와 종횡비가 같으면(오차 1% 이내) 앵커의 실제 픽셀 크기로 LANCZOS 리사이즈 후 PNG 저장 → 에피소드 내 해상도 일관.
5. 크기 요청: 4:5 → `1024x1280`, 비율 미지정 → `1024x1024`.
6. 입력 한도 검증: REF+앵커 ≤16장, prompt ≤32000자 위반 시 호출 전 Hold.

## 5. Ledger 정합 (SQL 변경 없음)

- OpenAI 호출도 **기존 패널 fingerprint 그대로** 예약(`ProductionGenerationGuard` 동일 인스턴스). 이유: visual quality 동결값·reuse 로직·`artifact identity changed` 규칙과 충돌 없이 이어서 생성하기 위함. fingerprint는 "패널 논리 입력" 식별자로 사용.
- 실제 공급자 입력은 `store_attempt_diagnostic(token,"inputs",…)`에 기록: `provider`, `model`, `quality`, `size`, `prompt_sha256`(프리앰블 포함), `ref_sha256`, `style_anchor_sha256`.
- Gemini quota 실패 정산: `finish_outcome(state="failed", actual_cost=0.0, reason="QUOTA_EXHAUSTED")` → 결과 코드 `INVALID_IMAGE`, hold 없음 → 같은 패널 재예약 가능.
  - 전제: 429/잔액 거절 요청은 미과금. 공식 문서 미확인 → 카나리 후 Google Cloud Billing 리포트로 검증.
- 패널당 3회 한도: Pk = Gemini 1 + OpenAI 1 (+ invalid PNG 재시도 1 여유).
- 성공 시 `p_actual_cost`가 $0.10 초과면 DB가 terminal 처리 → medium 유지 근거.

## 6. 비용 산정 (OpenAI)

`cost = text_tokens*T_IN + image_tokens*I_IN + output_tokens*OUT (per 1M)`

| 상수 | 값 | 근거 |
|---|---|---|
| `I_IN` 이미지 입력 | $8.00 | 외부 집계(공식 미확인) |
| `OUT` 이미지 출력 | $30.00 | 외부 집계(공식 미확인) |
| `T_IN` 텍스트 입력 | 미확정 | 카나리 전 확정 필요 |

상수는 `engine/image/openai_client.py`에 두고 `ICG_OPENAI_COST_*_PER_1M` 환경변수로 덮어쓰기 가능. 공식 단가 확인 전 운영 활성화 금지.

## 7. 모듈 설계

### 7.1 신규 `engine/image/openai_client.py`
```python
_MODEL_DEFAULT = "gpt-image-2"; _QUALITY_DEFAULT = "medium"
_ALLOWED_MODELS = {"gpt-image-2", "gpt-image-2-2026-04-21",
                   "gpt-image-2.5-sunburst", "gpt-image-2.5-flare"}
STYLE_PREAMBLE = "..."  # §4.3

def fallback_enabled() -> bool          # ICG_IMAGE_OPENAI_FALLBACK_ENABLED true/false, 그 외 Hold
def fallback_ready() -> bool            # enabled and OPENAI_API_KEY 존재
def _get_client()                        # OpenAI(api_key=..., max_retries=0, timeout=180)
def _size_for(aspect: str | None) -> str # "4:5"->"1024x1280", None->"1024x1024", 그 외 Hold
def calc_cost(usage) -> float | None
def generate_one(client, prompt, ref_paths, style_anchor, aspect)
    -> tuple[bytes, float | None, dict]  # png bytes, cost, diagnostics
    # NoImageResponse / ProviderQuotaExhausted / 기타 예외로 매핑
def normalize_to_anchor(png: bytes, anchor: Path | None) -> bytes
```

### 7.2 수정 `engine/image/gemini_client.py`
- `class QuotaExhausted(GenerationHold)` + `classify_gemini_quota(exc)` 추가.
- `generate_panel(..., provider_state: ProviderState | None = None)`:
  - `provider_state.active == "openai"` 이면 Gemini 호출 생략 → OpenAI 경로.
  - Gemini `except Exception` 분기 앞에 quota 분기: fallback_ready()·plan 없음·provider_state 존재 시에만 `failed/0/QUOTA_EXHAUSTED` 정산 후 `provider_state.switch(reason)` → 같은 루프에서 OpenAI 시도. 조건 미충족 시 현행 Hold.
  - JSONL 로그·summary 레코드에 `provider`, `model` 기록 (Gemini 레코드 형식 보존).
- `generate_episode`: `ProviderState` 1개 생성·전 패널 공유, 스타일 앵커 결정, summary에 `provider_by_panel`, `fallback_reason`, `fallback_from_panel`, `cost_by_provider` 추가(파일 전용; DB run_status 키 화이트리스트는 변경 안 함).
- `ProviderState`: `active`, `switched_at_panel`, `reason`, `style_anchor`.

### 7.3 수정 `scripts/run_market.py` (`step_image`)
- 반환 비용 유지(`gemini_cost_usd` = 총 이미지 비용, 하위호환). `{episode_id}_images.json`에 `provider_by_panel`, `cost_by_provider` 추가.
- 폴백 발생 시 `logger_inst.info("STEP_6", "IMAGE_PROVIDER_FALLBACK from=P{k} reason=...")`.

### 7.4 워크플로 `.github/workflows/run_market.yml` (job env)
```yaml
OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
ICG_IMAGE_OPENAI_FALLBACK_ENABLED: ${{ vars.ICG_IMAGE_OPENAI_FALLBACK_ENABLED || 'true' }}
ICG_OPENAI_IMAGE_MODEL: ${{ vars.ICG_OPENAI_IMAGE_MODEL || 'gpt-image-2' }}
ICG_OPENAI_IMAGE_QUALITY: ${{ vars.ICG_OPENAI_IMAGE_QUALITY || 'medium' }}
```
롤백: repo variable `ICG_IMAGE_OPENAI_FALLBACK_ENABLED=false`. 키 미등록이면 폴백 비활성(경고 로그) + 현행 Hold.

### 7.5 `requirements.txt`
`openai>=3.40.0` 추가 (gpt-image-2 계열·임의 size 지원 확인 버전).

### 7.6 키 점검 (preflight, 선택)
`scripts/market_preflight.py`에 OpenAI `models.retrieve(ICG_OPENAI_IMAGE_MODEL)` 무과금 점검 추가 → 키 유효성·모델 접근 권한(조직 인증 포함) 사전 확인. 실패 시 경고만(Gemini 정상 경로는 막지 않음).

## 8. 테스트 설계 (모두 오프라인 mock, 실과금 0)

| 파일 | 케이스 |
|---|---|
| `tests/test_openai_image_fallback.py` | Gemini 429 → OpenAI 성공, ledger `failed/0/QUOTA_EXHAUSTED` 후 success |
| | P3 소진 → P1·P2 Gemini 보존, P3~Pn OpenAI, Gemini 재호출 0회 |
| | 플래그 off / 키 없음 → 현행 Hold와 동일 |
| | retry_plan 경로 → 폴백 금지 |
| | Gemini 401·400 INVALID_ARGUMENT·5xx → 폴백 금지 |
| | OpenAI 429 → `IMAGE_PROVIDERS_EXHAUSTED` Hold |
| | OpenAI moderation_blocked → unknown 정산 + Hold |
| | usage 누락 → unknown Hold |
| | REF+앵커 17장 → 호출 전 Hold |
| | 앵커 선택(최근 성공 Gemini 패널)·리사이즈·size 매핑 |
| | 비용 계산, >$0.10 수신 시 Hold 전파 |
| | 재실행 시 summary의 QUOTA_EXHAUSTED → OPENAI로 시작, 성공 패널 reuse |
| `tests/test_workflow_run_market.py` | 신규 env 키 1회 정의, secrets/vars 컨텍스트만 사용 |
| 기존 | `pytest` 전체, `ruff` 통과 |

## 9. 롤아웃

1. 구현 + 오프라인 테스트 (과금 0)
2. 사전 조건: `OPENAI_API_KEY` Secret 등록, OpenAI 크레딧·조직 인증 확인, 공식 단가(T_IN 포함) 확인
3. 카나리: 과거 에피소드 1건에서 2~3패널 OpenAI 강제 생성(별도 scope, 예상 ≤$0.3) → 화풍 비교·usage 실측·$0.10 이하 확인
4. 운영 활성화 (`vars` 기본 true)
5. 첫 실발생 시 Gemini 오류 형태 실측 → §3.1 분류표 확정

## 10. 미확인 사항 (구현 전/카나리에서 확정)
1. OpenAI 공식 단가(특히 gpt-image-2 텍스트 입력), 4:5 출력 토큰 수
2. Gemini 잔액 소진 시 실제 오류 `code/status`
3. Gemini 429/OpenAI 거절 요청의 과금 여부
4. 스타일 앵커 고정 자산(`assets/style/gemini_style_anchor.png`) 선정 — 마스터 승인 필요
