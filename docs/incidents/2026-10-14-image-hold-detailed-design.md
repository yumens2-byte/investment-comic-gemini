# ICG Run Market 이미지 보류·운영 모니터링 상세설계

- 작성일: 2026-10-14 KST
- 대상: yumens2-byte/investment-comic-gemini
- 분석 기준: 2c18fcf4e1cd53bb48734a9af1abab5f06deddb9
- 변경 브랜치: fix/image-hold-monitoring-20261014
- 상태: 개발·오프라인 회귀 검증. 운영반영 및 실패 회차 유료 복구 미수행.

## 1. 확인된 장애와 범위

Run Market 38470953872 / job 115549589297은 2026-10-14 06:32:43 KST에 Gemini가 P5를 FinishReason.PROHIBITED_CONTENT로 거절하면서 STEP 6에서 중단됐다. 대본과 프롬프트는 8개였지만 유료 이미지 대상은 P1~P6의 6개다. P7 TEXT_CARD와 P8 DISCLAIMER는 조립 전용 카드다. 아티팩트 11851324896에서 P1~P4 PNG와 대본, 호출 로그, generation-summary.json을 확인했다. P5는 거절, P6은 미시도다.

확인된 공급자 사용량 기반 호출 비용은 성공 4개 합계 $0.1570308, P5 거절 $0.000564, 총 $0.1575948이다. 기존 summary의 cost_usd는 성공 패널 비용만 담아 거절 비용이 합계에서 빠져 있었다. 사용량 기반 관측 비용과 원장 정산 완료 여부를 구분해야 한다.

Resume 38485709335 / job 115598714091은 08:41:45 KST에 image_generated 대상 없음으로 실패했다. 다운로드 대상 선택은 assembled/narrative_done까지 조회하지만 실제 조립 자동 선택은 image_generated만 허용하여 기준이 달랐다.

이번 대본에는 _reviewed_image_retry_plans가 없었다. 현재 코드는 콘텐츠 거절에 대해 검토된 계획이 있어야 대체 입력을 사용한다. 재시도 flag나 횟수 2 설정만으로 콘텐츠 거절을 재시도하지 않는다. 정확히 어떤 입력 요소가 P5 거절을 일으켰는지는 이번 공개 로그·아티팩트만으로 확정할 수 없다.

## 2. 요구사항과 처리 계약

| ID | 요구사항 | 구현·검증 기준 |
|---|---|---|
| R01 | 대본 완료와 이미지 완료 구분 | 대본 준비 로그에 이미지 생성 전 명시; 이미지 분모에서 카드 제외 |
| R02 | 부분 성공 보존 및 정확한 진행률 | 완료/보류/미시도 집계; 성공 PNG 삭제·재생성 금지 |
| R03 | 거절 원인과 재시도 조건 가시화 | provider_reason과 reviewed_retry_panels 기록; flag는 검토 승인이 아님 |
| R04 | 잘못된 후속 계획으로 불필요한 선행 비용 방지 | 제공된 모든 패널 계획의 prompt/REF/hash 검증을 첫 유료 호출 전에 수행 |
| R05 | 콘텐츠 차단과 비용 불명확 시 안전 중단 | 기존 terminal/HOLD·최대 3회 원장 계약 유지; 차단 설정 완화 없음 |
| R06 | 실패 실행의 복구 아티팩트 추적 | 현재 실행에서 성공 이미지가 확인된 HOLD만 artifact_run_id 보존; 완료 상태 변경 없음 |
| R07 | Resume 다운로드·조립 대상 일치 | 준비 단계에서 정확한 episode ID와 artifact run ID를 확정하고 양 단계에 전달 |
| R08 | 예약 무대상과 실제 장애 구분 | 예약 무대상은 IDLE 성공; 수동 무대상, DB 장애, 잘못된 응답·ID, 아티팩트 누락은 오류 |
| R09 | 알림에 정확한 현재 실행 정보만 출력 | run_id/run_attempt 일치 summary만 읽기; 전체 프롬프트·REF bytes 미노출 |

공급자의 PROHIBITED_CONTENT 자체를 사전 검사로 완전히 없애는 것은 보장할 수 없다. 이번 변경은 완료 오인, 대상 불일치, 예약 무대상 중복 실패, 복구 파일 추적 누락, 잘못된 재시도 계획으로 발생하는 불필요한 호출을 방지한다. 실제 콘텐츠 거절은 검토된 입력과 기존 복구 계약을 통해 처리한다.

