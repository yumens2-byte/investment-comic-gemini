# 이미지 방어코딩·추가 재시도 2회 개발 및 단위테스트 결과

작성: 2026-10-08 KST. 기준: 7ae98708e16e124cfa568bdab1ec1e4e0d1c56cd.
대상 장애: Run Market 37690049331, P4 PROHIBITED_CONTENT.

## 구현 결과

- OBSERVATION / NO_BATTLE에서 타격·파괴 동작을 사전에 검출한다. 충돌 장면을 임의 변환하지 않고 대본 검토를 요구한다.
- ICG_IMAGE_RETRY_V2_ENABLED 기본값은 false다. 새 분기는 최초 호출 + 추가 최대 2회이며 ICG_IMAGE_MAX_RETRIES는 0..2만 허용한다.
- 콘텐츠 거절은 동일 입력으로 반복하지 않는다. DB에 등록된 검토 계획, 입력·REF 해시, 현재 persisted script가 일치하는 다른 장면만 사용한다.
- 미확정 비용, timeout, 정산 실패, 권한·예산 오류는 재호출 없이 기존 HOLD를 유지한다. 429도 보수적으로 중단하며 조건부 일시 제한 재시도는 구현하지 않았다.
- SDK HTTP 재시도 attempts=1 유지 및 이미지 AFC 비활성화. 자동 호출은 애플리케이션 정책에서만 수행한다.
- 새 원장 cursor는 실행 재시작 후 이미 거절된 입력을 건너뛰고, 대체 입력으로 성공한 PNG의 입력을 다시 선택한다.
- 총 호출 수는 기존 DB calls를 revision과 무관하게 합산하여 3회로 제한한다. 예약 및 정산은 기존과 동일한 advisory transaction lock을 사용한다.
- 확정된 패널 실패와 전역 HOLD를 구분한다. 확정 패널 실패는 나머지 패널을 진행할 수 있지만 누락 이미지가 있으면 기존 STEP 6 완전성 검사에서 실패하며 image_generated를 기록하지 않는다.
- generation-summary.json에 패널 상태·비용·완료 여부를 저장한다.
- 검토 입력·REF 해시 및 공급자 finish_message/safety_ratings/차단 이유는 ICG_IMAGE_DIAGNOSTICS_DIR의 제한된 로컬 파일에 저장한다. 이 디렉터리는 output 밖에 위치해야 하며 디렉터리 0700/파일 0600이다. 일반 아티팩트로 자동 업로드하지 않는다.

## 변경 파일

| 경로 | 내용 |
|---|---|
| engine/image/action_safety.py | 관찰 장면 충돌 검사 |
| engine/image/gemini_client.py | 거절 응답 분류, 검토 대안 재시도, 패널 실패 집계, 진단 |
| engine/image/generation_guard.py | 검토 계획 RPC, 입력 전환, 영속 cursor 및 횟수 검증 |
| engine/image/retry_policy.py | 신규: 횟수 제한, 계획 hash/REF 검증, 재시도 대기 |
| scripts/market_preflight.py | 검토 계획으로 terminal 복구할 때 읽기 전용 점검 |
| scripts/run_market.py | 관찰 검사와 패널 retry plan 전달 |
| docs/sql/image-generation-retry.sql | 신규: 검토 계획 테이블과 4개 RPC, 미적용 |
| tests/test_image_retry_defense.py | 신규: 28개 테스트 케이스(파라미터화 포함) |
| 이 문서 | 개발·검증 결과 및 운영 전 잔여 작업 |

총 9개 파일: 기존 수정 5개, 신규 4개. source/runtime Python 경로는 총 6개다.

## 검증 증거

