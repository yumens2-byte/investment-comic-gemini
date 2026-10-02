# CONTENT_QC_HOLD 경고 전환 — 요구사항·설계·검증

## 목적과 범위

CONTENT_QC_HOLD는 미개발 기능이 아니라 기존 조립·발행 차단 기능이다. 사용자 요청에 따라 이 콘텐츠 QC 경로를 경고로 전환한다. 장기 비전투 반복 개선(PR #96)과 별도 변경이다.

- 기존 CONTENT_QC_HOLD, 누락/실패/오래된 복구 검수, 패널 검수 해시 불일치가 작업을 중단하지 않는다.
- 원래 검수 메타데이터와 DB의 HOLD 값을 PASS로 조작하거나 삭제하지 않는다.
- 로그 및 output/content-qc-warnings.jsonl에 CONTENT_QC_WARNING을 기록한다.
- Resume 조립, 발행 사전점검, 발행 claim 경로가 같은 콘텐츠 QC 정책을 사용한다.
- Telegram 경고 알림을 Run Market/Resume/Publish 워크플로에 추가한다. 항상 실행하는 알림 단계가 경고 파일이 있을 때만 전송한다. DRY_RUN에서는 전송하지 않는다.
- 기존 실패 알림 단계는 그대로 유지한다. 알림 실패·증거파일 기록 실패가 추가로 파이프라인을 중단하지 않는다.
- PUBLISH_HOLD 중복 발행 잠금, CAS fencing, 발행 채널 설정, 원본 파일 누락 및 조립 실패, 실제 전송 실패 등 처리 계약은 유지한다.
- 다른 별도 품질 트랙/시장 데이터/서사 strict 검증은 이번 CONTENT_QC_HOLD 변경 범위에 포함하지 않는다.

## 구현

1. 기존 콘텐츠 검증을 _check_content_ready 및 _check_reviewed_sources 내부 함수로 유지한다.
2. 공개 require 함수는 QualityHold를 잡아 경고를 기록하고 경고 목록을 반환한다. 잘못된 narrative 자료형은 처리 오류로 남긴다.
3. publish_preflight는 content_qc_warnings를 별도 반환하며 content_qc_hold를 block_reasons에 넣지 않는다.
4. notify_failure --qc-warnings는 QC 경고를 모아 한 번 알림한다. 경고가 없으면 종료하고, 기존 인자 없는 실패 알림은 유지한다. 중복 메시지를 제거하며 HTML 이스케이프와 메시지 길이 제한을 적용한다.
5. 운영 DB 쓰기, HOLD 해제, Telegram 실제 전송, 유료 생성은 개발 테스트에서 수행하지 않는다.

## 검증 결과

- 전체 회귀: 1,473 passed in 42.27s.
- Ruff 및 diff 검사 통과.
- 기존 콘텐츠 경고가 publication claim 획득 및 Resume 조립 진입을 허용하는 것을 mocked adapter로 확인했다.
- 원래 HOLD 메타데이터 유지, 검수 해시 변경 경고, 발행 CAS 잠금 유지, 파일 오류 차단, 알림 없음/경고/기존 실패 모드를 검증했다.
- GitHub 운영 CI·실제 Telegram 경고 도착·조립 및 실발행 결과는 별도 운영 검증이다.

## 변경 파일

- 운영 6본: content_qc.py, publish_preflight.py, notify_failure.py, run_market.yml, resume_episode.yml, publish_sns.yml.
- 테스트 3본: test_content_recovery_qc.py, test_publish_dry_preflight.py, test_content_qc_warning_notifications.py.
- 문서 1본: 본 문서. 총 10본.