## 3. Run Market 상세 흐름

1. STEP 4: 대본 패널 N개 준비, 이미지 생성 전이라는 로그를 출력한다.
2. STEP 6: 대본 N개/생성 이미지 M개/조립 전용 카드 N-M개를 표시한다.
3. generate_episode: 활성 재시도 횟수를 검증하고, 제공된 모든 재시도 계획의 version, hash, original prompt, REF SHA-256을 검증한다. 잘못된 계획이면 첫 유료 호출 전에 중단한다. DB 계획·cursor 권한 검증은 기존 ProductionGenerationGuard가 계속 담당한다.
4. 첫 호출 전 summary를 생성한다. 아직 시도하지 않은 이미지는 not_attempted다.
5. 성공 패널: 기존 PNG 검증·배타적 저장·원장 정산 계약을 유지한다. 파일은 보존한다.
6. 보류 패널: held로 기록하고 나머지는 not_attempted로 남긴다. 기존 예외 원인에 NoImageResponse가 있으면 정규화된 provider_reason을 기록한다. 무조건 다음 패널을 호출하지 않는다.
7. 현재 실행에서 성공 이미지가 존재하는 GenerationHold에 한해 기존 artifact_run_id 컬럼에 현재 run ID를 보존한다. 이전 실행 summary, 선행 입력 검사 실패, 성공 0개이면 기존 포인터를 덮어쓰지 않는다. 저장 오류가 발생해도 최초 HOLD를 다른 예외로 바꾸지 않는다.
8. 모든 유료 이미지가 완료된 경우에만 기존 image_generated 상태를 기록한다. 누락 상태로 조립·발행하지 않는다.

### Summary 계약

기존 panels/complete/cost_usd/held_panel/cost_complete를 유지하고 아래 필드를 추가한다.

| 필드 | 의미 |
|---|---|
| run_id, run_attempt | 현재 Actions 실행과 시도 식별 |
| expected_images | 유료 생성 대상 이미지 수 |
| successful_images | 현재 확보된 성공 이미지 수; 원장 검증 후 재사용도 포함 |
| not_attempted_images | 보류 이후 아직 호출하지 않은 수 |
| reviewed_retry_panels | 활성 flag 하에서 제공된 패널별 검토 계획 수 |
| content_retry_policy | reviewed_plan_required |
| provider_reason | NoImageResponse에서 추출한 공급자 원인; 알 수 없으면 null |
| observed_provider_cost_usd | 현재 run_id/run_attempt 호출 로그의 알려진 사용량 비용 합계 |

observed_provider_cost_usd는 공급자 관측치 합계다. 이전 실행 재사용 비용을 다시 청구 비용으로 합산하지 않는다. 알 수 없는 비용이 섞일 수 있으므로 이 값으로 HOLD를 해제하거나 원장 정산 완료를 판단하지 않는다. cost_complete=false는 그대로 유지한다.

## 4. Resume 상세 흐름

- 준비 CLI: python -m scripts.run_resume --prepare-only [--episode ID] [--scheduled]
- 자동 조회는 기본 image_generated만 허용한다. 명시적으로 허용한 narrative-only 옵션과 기존 force 상태 검증은 유지한다.
- 준비 결과: ready=true/false, episode_id, run_id. 허용 상태와 정확한 행, 숫자형 artifact run ID, 날짜·에피소드 번호를 검증한다.
- 예약 대상 없음: status=idle, ready=false. 다운로드·조립·슬라이드 업로드·QC 알림을 건너뛴다. 실제 실패 알림은 발생하지 않는다.
- 준비 조회 실패: 예외를 전달해 작업을 실패시킨다. 대상 없음으로 위장하지 않는다.
- 다운로드: episode-{확정 run_id} 아티팩트만 받는다. 이전처럼 episode-* 전체 패턴을 사용하지 않는다.
- 조립: 확정 episode_id를 환경변수로 전달하고 shell 배열로 인자를 구성한다. 인라인 shell에 수동 입력 문자열을 직접 삽입하지 않는다.
- 조립 직전 기존 상태 검증과 필수 PNG 검사를 다시 실행한다. 선택 이후 상태가 바뀌어도 무조건 조립하지 않는다.

## 5. 기존 복구·재시도 절차

이번 변경은 검토된 대체 프롬프트를 자동 생성·승인하거나 기존 terminal 원장을 자동 초기화하지 않는다. 콘텐츠 차단을 우회하는 프롬프트 치환·공급자 안전 설정 변경도 하지 않는다.

