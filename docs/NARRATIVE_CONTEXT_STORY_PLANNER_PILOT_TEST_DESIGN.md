# Narrative Context & Story Planner Pilot Test Design

## 목적

`Narrative Context Pack`과 `StoryBeatPlan` 파일럿은 Claude가 8컷 에피소드를 생성하기 전에
시장 근거와 패널별 서사 계약을 고정해 환각을 줄이고, 기존 파이프라인은 feature flag로 안전하게 유지하는 것을 목표로 한다.

## 상세 설계 검증 범위

1. **Context Pack 생성**
   - `delta`, 선택 뉴스, 이벤트 일정, 섹터 히트맵을 입력으로 받아 `version=pilot-1` 패킷을 만든다.
   - `top_evidence`는 최대 3개로 압축하고, 뉴스가 있으면 최소 1개 뉴스 evidence가 포함되어 숫자만 있는 스토리를 피한다.
   - `prohibited_claims`는 프롬프트와 품질 게이트에서 동일한 factuality guardrail로 사용한다.

2. **StoryBeatPlan 생성**
   - 항상 1~8번 패널을 순서대로 만들고 8번은 `DISCLAIMER`로 고정한다.
   - 1~5번 패널은 evidence id를 연결해 시장 근거가 서사 전개에 남도록 한다.
   - `NO_BATTLE`은 빌런 required character를 강제하지 않아 관찰형 에피소드와 호환된다.

3. **Prompt fallback**
   - Notion 런타임 템플릿이 아직 `Narrative Context Pack` / `Story Beat Plan` 블록을 갖고 있지 않아도
     `prompt_tpl` fallback이 두 블록을 뒤에 추가해야 한다.
   - 이 계약은 `tests/test_pilot_flow_contract.py`에서 legacy template monkeypatch로 검증한다.

4. **Grounding gate**
   - 알고 트레이딩 비중/캐스케이드 같은 구체 시장 주장은 evidence에 관련 근거가 있을 때만 통과한다.
   - strict 모드에서는 unsupported claim이 `StoryGroundingError`로 실패해야 하며,
     관련 evidence가 추가되면 동일 script가 통과해야 한다.

## 파일럿 반복 테스트 루프

```bash
python -m pytest tests/test_pilot_flow_contract.py -q
python -m pytest tests/test_workflow_run_market.py tests/test_test_suite_integrity.py -q
python -m pytest tests/ -q
ruff check . --line-length=100
```

## 배포 전 확인 기준

- workflow에는 `github.event.inputs` 직접 참조가 없어야 한다.
- `NARRATIVE_CONTEXT_ENABLED`와 `STORY_PLANNER_ENABLED` job env 정의는 각각 1회여야 한다.
- `tests/test_test_suite_integrity.py`가 중복 top-level test 함수명을 차단해야 한다.
- 전체 테스트와 `ruff`가 통과해야 다음 PR로 배포한다.
