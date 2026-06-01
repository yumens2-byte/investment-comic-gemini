# Notion Handoff — Narrative Context / Story Planner Pilot 작업 히스토리

> 작성일: 2026-06-01  
> 목적: 사용자가 에러 확인을 요청한 시점부터 현재까지 진행한 작업을 Notion에 붙여넣어 다음 작업자가 이어서 진행할 수 있도록 정리한다.  
> 범위: `run_market` 파일럿, workflow/input normalization, story grounding, Gemini cost logging, snapshot quality, 테스트/배포 오류 대응.

---

## 1. 최초 문제 인식

### 1.1 `run_market` 운영 로그 점검 요청

사용자가 `python -m scripts.run_market` 실행 로그와 생성된 에피소드 JSON을 제공하며 데이터/스토리 품질을 점검해 달라고 요청했다.

관찰된 주요 사항:

- 데이터 수집 단계는 완료됐지만 외부 API warning이 반복됐다.
  - FRED 일부 series retry 후 성공.
  - yfinance TzCache 생성 warning.
  - Crypto.com mark price API 404.
  - LunarCrush API 402 Payment Required 후 cache fallback.
- narrative 결과에서 `알고 트레이딩 비중 급증`, `알고 캐스케이드 감지/붕괴/정상화` 같은 구체 시장 주장이 생성됐지만, 실제 제공된 market evidence에는 해당 claim을 직접 뒷받침하는 데이터가 부족했다.
- Gemini image 단계에서 P8 생성 중 `AttributeError` retry가 발생했으나 최종 8/8 패널 생성은 성공했다.
- Gemini cost가 `$0.0000`으로 남아 usage/cost observability가 부족했다.

### 1.2 목표로 재정의한 문제

1. Claude narrative가 시장 근거 없이 스토리 장치를 만들어내는 문제를 줄인다.
2. 8패널 구조를 사전에 deterministic하게 고정해 coherence를 높인다.
3. workflow에서 파일럿 기능을 flag로 안전하게 켜고 끌 수 있게 한다.
4. stage가 분리되어 실행되어도 context/plan이 저장·복원되는지 검증한다.
5. 배포 전 테스트/lint/workflow 오류를 반복적으로 제거한다.

---

## 2. 구현한 파일럿 핵심 기능

### 2.1 Narrative Context Pack

추가/수정 파일:

- `engine/analysis/story_context_builder.py`
- `scripts/run_market.py`
- `tests/test_story_context_builder.py`

역할:

- `delta`, optional news, economic events, sector heatmap, battle result를 compact한 `narrative_context_pack`으로 변환한다.
- pack version은 `pilot-1`.
- `top_evidence`, `market_cause`, `foreshadow`, `scene_symbols`, `prohibited_claims`를 포함한다.
- 뉴스가 있으면 숫자 metric만 남지 않도록 최소 1개 news evidence를 포함하는 방향으로 설계했다.

검증 포인트:

- JSON serializable.
- `top_evidence` 최대 개수 유지.
- metric/news evidence id가 prompt와 story plan에서 참조 가능.

### 2.2 StoryBeatPlan

추가/수정 파일:

- `engine/narrative/story_planner.py`
- `engine/narrative/schema.py`
- `tests/test_story_planner.py`

역할:

- deterministic 8-panel story contract 생성.
- `StoryBeat` / `StoryBeatPlan` Pydantic schema 추가.
- panel index는 1..8 순서여야 하고 panel 8은 반드시 `DISCLAIMER`.
- `NO_BATTLE` 시나리오에서는 villain required character를 강제하지 않음.

검증 포인트:

- 8개 panel beat 유지.
- 마지막 beat `DISCLAIMER` 강제.
- panel 순서 깨짐 시 validation error.

### 2.3 Prompt / Claude integration

추가/수정 파일:

- `config/prompts/narrative_user.j2`
- `engine/narrative/prompt_tpl.py`
- `engine/narrative/claude_client.py`
- `tests/test_prompt_tpl.py`

역할:

- prompt에 `narrative_context_pack`, `story_beat_plan` 전달.
- Notion runtime template이 아직 업데이트되지 않은 경우 fallback block을 뒤에 append.
- 과거 테스트 실패였던 `Narrative Context Pack` / `Story Beat Plan` 미출력 문제를 fallback으로 보완.

검증 포인트:

- legacy template에서도 파일럿 block이 출력된다.
- Notion template에 이미 block이 있으면 중복 append하지 않는다.

