# 공통 이미지 복구 모듈 상세설계 및 운영 가이드

기준: main a4c0910a08c52cfe9b7ad1f3456e03479d2397e7.
이 변경은 별도 브랜치에서 구현·회귀 검증한다. 운영 병합, 운영 DB 변경, 유료 생성,
기존 파일 삭제는 수행하지 않는다.

## 1. 문제와 목표

2026-10-21 복구에서는 날짜·실행 ID·revision을 고정한 YAML, Python helper,
요청 JSON을 추가했다. 이 방식은 같은 종류의 장애가 생길 때 파일이 계속 늘어난다.
또한 외부 도구에서 받은 원본 JSON이 100.0을 100으로 바꾸면 전체 대본 해시가 달라진다.

새 구조는 하나의 수동 워크플로와 하나의 공통 서비스로 날짜별 복구를 처리한다.
새 장애는 검토 장면 JSON과 요청 JSON 데이터만 추가하고, 새 YAML/실행 코드를 만들지 않는다.
현재 기능은 **미정산이 없는 단일 콘텐츠 거절 회차의 명시적 새 revision 복구**다.
부분 성공 이미지와 원본 거절 기록을 보존하고 기존 예산을 초기화하지 않는다.

| 기존 | 공통화 후 |
|---|---|
| 날짜별 push 트리거 YAML | image_recovery.yml 한 개, workflow_dispatch만 |
| 날짜·P4·성공 3장을 고정한 helper | source/ledger/request에서 검증하는 recovery_service |
| 외부 JS에서 대본 해시 계산 | Python DB 응답 원본에서 inspect가 계산 |
| 코드 커밋이 유료 복구를 시작 | inspect → prepare → 명시적 execute |
| 성공 여부만 확인 | 원본 PNG hash·요청 hash·후보 hash·CAS·수동 조립 게이트 |

## 2. 구성과 책임

| 파일 | 책임 |
|---|---|
| .github/workflows/image_recovery.yml | 수동 입력, 원본 artifact 다운로드, 공통 CLI, 허용된 결과 업로드 |
| scripts/image_recovery.py | 입력/출력 라우팅, 검증된 GITHUB_OUTPUT, 비공개 오류 원문 차단 |
| engine/image/recovery_service.py | 요청 검증, source/ledger snapshot, 해시와 PNG 검증, 모드별 오케스트레이션 |
| scripts/prepare_image_recovery.py | 기존 검토 장면·캐스트·REF·후보 구성 및 v3 CAS 등록 재사용 |
| scripts/run_market.py --stage image | 기존 DB 예약·정산·비용·PNG·image_generated 상태 계약 재사용 |
| tests/test_common_image_recovery.py | provider/운영 DB 호출 없는 회귀 검증 |
| docs/image-recovery-cleanup-inventory-20261021.md | 일회성 삭제 후보와 유지/이관 조건 |

공통 서비스가 대본 생성·분석·조립·발행을 호출하지 않는다. 기본 모드는 inspect이며,
prepare와 inspect는 DB 쓰기와 이미지 provider 호출이 0이다.

## 3. 실행 상태와 트랜잭션 경계

1. **inspect**: 날짜를 정규화하고 episode_no=1의 정확한 원본과 ledger를 읽는다.
   outcome-v3 capability, narrative_done, state-candidate-1, 단일 terminal, 알려진 비용을 검사한다.
   요청 템플릿을 공개 가능한 보고서에 출력한다. 전체 script는 RUNNER_TEMP의 mode-0600 파일로만 보관한다.
2. **prepare**: 저장소 요청 JSON을 읽고 원본 artifact를 먼저 복원한다.
   source 전체/public hash, source revision, artifact run ID, terminal token/reason/cost,
   모든 성공 PNG의 영수증 hash와 실제 PNG 바이트를 대조한다.
   검토 장면 파일의 hash를 확인하고 기존 prepare/validate_candidate를 실행한다.
   후보에는 require_manual_resume=true를 넣는다. 원본을 바꾸지 않고 request/candidate SHA256을 출력한다.
3. **execute**: 검토한 요청 SHA256과 후보 SHA256, RECOVER_REVIEWED_IMAGES 확인 문구가 모두 필요하다.
   원본을 다시 읽고 prepare 전체를 다시 수행한다. 후보 해시까지 일치한 경우에만 기존
   image_generation_register_recovery_v3 RPC를 호출한다.
4. **등록 트랜잭션**: 기존 DB RPC가 source compare-and-set, 후보 대본과 terminal recovery receipt를
   원자적으로 반영한다. source drift나 잘못된 영수증은 롤백된다.