- 최종 전체 회귀: 1,609 passed, 64.44초.
- 마지막 cursor/잔여 횟수 보완 후 관련 테스트: 114 passed, 1.03초.
- 새 테스트는 최초 성공, 1차/2차 대안 성공·소진, 동일 거절 입력 재사용 금지, 재시작 cursor, 기존 2회 호출 후 남은 1회만 실행, 타임아웃·정산 실패·미확정 비용 중단, 해시·REF 변경 차단, PNG 재사용, 비공개 증거 권한, 패널 실패 후 진행과 전역 HOLD 중단을 포함한다.
- Ruff: 변경 이미지 모듈·preflight·새 테스트 검사 통과. git diff --check 통과.
- pglast: SQL 19개 statement와 PL/pgSQL 함수 4개 구문 검증 통과. 이는 실제 DB 실행·권한·동시성 검증을 대신하지 않는다.
- 실행 환경: Python 3.12.14. 저장소 운영 workflow는 Python 3.11이므로 실제 CI 환경 검증은 통합 단계에 남아 있다.
- 초기 전체 테스트 3개 실패는 로컬 SOCKS 프록시 지원 패키지 누락으로 발생했다. 테스트 환경에 socksio를 설치한 뒤 전체 통과했다. 해당 환경 보정으로 저장소 dependencies를 변경하지 않았다.
- 실제 Gemini 호출, 운영 DB 쓰기, 운영 배포 및 발행은 수행하지 않았다.

## 검토된 입력 계획 계약

script_json._reviewed_image_retry_plans의 키는 패널 번호 문자열이다. 각 값은 version=image-retry-plan-1, plan_id, prompts(1..3), ref_sha256다. prompts[0]는 해당 패널의 최초 확정 프롬프트와 같아야 한다. plan_id는 version/prompts/ref_sha256 객체를 ensure_ascii=false, sort_keys=true, separators=(',',':')로 직렬화한 SHA-256이다.

DB image_generation_retry_plans에는 같은 plan_id, scope, panel, revision, current script_json 전체 스냅샷, fingerprint 배열, review_evidence를 등록한다. fingerprint는 기존 ProductionGenerationGuard와 동일하게 [prompt+'\n[model=gemini-2.5-flash-image;aspect=None]', REF SHA-256 배열]을 ensure_ascii=false, separators=(',',':')로 직렬화한 SHA-256이다. 계획과 증거는 운영자가 검토한 후 등록하며 공급자 거절 callback에서 자동 승인하지 않는다.

같은 plan_id가 다른 날짜에서 재사용될 수 있도록 DB PK는 (plan_id,scope,panel)이다. 서비스 실행 주체에만 SELECT/INSERT 및 RPC 실행 권한을 부여한다. 계획은 UPDATE/DELETE 권한을 부여하지 않는다. 예산과 횟수는 계획별로 초기화하지 않는다.

기존 terminal 호출은 그대로 보존한다. 새 코드 이전에 발생한 P4 terminal은 기존 recovery receipt로 명시적 정산·검토를 완료해야 한다. 기존 성공 P1~P3 fingerprint를 유지하고 원본 PNG를 복원해야 한다. 새 계획만 등록해서 오래된 terminal을 자동 해제하지 않는다.

## 운영 활성화 전 필수 잔여 작업

1. 격리 DB에 revision/recovery 계약을 준비하고 신규 SQL을 실행하여 권한, 같은 token 정산 재전송, 충돌 정산, 동시 reserve, 총 횟수·기간 비용 한도를 검증한다. SQL은 deployment proposal이며 migration history를 생성하거나 운영 적용하지 않았다.
2. Python 3.11 CI에서 변경 코드와 기존 파이프라인 회귀를 실행한다.
3. 이번 P4의 대본·동작·최종 프롬프트를 검토하여 비전투 장면과 대체 장면을 확정하고 현재 script와 DB 계획/receipt에 등록한다. P1~P6 각각의 입력 해시 및 기존 성공 PNG를 확인한다.
4. 제한된 로컬 진단 파일을 보존할 접근 제한 저장소 및 수집 경로를 연결한다. 현재 구현은 로컬 파일 권한만 보장하며 runner 종료 후 영구 보존은 보장하지 않는다.
5. 예산 예약은 기존 고정 0.10 USD를 유지한다. 공급자의 실제 최대 과금 상한을 확인한 별도 동적 예약은 아직 구현하지 않았다. 실제 출력 상한·모델 과금 정책 검증 후 파일럿을 진행한다.
6. 기능 flag를 OFF로 둔 상태에서 배포·통합 검증한 다음 제한 파일럿으로 활성화를 검증한다. 이후 운영반영 절차를 진행한다.

부분 실패의 별도 DB status, 전용 Telegram 집계 템플릿, 동적 예약액, Retry-After 기반 일시 429 재시도는 이번 핵심 구현에 포함하지 않았다. 기존 narrative_done 상태·실패 알림·발행 완전성 검사를 유지한다. 이 문서의 단위테스트 완료를 운영 복구 완료로 해석하지 않는다.