실패 회차 복구는 기존 docs/run-market-image-recovery.md 및 docs/webtoon-quality/image-resume-operations-20261008.md 계약을 따른다.

1. 원래 실패 실행의 아티팩트, 성공 PNG SHA-256, 영속 입력 fingerprint, 비공개 입력 진단, 공급자 거절 상세와 원장 비용을 확인한다.
2. P5의 실제 최종 입력과 캐릭터 REF를 검토한다. 대본 단독으로 정확한 거절 요소를 단정하지 않는다.
3. 적합한 장면과 검토된 대체 입력을 확정한다. 기존 검토 계획과 recovery receipt, persisted script 일치 계약에 맞춰 등록한다.
4. 원본 P1~P4를 복원하고 해시·입력 동일성을 확인한다. 무조건 all/force로 다시 생성하지 않는다.
5. 기존 recovery 모드에서 새 revision과 원본 source_artifact_run_id를 사용하고, 비용·총 호출 한도 검사 후 필요한 이미지에 대해서만 복구한다.
6. 실제 유료 파일럿과 image_generated 상태 확인 후 Dialog/Resume를 진행한다. 부분 성공을 완료로 바꾸지 않는다.

이번 작업에서 운영 DB/검토 계획/receipt 변경, 실제 Gemini 호출, SNS 발행은 수행하지 않았다. 오늘 실패 회차의 복구가 완료됐다는 뜻도 아니다.

## 6. 알림 예시

아래는 이번 4/6 중단 조건을 새 집계에 적용한 예시이며 실제 전송하지 않았다.

> Gemini 이미지 거절: P5: FinishReason.PROHIBITED_CONTENT
>
> 이미지 생성 진행률: 이미지 4/6개 완료 · 미시도 1개
>
> 완료된 PNG는 보존했습니다. 동일 입력 반복 실행 대신 거절 상세와 검토된 복구 계획을 확인하세요.

## 7. 변경 파일 및 검증

| 파일 | 변경 |
|---|---|
| engine/image/gemini_client.py | 계획 일괄 선행 검증, 실행·시도별 호출 로그, 부분 성공·관측 비용 summary |
| scripts/run_market.py | 단계별 개수 표시, 성공 파일이 있는 HOLD의 아티팩트 포인터 보존 |
| scripts/run_resume.py | 정확한 대상 확정, IDLE/DB 장애 구분, CLI 준비 모드 |
| .github/workflows/resume_episode.yml | 동일 대상 다운로드·조립, 명시 아티팩트 이름, 무대상 skip, shell 입력 안전 전달 |
| scripts/notify_failure.py | 현재 실행·시도의 이미지 진행률 알림 |
| tests/test_image_hold_monitoring.py | P5 보류·비용·PNG 보존, 잘못된 계획, 조회 장애, 입력 ID, 이전 포인터 보존 회귀 |
| 이 문서 | 상세설계·운영 적용 범위와 제한 |

- Python 3.11.17 전체 회귀: **1,716 passed / 42.79초**.
- 신규 장애 회귀: 26개. 초기 관련 회귀 111개 통과 후 조회 형식·이전 아티팩트 보존 검사를 추가하고 전체 재검증했다.
- Ruff: 변경 이미지 클라이언트·Resume·알림·신규 테스트 통과. run_market.py F 규칙 검사 통과.
- Git diff --check 통과.
- Resume workflow YAML 파싱 및 모든 run 블록의 bash -n 통과.
- 모든 테스트의 provider/DB 어댑터는 mock을 사용한다. 유료 공급자·운영 DB 검증을 대신하지 않는다.
- GitHub PR CI는 PR 생성 이후 별도로 확인해야 한다.

## 8. 운영반영 기준

PR CI, 특히 운영과 같은 Python 3.11 회귀와 workflow 검증 통과 후 main 반영한다. 스키마 변경과 신규 secret은 없다. 예약 Resume 무대상에서 다운로드·조립이 skip되는지, DB 장애는 실패로 남는지 확인한다. 다음 실제 이미지 실행에서는 대본·이미지 분모와 진행률을 확인한다. 공급자 거절이 발생하면 성공 PNG가 유지되는지와 복구 artifact_run_id 저장을 확인한다.

코드 배포와 2026-10-14 회차의 유료 복구는 별개다. 현재 산출물은 PR 검토 대상이며 운영반영은 수행하지 않았다.
