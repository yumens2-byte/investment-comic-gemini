# 거절 후 장면 수정·재시도 보완 상세설계

## 현재 문제와 목표

현재 ordinary 경로는 검토 대체안이 없으면 content refusal을 보류한다.
기존 retry adapter는 검토·등록된 대체 prompt가 있으면 최대 2회 추가 호출하지만,
그 대체안을 안전하게 준비·등록하는 정식 경로가 없었다.

이번 변경은 검토된 실제 장면 수정안을 source-bound plan으로 준비하고,
원본 대본과 DB 계획을 원자적으로 등록하여 기존 adapter의 제한 재시도를 사용할 수 있게 한다.
무검토 LLM 자동 재작성이나 단순 금칙어 치환은 구현하지 않는다.
제공자의 세부 거절 근거가 없으면 특정 원인을 단정하지 않는다.

## 처리 순서

1. 정확한 persisted script와 최종 base prompt를 비공개로 확보한다.
2. 각 paid panel에 1~2개 수정 장면을 검토해 준비한다.
3. prepare가 cast·REF·source hash·이야기 단서·새 action과 motion을 검증한다.
4. 명시적 register가 CAS로 script의 retry 메타만 갱신하고 모든 DB plan을 같은 transaction에 넣는다.
5. stage=image에서 image_retry_v2=true로 실행한다.
6. 최초 입력이 콘텐츠 거절이면 정산·진단 저장 후 등록된 다음 실제 장면으로 전환한다.
7. 최초 포함 패널 평생 3회 및 기존 비용/횟수 한도를 넘으면 중단한다.
8. 타임아웃·unknown usage·정산/진단 실패·privacy/recitation 등 별도 검토 이유는 즉시 보류한다.
9. 성공 PNG는 hash를 검증해 재사용하며, 거절된 fingerprint는 다시 호출하지 않는다.

동일한 거절 입력을 다시 보내거나 safety settings를 낮추지 않는다.
DB ledger와 기존 original/recovery/retry RPC의 중단 기준은 변경하지 않는다.

## 장면 계약

image-retry-plan-2는 원본 panel의 action/setting/narration/key_text/cast를 hash로 고정한다.
대체 장면마다 action, setting, complete prompt, camera, target_kind, motion,
physical_contact=false, weapon_discharge=false, injury=NONE, story_facts, change_note를 요구한다.

action은 원본 및 다른 대체안과 달라야 한다.
camera나 스타일만 바꾸고 action을 유지하면 차단한다.
TURN/LEAN/REACH/PROP_INSPECTION/CROUCH/ENVIRONMENT motion을 허용하며,
최대 두 대체안의 motion 종류도 달라야 한다. 서 있기·멈춰 있기만으로는 대체안을 만들 수 없다.
모든 positive action/setting/prompt에 기존 scene validator를 적용한다.

예: 압박 장면을 '누나가 몸을 돌려 독립 표시를 확인' 또는
'방패 앞면을 기울여 확인하되 내부 균열은 미발견'으로 실질적으로 바꾼다.
공격을 숨기는 표현이나 카메라 수정만으로 동일 장면을 재호출하지 않는다.

story_facts는 검토자가 확인한 보존 단서다. 문자열 포함 검사는 사실의 자동 의미 검증이 아니다.
캐릭터/소품/서사 의미 및 각 장면의 시각적 품질은 검토 대상이며 제공자 수락을 보장하지 않는다.

## 준비·등록 인터페이스

scripts/prepare_image_retry_plans.py
- --source: 정확한 persisted source JSON
- --base-prompts: panel index를 key로 한 실제 최종 prompt JSON
- --repairs: panel index별 repairs/story_facts/actor/note JSON
- --output: output/ 바깥의 비공개 새 파일
- 기본 실행은 준비만 수행하며 DB write와 paid call은 0이다.
- --register --confirm REGISTER_REVIEWED_REPAIR_PLANS는 별도 명시적 DB 등록이다.

CLI 출력 파일에는 source/candidate/fingerprints가 있으며 mode0600, exclusive create를 사용한다.
source는 호출 환경의 Python에서 직렬화·hash한다. 외부 JSON 전달이 100.0을 100으로 바꾸는
표현 손실에 의존해 source hash를 재구성하지 않는다.

## DB 등록과 기존 이력

추가 SQL: docs/sql/image-generation-register-repair-plans-v2.sql.
service_role만 호출하며 anon/authenticated는 실행할 수 없다.
정확한 narrative_done episode_no1, 원본 전체 비교, 모든 paid panel coverage,
단서/cast/action source 일치, 2~3개 서로 다른 fingerprint, immutable plan을 확인한다.
공개 narrative, 카드, source state는 바꾸지 않는다.

기존 호출이 success뿐인 경우에는 base fingerprint가 동일해야만 등록할 수 있다.
reserved/unknown/failed/terminal이 이미 있으면 이번 준비 RPC는 등록하지 않는다.
해당 상태는 기존의 명시적 reviewed recovery 경로로 처리해야 한다.
기존 실패 기록을 삭제하거나 budget을 초기화하지 않는다.

## 범위와 운영반영 조건

현재 기본 aspect=None인 기존 이미지 경로가 대상이다.
_scene_performance_v2/4:5 성능 패키지는 다른 fingerprint 계약이므로 준비 단계에서 차단한다.
기존 version1 계획은 호환 유지한다. 기존 플래그를 켜는 것만으로 수정안이 생성되지는 않는다.
수정안의 검토·등록이 선행되어야 거절 시 대체 장면으로 자동 전환한다.

운영반영 전 CI: 전체 pytest/Ruff, 신규 SQL registration/cursor 계약,
기존 budget/settlement/diagnostic/refusal/reuse/unknown 계약을 통과해야 한다.
SQL 배포와 계획 등록, 유료 파일럿은 이번 PR에서 실행하지 않는다.
새 공식 공통 recovery workflow는 이 prepared plan/register 인터페이스를 확장점으로 사용할 수 있다.

단일 PGlite backend 테스트는 다중 세션 lock 경합과 실제 제공자 수락을 증명하지 않는다.