5. **이미지**: 등록 성공 뒤에만 stage=image 사전 점검을 실행하고 allowed=true를 확인한다.
   이후 같은 날짜/새 revision으로 stage=image만 실행한다. all/recovery는 호출하지 않는다.
6. **수동 조립**: 생성 성공 시 image_generated가 되지만 기존 예약 Resume은
   require_manual_resume 표식 때문에 이 회차를 건너뛴다. 시각 검수 후 명시적 수동 Resume만 진행한다.

등록 뒤 이미지 호출이 실패해도 등록을 임의 취소하거나 비용·호출 이력을 삭제하지 않는다.
공통 execute를 무조건 재실행하지 않는다. 이미 등록된 회차는 이 경로에서 차단하고,
기존 run-market 이미지 재개/정산 절차로 실제 ledger와 artifact를 먼저 확인한다.\n실패 보고서는 등록 응답이 불명확하면 registered=unconfirmed/phase=registration,\n등록 확정 뒤 이미지에서 멈추면 registered=true/phase=image를 유지한다.\n등록 이후에는 같은 revision과 실제 partial artifact를 확인하여 stage=image로 재개하거나,\n새 콘텐츠 거절이 있으면 해당 ledger를 검토하는 수동 복구 절차를 따른다. 무조건 execute를 다시 누르지 않는다.

## 4. 요청 계약

version은 reviewed-image-recovery-2다. inspect가 다음 값들을 실제 Python 응답에서 채운다.

- episode_date / episode_id / episode_no=1
- source_revision, 다음 revision 제안값인 target_revision
- source_artifact_run_id
- source_script_sha256 / public_script_sha256
- terminal_token / terminal_reason / terminal_cost_usd
- success_hashes: 성공한 모든 패널의 원본 PNG SHA256

운영자가 채우는 값은 scenes_path, scenes_sha256, actor, note다.
target_revision은 실제 실행 전에 사용하지 않은 값으로 명시적으로 검토한다.
inspect의 source+1 출력은 제안이며 자동 실행이나 예산 초기화가 아니다.

요청 JSON은 .github/icg-image-recovery/ 또는 config/image-recovery/requests/ 아래에만 둔다.
장면 JSON은 기존 docs/incidents/ 또는 config/image-recovery/scenes/ 아래에 둔다.
경로의 절대 경로, 상위 이동, 저장소 밖 symlink, 출력 개행 삽입을 차단한다.
SHA256은 소문자 64자리로 검증한다. 캐스트와 실제 REF 바이트 검증은 기존 준비 도구를 재사용한다.

## 5. 운영 입력 가이드

배포 후 GitHub Actions에서 **Reviewed Image Recovery** 워크플로를 main 기준으로 실행한다.

| 단계 | 필수 입력 | 결과 |
|---|---|---|
| inspect | mode=inspect, target_date | 검토 요청 템플릿, 원본 전체/public hash |
| prepare | mode=prepare, request_path | request_sha256, candidate_sha256, PNG 검증 수량 |
| execute | mode=execute, request_path, request_sha256, candidate_sha256, confirm=RECOVER_REVIEWED_IMAGES | CAS 등록 후 이미지 생성 |

inspect 보고서의 request_template를 요청 JSON으로 저장하고 검토 장면의 경로·해시와 검토자·근거를 채운다.
SHA를 복사할 때 script 본문을 다른 런타임에서 파싱·재직렬화하여 재계산하지 않는다.
prepare가 출력한 두 SHA를 그대로 execute 입력에 사용한다.

새 코드 배포나 장면/요청 변경이 있으면 prepare를 다시 수행한다.
prepare/execute는 요청 파일의 날짜를 사용하므로 target_date는 공란으로 둔다.
기본 입력만으로 execute가 발생하지 않으며 push와 schedule 트리거는 없다.

## 6. 실패 처리와 보존

| 조건 | 처리 |
|---|---|
| 잘못된 날짜·경로·request hash | 다운로드/등록 전 차단 |
| 원본·revision·terminal token/cost·성공 receipt 변경 | CAS 이전 차단 |
| 원본 PNG 누락·hash 불일치·PNG 형식 손상 | 등록 전 차단 |
| reserved/unknown·누락/비정상 비용·복수 terminal | 공통 자동 복구 제외 |
| 기존 recovery receipt 존재 | 중복 등록 차단 |
| 후보 hash 변경 | 등록 전 차단 |
| CAS 실패 | provider 호출 없음 |
| image preflight allowed=false | provider 호출 없음 |
| provider 불명확 응답·유료 생성 실패 | 기존 guard로 보류, 원본·부분 성공 PNG·ledger 보존 |