### 2.4 Story grounding quality gate

추가/수정 파일:

- `engine/narrative/story_quality.py`
- `scripts/run_market.py`
- `tests/test_story_quality.py`

역할:

- 알고 트레이딩 비중, 알고 캐스케이드 감지/붕괴/정상화 등 unsupported claim을 감지한다.
- evidence에 알고리즘 거래 관련 근거가 없으면 warning 또는 strict mode error로 차단한다.
- pilot flag enabled일 때 narrative 이후 gate로 사용한다.

검증 포인트:

- unsupported algo-trading claim은 strict mode에서 `StoryGroundingError`.
- 관련 evidence가 제공되면 통과.

### 2.5 Gemini cost / usage logging

추가/수정 파일:

- `engine/image/gemini_client.py`
- `tests/test_gemini_client.py`

역할:

- Gemini SDK response의 `usage_metadata`를 snake_case / camelCase / dict 형태로 추출.
- metadata가 없으면 prompt length + reference image count 기반으로 token estimate.
- panel별 `cost_usd`, latency, token info를 기록하고 episode total cost를 반환.
- response shape 차이로 `AttributeError`가 나는 부분을 `_response_parts()` 등으로 완화.

검증 포인트:

- snake_case/camelCase metadata 추출.
- total token 기반 output fallback.
- missing content response에서 AttributeError 없이 빈 parts 반환.

### 2.6 Snapshot quality summary

추가/수정 파일:

- `engine/data/snapshot_writer.py`
- `tests/test_snapshot_writer_quality.py`

역할:

- snapshot payload의 critical/optional field 누락을 요약한다.
- critical data gap은 warning으로 노출해 데이터 품질 확인에 사용한다.

---

## 3. Workflow / 배포 오류 대응 히스토리

### 3.1 workflow input normalization

수정 파일:

- `.github/workflows/run_market.yml`
- `tests/test_workflow_run_market.py`

작업 내용:

- `github.event.inputs` 직접 참조를 제거하고 `inputs.*` → job env (`TARGET_DATE`, `RUN_STAGE`) 방식으로 정규화했다.
- `narrative_context`, `story_planner` workflow_dispatch input 추가.
- `NARRATIVE_CONTEXT_ENABLED`, `STORY_PLANNER_ENABLED` env 추가.
- rollout check step에서 파일럿 module import 및 workflow sanity check 수행.

### 3.2 중복 pilot flag env 정의 오류

발생 오류:

```text
FAILED tests/test_workflow_run_market.py::test_run_market_workflow_has_single_pilot_flag_definitions
assert 2 == 1
where count('NARRATIVE_CONTEXT_ENABLED:') == 2
```

원인:

- workflow 내에 기존 `inputs.*` 기반 env 정의와 legacy `github.event.inputs.*` 기반 env 정의가 중복으로 남아 있었다.
- 또한 테스트가 파일 전체 문자열 count 방식이라 guard code/comment에 같은 key가 들어가면 false positive가 날 수 있었다.

대응:

- legacy `github.event.inputs` env block 제거.
- workflow rollout check는 실제 job env line만 anchored regex로 count하도록 변경.
- test도 YAML 파싱 + anchored env key count 방식으로 강화.

검증:

```bash
python -m pytest tests/test_workflow_run_market.py -q
python -m pytest tests/ -q
ruff check . --line-length=100
```

### 3.3 `scripts/run_video_trailer.py` syntax/ruff 오류

발생 오류:

```text
invalid-syntax: Expected `else`, found `:`
... logger.debug(f"[PRE-OP] payload preview:\n{message}")
```

원인:

- f-string 내부 newline이 깨져 Python parser가 이후 block 전체를 syntax error로 해석했다.

대응:

- debug log string formatting을 정상 escape된 `\n` 형태로 수정.
- `tests/test_run_video_trailer_syntax.py` 추가해 `py_compile`로 syntax를 방어.

검증:

```bash
python -m pytest tests/test_run_video_trailer_syntax.py -q
ruff check . --line-length=100
```

### 3.4 ruff F811 duplicate test definition 오류

발생 오류:

```text
F811 Redefinition of unused `test_run_market_workflow_yaml_parses`
```

원인:

- merge/update 과정에서 `tests/test_workflow_run_market.py`에 같은 test function이 중복 정의됨.

대응:

- 중복 정의 제거.
- `tests/test_test_suite_integrity.py` 추가.
- 이 테스트는 `tests/test_*.py`를 AST로 파싱하여 같은 파일 안의 top-level `test_*` 함수명이 중복되면 실패한다.

