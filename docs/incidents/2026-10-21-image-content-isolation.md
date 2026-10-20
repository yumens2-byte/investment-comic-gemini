# 2026-10-21 이미지 콘텐츠 거절 — 분석·설계 및 운영 전 검증

## 확인된 장애와 원인

- 원본 실행: https://github.com/yumens2-byte/investment-comic-gemini/actions/runs/39489073022
- 기준 SHA: e6b00b8e37eb17eb2177def5f1a39c962d08c2e2
- 에피소드: ICG-2026-10-21-001, revision 1.
- 운영 DB 읽기 확인: P1/P2/P3 success, P4 terminal / CONTENT_REVIEW_REQUIRED / PROHIBITED_CONTENT.
- P4 정산 cost: 0.0007916999999999999 USD, 입력 토큰 2639, 출력 토큰 0.
- P4는 HTTP 200 응답이지만 이미지 없는 콘텐츠 거절이었다. HTTP 성공은 이미지 생성 성공을 뜻하지 않는다.
- 제공자 응답에 세부 finish message와 safety category가 없어, 특정 단어·캐릭터·무기가 거절 원인이라고 단정할 수 없다.
- 원본 입력은 두 캐릭터의 에너지 압박·방패 균열을 묘사하며 일반 combat staging을 포함했다. 정확한 입력과 REF 해시는 비공개 DB 진단에 보존되어 있다.
- 기존 정책: 일반 콘텐츠 거절 -> 즉시 GenerationHold. Python뿐 아니라 v1/v2 DB inspect도 같은 scope의 terminal 하나가 전체를 막는다.
- 운영 episode status는 narrative_done, artifact_run_id는 39489073022. 성공 PNG를 담은 episode artifact가 존재한다. 누락 상태의 image_generated 승격·발행은 없다.

## 업무분장과 변경 설계

주 담당은 원본 로그·DB 확인, Python 예외/요약, 후보 장면과 CI 통합을 맡았다.
독립 담당은 DB 예약 계약·SQL 테스트, 또 다른 담당은 파이프라인·운영 상태·변경 코드 리뷰를 맡았다.

- 새 기능은 ICG_IMAGE_CONTENT_ISOLATION_V4_ENABLED로 명시적으로 활성화한다. 기본 false.
- outcome-v3 정산과 v4 DB capability가 확인되어야 한다. capability 부재 시 유료 호출 전 차단한다.
- ordinary revision 1만 대상. 검토 재시도와 revision 2 이상은 기존 복구 경로를 사용한다.
- 정산된 콘텐츠 거절, 비용 확인, 입력 및 거절 진단 저장 성공인 경우만 typed SettledContentRefusal을 발생시킨다.
- DB는 다른 패널의 정산·진단이 확인된 콘텐츠 거절만 격리한다. 거절 원본 패널 재호출은 차단한다.
- 기존 전역 advisory lock, 패널·scope·일·월 횟수/비용 한도는 유지한다.
- unknown/reserved, 정산 실패, 진단 실패, 과비용, fingerprint 변경은 전체 중단한다.
- 후속 패널을 모두 처리해도 거절 패널이 남으면 최종 GenerationHold. 부분 이미지를 완성 회차나 발행 가능 상태로 바꾸지 않는다.
- 로컬 요약에는 복수 held_panels를 남긴다. 기존 DB 텔레메트리 허용 필드 계약은 유지한다.
- 더 나중에 발생한 정산 장애를 앞선 콘텐츠 거절 사유로 덮어쓰지 않는다.

## 이번 회차 복구 후보

docs/incidents/2026-10-21-reviewed-scenes.json에 6개 paid scene을 준비했다.
에너지로 인물을 압박하는 장면을 실제 비접촉 관찰·독립된 추상 표시·소품 점검 장면으로 바꾼다.
등장 캐릭터, 고정 소품, 미발견 방패 내부 균열, 무승부·미해결 단서를 유지한다.
기존 한국어 나레이션, 대사, 상태 후보, TEXT_CARD/DISCLAIMER는 준비 도구가 변경하지 않는다.

이 파일은 검토용 장면 입력이다. 운영 DB의 정확한 최신 script_json을 결합한 등록 후보는 아니다.
기존 prepare_image_recovery가 모든 paid panel의 비접촉 계약과 고정 prompt를 검증하므로 6개 전부를 준비했다.
원본 성공 P1~P3 PNG는 보존되지만, 새로운 prompt fingerprint가 다르면 재사용되지 않고 새 이미지 생성 비용이 든다.
P4만 재시도하여 3장 재사용이 보장된다고 주장하지 않는다. 원본 inputs와 동일한 fingerprint인 경우만 기존 DB 가드가 무과금 재사용한다.
제공자의 향후 수락 여부는 오프라인 테스트로 보장할 수 없다. 안전 설정 완화나 거절 입력 위장은 수행하지 않는다.

## 검증

현재 로컬 실행 환경은 No usable execution environment이므로 GitHub draft PR CI에서 실행한다.
신규 Python 회귀: 정산·진단 순서, 비확정 정산 차단, flag off, 복수 거절, 후속 독립 패널 처리, 최종 HOLD, 이후 정산 장애 오분류 방지, capability 누락.
신규 SQL 계약: 콘텐츠 격리/원본 재호출 금지, 기존 RPC 차단 유지, unknown·reserved·legacy·과비용·진단 누락 차단, PNG hash 재사용, revision/예산/권한.
복구 준비 테스트: 실제 repo canon REF 바이트로 후보 검증, 원본 source 무변경, public narrative/cast/카드 보존, provider/DB 호출 0.

SQL 테스트의 PGlite 병렬 Promise 검증은 단일 PostgreSQL backend다.
다중 세션 lock 경합 및 실제 제공자 응답·청구 검증을 수행했다고 주장하지 않는다.
CI 최종 결과는 PR과 workflow run을 기준으로 확인한다.

## 운영반영 및 복구 순서 (이번 작업에서 미실행)

1. PR의 최종 SHA에 대해 CI 4개 job 모두 성공 확인.
2. 운영 DB prerequisites와 기존 함수 정의를 확인하고 additive v4 SQL을 적용·권한/capability 검증.
3. 코드 배포 후 별도 설정으로 v4 flag 활성화. DB 미적용 상태에서 먼저 켜면 안전하게 중단된다.
4. 이번 실패 회차는 일반 all/recovery 재실행으로 우회하지 않는다. 같은 revision의 P4는 계속 차단된다.
5. 운영 최신 script_json을 비공개 경로로 export하고 위 scenes 파일로 prepare_image_recovery를 실행한다. 사용하지 않은 새 revision을 확인한다.
6. prepare와 validate_candidate 통과 후 생성된 최종 후보와 원본 narrative/cast/REF를 검토한다.
7. 별도 운영 단계에서 정확한 terminal token과 확인된 cost로 register를 수행한다. stale source면 중단한다.
8. stage=image, target_date=2026-10-21, 새 revision, source_artifact_run_id=39489073022로 실행한다. 새로운 유료 생성이며 발행과 별개다.
9. 6/6 생성과 artifact/상태 정합성을 확인한 뒤 대사/조립/발행 게이트를 진행한다.

운영 DB 함수·데이터 변경, recovery 등록, paid image 호출, main 병합, SNS 발행은 이 준비 작업에서 수행하지 않는다.