RUNNER_TEMP의 source.json/candidate.json과 private provider diagnostics는 업로드하지 않는다.
허용 업로드는 output/image-recovery-report.json과 output/episodes/뿐이다.
보고서는 원본 대본·프롬프트·응답 원문·헤더·키를 포함하지 않는다.
실패 오류는 허용된 코드 또는 예외 타입만 공개한다.

## 7. 동시성·예산·운영 모니터링

공통 복구 워크플로는 icg-image-recovery 그룹으로 서로 직렬화한다.
기존 Run Market의 icg-today/날짜 그룹과 동일한 전역 배타성을 주장하지 않는다.
최종 중복 방어는 기존 DB CAS 및 advisory lock, immutable receipt, lifetime/day/month 예산이다.
기존 terminal/unknown 기록 삭제나 revision 증가를 통한 예산 우회는 없다.

generation_guard_beta 등 DB 쓰기 테스트와 실제 운영 복구는 서로 다른 책임이다.
DB 쓰기 beta를 read-only inspect에 섞지 않는다. 테스트 reserved/unknown 기록을 이 모듈이 삭제하지 않는다.
자세한 분류와 삭제 조건은 cleanup inventory를 따른다.

운영 모니터링은 recovery report → DB revision/상태/미정산 → artifact_run_id → 수동 조립 표식을 확인한다.
오프라인 검증은 provider 수락, 실제 청구서, 운영 전달·시각 품질을 증명하지 않는다.

## 8. 현재 지원 범위와 확장 지점

- 기존 v3 등록 계약에 맞춰 episode_no=1, 단일 settled content terminal, 새 revision만 지원한다.
- 복수 terminal과 이미 등록된 회차의 재개는 단일 원자 등록으로 처리된다고 주장하지 않는다.
- _scene_performance_v2가 있는 회차는 기존 v1 prepare와 aspect 계약이 다르므로 전용 준비 경로를 요구한다.
- 콘텐츠 거절 사유가 상세히 없으면 특정 단어나 무기를 원인이라고 단정하지 않는다.
- 모든 장면을 정지 자세로 치환하는 템플릿을 공통 모듈에 넣지 않는다. 장면 수정 품질은 별도 검토와
  source-bound retry-plan 모듈이 담당하며, 이 서비스는 source/receipt/후보 승인·실행을 담당한다.
- 새 retry-plan-2는 별도 PR에서 개발 중이다. 공통 API의 prepare/register 단계 사이에 검토 계획을
  연결할 수 있지만, 이 변경은 해당 정책을 강제로 켜거나 새 DB 계약을 적용하지 않는다.

## 9. 검증과 단계별 이관

회귀는 다른 날짜 fixture, float/int 해시 차이, source 무변경, 모든 REF, 원본 PNG 무결성,
원본/ledger drift, 경로 및 출력 주입, 명시적 execute, CAS 실패, private 권한, provider 전 사전 점검을 확인한다.
로컬 실행 환경을 사용할 수 없어 실제 실행 증거는 PR CI의 최종 SHA 결과로 남긴다.

첫 배포에서는 새 모듈만 추가한다. 현재 일회성 YAML/helper/request는 그대로 두고 공통 inspect/prepare를
운영에서 확인한다. 이후 공통 회귀로 이전이 확인된 파일만 cleanup inventory에 따라 별도 삭제 PR로 처리한다.
사건 근거·SQL 이력·REF 및 회귀 fixture를 일괄 삭제하지 않는다.


## 등록 전 남은 예산 검사

후보의 `_reviewed_image_inputs.panels`별 idx/fingerprint를 현재 scope 이력과 비교한다.
같은 패널의 성공 fingerprint가 후보와 같고 원본 PNG 검증을 통과한 경우만 재사용으로 센다.
새 생성이 필요한 패널의 lifetime 호출 이력이 이미 3회이면
`RECOVERY_PANEL_BUDGET_EXHAUSTED`로 prepare/execute를 등록 전에 차단한다.
기존 scope 호출 수 + 필요한 새 이미지 수가 30을 넘거나,
기존 확정 비용 + 새 이미지마다 보수적 $0.10의 합계가 $3.00을 넘는 경우도 차단한다.
비용 합산은 Decimal로 경계값을 계산한다. 이 검사는 ledger를 초기화하거나 비용 한도를
늘리지 않는다. day/month 전역 예산과 검사 이후 동시 변경은 기존 DB reservation이 최종 판단한다.
inspect는 후보 생성 전의 요청 템플릿만 제공하므로 실행 가능 판정이 아니다.
