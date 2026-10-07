# 2026-10-08 이미지 생성 운영 복구

대상: `ICG-2026-10-08-001`, 중단 실행 `37690049331`.

## 적용 및 복구 준비

- 운영 DB에 `docs/sql/image-generation-retry.sql` 적용.
- 기존 대본을 서버 전용 diagnostics 테이블에 백업하고, revision 2 복구 대본과 6개 유료 패널의 검토된 입력·재시도 계획을 등록.
- 당시 Notion 내용으로 P1~P4 입력을 재구성하여 운영 원장 지문과 일치 확인. 원본 artifact의 P1~P3 PNG SHA256도 운영 원장과 일치 확인.
- P1~P3는 당시 프롬프트와 원본 PNG를 유지. 이 패널들은 새 유료 호출 없이 재사용. P2/P3 대본 action 표현은 관찰 모드에 맞게 정리했으며, 이미 생성된 이미지와 공급자 입력 기록은 유지.
- P4는 데이터 화면을 조용히 관찰하는 비전투 장면으로 수정. 기존 거절 호출의 비용 USD 0.000561을 그대로 유지하고 revision 2 복구 receipt 등록.
- P4는 기존 1회 호출을 포함해 총 3회 제한이므로 **추가 호출 최대 2회**. P5/P6는 첫 호출 + 재시도 2회, 각각 총 3회 제한.
- P7/P8은 TEXT_CARD/DISCLAIMER로 공급자 이미지 호출 대상에서 제외.

## 실행 방법

GitHub Actions → **📊 Run Market** → **Run workflow**에서 다음 값을 사용한다.

| 입력 | 값 |
|---|---|
| Branch | `main` |
| image_retry_v2 | `true` |
| generation_revision | `2` |
| source_artifact_run_id | `37690049331` |
| dry_run | `false` |
| target_date | `2026-10-08` |
| stage | `image` |
| force | `false` |
| 나머지 feature flags | 기존 `auto` 기본값 |

`stage=image`은 현재 DB에 등록된 복구 대본을 읽는다. `stage=recovery`는 대본을 다시 만들므로 이 회차의 준비된 복구 입력에 사용하지 않는다. 기존 실패 실행의 **Re-run jobs**는 당시 커밋과 입력으로 실행되므로 사용하지 않는다.

## 로그에서 확인할 것

1. preflight가 통과하고 revision 2 대본을 복원한다.
2. 원본 artifact에서 P1~P3 PNG를 복원한다. 파일이 없거나 해시가 다르면 유료 재생성 대신 중단한다.
3. Gemini 호출은 미완료 P4~P6에만 발생한다. 알려진 비용으로 정산된 콘텐츠 거절만 검토된 다음 프롬프트로 진행한다.
4. 생성 완료 상태와 `generation-summary.json`을 확인한다. 전체 실행 성공 전까지 완성된 회차로 간주하지 않는다.

타임아웃·비용 불명·진단 저장 실패·정산 실패는 자동 재시도하지 않는다. 해당 원장을 먼저 확인한다. 재실행해도 DB에 기록된 호출 횟수는 초기화되지 않는다.

원본 artifact 보존 기간은 14일이다. 만료 전에 위 실행으로 P1~P3를 복원해야 한다. 성공 후 이미지 검수·조립·게시 절차는 별도로 진행한다. 이 배포 및 복구 준비에서는 Gemini 유료 호출을 실행하지 않았다.

## 롤백

새 요청의 `image_retry_v2=false`로 재시도 기능을 비활성화한다. 원장·receipt·진단 기록은 삭제하지 않는다. 준비된 revision 2 대본에 revision 1 실행을 지정하지 않는다. 대본을 되돌리려면 서버 전용 diagnostics의 `kind=operator_recovery_backup` payload에 저장된 원본을 검토하고 별도 복구 revision을 준비한다.
