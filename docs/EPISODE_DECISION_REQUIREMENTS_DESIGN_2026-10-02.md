# 최종 에피소드 판정 — 요구사항·상세설계·검증

## 기준과 요구사항

- 저장소: yumens2-byte/investment-comic-gemini
- 기준 main: 7065d6d966c0cc16ddaa068a71f0454a1aeafbc0
- 요구사항: https://app.notion.com/p/3ed9208cbdc38185a545ef333bcc4cd0
- 상세설계: https://app.notion.com/p/3ed9208cbdc381d89526df5511460800
- 이해관계자 검토는 콘텐츠·시장 분석·시스템 운영 관점의 역할 검토다. 실제 외부 참석자 회의가 아니다.
- 합의: 강제 전투가 아니라, 발행된 NO_BATTLE 3회 연속 이후 다음 회차의 서사 변화 검토. 3회는 임시 편집 기준이다.
- 시장 수치·위험도·DSS·승패 계산·각성 조건·캐릭터 REF는 변경하지 않는다.
- 현재 생성된 회차와 콘텐츠 QC 보류는 소급 변경하거나 해제하지 않는다.

| 요구사항 | 구현 | 검증 |
|---|---|---|
| FR-01 최종 타입·시나리오·폼 보너스 통합 | episode_decision.resolve_episode_decision → 캐스팅·전투 계산 앞에서 확정 | Day64 재현, 타입 계약 |
| FR-02 최신 비전투 반복 검토 | storyline_guard.latest_streak, threshold=3 | 최신 prefix와 오래된 tail 분리 |
| FR-03 시장과 편집 분리 | 근거 있는 MEDIUM/HIGH + BATTLE/SHOCK만 기본 배틀, 그 외 TACTICAL_ACTION | LOW·근거 없음·NORMAL 예외 |
| FR-04 카논 보호 | 수동·각성 후 회복·등장·EPIC·첫 전투 단계, 기존 전투/폼 및 CONFLICT/FLASHBACK 보존 | 보호 단계·폼 보너스·회복 테스트 |
| FR-05 이력 계약 | published, 현재 날짜 이전, 날짜·회차 내림차순 | 시나리오·outcome 쿼리 계약 |
| FR-06 재실행·소급 금지 | 저장 결정/context 재사용; 기존 회차의 context 없으면 중단 | 신규/레거시 재실행 및 누락 차단 |
| FR-07 비전투 행동 | Claude 입력과 이미지 입력에 같은 action_mode 전달 | 대본 요청 캡처, 이미지 프롬프트 및 카드 테스트 |
| FR-08 추적성 | analysis_ctx_json 및 script_json의 _episode_decision, 판정 로그 | 저장 메타데이터·context 정합성 |

## 상세설계

1. 분석 시작 전에 저장된 context와 기존 회차 존재 여부를 확인한다. 버전 있는 판정은 검증 후 context 전체를 재사용하고, 레거시 회차는 기존 context를 유지한다.
2. 새 회차는 시장 이벤트·위험도·v3 에피소드 후보를 기존 방식으로 계산한다.
3. 발행 완료 이력만 읽어 최신 NO_BATTLE 연속 횟수를 계산한다. 같은 날짜에서는 episode_no 내림차순을 사용한다. 현재 날짜는 제외한다.
4. 최종 결정은 후보 타입·시나리오, 최종 타입·시나리오·폼 보너스·슬라이드 수, action_mode, 반복 횟수·기준·사유를 함께 기록한다.
5. 우선 규칙은 보존한다. 일반 비전투 3회 이상이면 근거/허용 구간에 따라 BATTLE/ONE_VS_ONE/COMBAT 또는 TACTICAL/NO_BATTLE/TACTICAL_ACTION을 선택한다. 편집에 의한 배틀은 form_bonus=0이며 각성을 새로 판정하지 않는다.
6. 장기 아크 기본 AFTERMATH는 최신 발행 outcome이 실제 전투 결과일 때 유지한다. 예전 전투 후 이미 관찰편이 발행됐다면 INTEL 후보로 대체한다. STEP_0 회복편은 먼저 반환되므로 유지된다.
7. 최종 결정 후 기존 캐스팅과 전투 계산을 실행한다. v3 판정 또는 새 판정 저장 실패 시 중단한다. v3 flag OFF 경로는 기존 다양성 정책을 사용한다.
8. 대본 반환 및 저장 JSON에 _episode_decision을 보존한다. 같은 프로세스의 image 단계에도 context에서 전달하여 저장 이후 재개 경로와 동작을 맞춘다.
9. 이미지 입력의 패널 시나리오가 최종 결정과 충돌하면 중단한다. TACTICAL_ACTION에서는 추적·회피·구출·장치 조작을 지시하며, 공격·승패·새로운 적은 허용하지 않는다. 시장정보·면책 카드는 배경 전용 규칙을 유지한다.

## 운영·장애·호환

- DB 테이블·마이그레이션·권한 변경 없음. 기존 JSON 메타데이터만 확장한다.
- 기존 생성 회차에 신규 결정을 붙여 재판정하지 않는다. context 누락/손상은 원인 확인 후 복구한다.
- 이력 조회 실패 시 기존의 빈 이력 fallback을 유지한다. 이 경우 반복 보정은 적용되지 않으며 운영 로그를 확인해야 한다.
- JSON 저장과 에피소드 발행은 단일 DB 트랜잭션이 아니다. 기존 워크플로의 실행 동시성 제어를 사용하며 이번 변경이 다중 writer 원자성을 추가 보장하지 않는다.
- 새 비전투 행동은 프롬프트 계약이다. 생성 이미지의 실제 행동·외형 준수는 별도 파일럿/콘텐츠 검수로 확인해야 한다.
- 본 작업의 단위·회귀 검증은 유료 생성, 운영 DB 쓰기, 실발행 없이 수행한다.

## 변경 본수

- 운영 소스 6본: scripts/run_market.py, engine/narrative/storyline_guard.py, engine/narrative/episode_type_engine.py, engine/narrative/episode_decision.py(신규), engine/narrative/claude_client.py, engine/image/prompt_builder.py.
- 테스트 5본: test_episode_decision.py, test_storyline_guard.py, test_episode_decision_reuse.py, test_episode_decision_narrative.py, test_episode_decision_image.py.
- 문서 1본: 본 문서. 코드·테스트는 예상 11본과 동일하며 문서 포함 총 12본이다.

## 검증 명령

```bash
python -m pytest tests/test_episode_decision*.py tests/test_storyline_guard.py -q
python -m pytest tests -q
ruff check .
git diff --check
```

검증 결과와 PR 상태는 Notion 상세설계의 완료 보고에 기록한다. 운영 반영과 유료 생성 파일럿은 개발 완료와 분리한다.