검증:

```bash
ruff check tests/test_workflow_run_market.py tests/test_test_suite_integrity.py --line-length=100
python -m pytest tests/test_workflow_run_market.py tests/test_test_suite_integrity.py -q
```

---

## 4. 추가한 파일럿 E2E 계약 테스트

추가 파일:

- `tests/test_pilot_flow_contract.py`
- `docs/NARRATIVE_CONTEXT_STORY_PLANNER_PILOT_TEST_DESIGN.md`

목적:

- 개별 unit test만으로는 `Context Pack → StoryBeatPlan → Prompt fallback → Grounding gate`의 전체 계약을 보장하기 어렵기 때문에 E2E contract test를 추가했다.

검증 내용:

1. metric/news/events/sectors 기반 context pack 생성.
2. news evidence가 pack에 포함되는지 확인.
3. StoryBeatPlan이 8 panel + 마지막 `DISCLAIMER`를 유지하는지 확인.
4. legacy Notion template monkeypatch 상태에서도 prompt fallback이 `Narrative Context Pack` / `Story Beat Plan` block을 추가하는지 확인.
5. unsupported algo-trading claim은 strict mode에서 실패하고, 관련 evidence 추가 시 통과하는지 확인.

반복 테스트 루프:

```bash
python -m pytest tests/test_pilot_flow_contract.py tests/test_workflow_run_market.py tests/test_test_suite_integrity.py -q
python -m pytest tests/ -q
ruff check . --line-length=100
```

---

## 5. 현재 상태 요약

현재까지 확인한 상태:

- `python -m pytest tests/ -q` 통과.
- `ruff check . --line-length=100` 통과.
- workflow에는 legacy `github.event.inputs` 직접 참조가 없어야 한다는 테스트가 존재한다.
- pilot flag env 정의는 anchored line 기준으로 각각 1회만 허용된다.
- 중복 top-level test function은 AST integrity test로 차단된다.
- pilot E2E contract test가 context/plan/prompt/grounding 흐름을 방어한다.

주의:

- 이 문서는 Notion에 붙여넣기 가능한 handoff 문서로 작성되었다.
- 현재 작업 환경에는 특정 Notion page/database target 정보가 제공되지 않아 API로 직접 업로드하지 않았다.
- Notion 업로드가 필요하면 `NOTION_API_KEY`와 대상 page/database ID, 또는 기존 Notion tracker 구조를 지정해야 한다.

---

## 6. 다음 작업 제안

### 우선순위 P0 — 배포 안정화

1. 새 PR에서 CI가 실제로 다음을 통과하는지 확인한다.
   - `ruff check . --line-length=100`
   - `python -m pytest tests/ -q`
2. GitHub Actions `run_market.yml`의 rendered workflow에 legacy block이 남아 있지 않은지 확인한다.
3. 이전 PR update가 막히는 경우 새 PR로 진행한다.

### 우선순위 P1 — 운영 파일럿 검증

1. `NARRATIVE_CONTEXT_ENABLED=true`, `STORY_PLANNER_ENABLED=true`로 analysis → narrative stage를 실행한다.
2. `daily_analysis.analysis_ctx_json`에 다음 key가 저장되는지 확인한다.
   - `narrative_context_pack`
   - `story_beat_plan`
3. narrative 결과에서 unsupported algo-trading claim이 warning/error로 잡히는지 확인한다.

### 우선순위 P2 — 품질 고도화

1. story_quality rule을 algo-trading 외의 unsupported claim으로 확장한다.
   - 예: 특정 CPI/FOMC 결과, oil supply shock, credit spread crisis 등.
2. 실제 news/economic calendar source가 붙으면 `Narrative Context Pack`에 source attribution을 강화한다.
3. Gemini cost가 계속 `$0.0000`으로 나오면 SDK response metadata shape를 추가 샘플링해 parser fixture를 보강한다.

---

## 7. 관련 커맨드 기록

```bash
git status --short --branch
git log --oneline -12
rg -n "github\.event\.inputs|NARRATIVE_CONTEXT_ENABLED:|STORY_PLANNER_ENABLED:" .github/workflows/run_market.yml tests/test_workflow_run_market.py
python -m pytest tests/test_workflow_run_market.py -q
python -m pytest tests/test_pilot_flow_contract.py tests/test_workflow_run_market.py tests/test_test_suite_integrity.py -q
python -m pytest tests/ -q
ruff check . --line-length=100
```
