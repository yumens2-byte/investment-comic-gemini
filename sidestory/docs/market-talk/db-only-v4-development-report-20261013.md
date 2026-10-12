# ICG Market Talk v4 개발·검증 보고서
작성: 2026-10-13 KST
기준 main: 33f22a51c35a10ed53a6872270e20c99a35a8b53
개발 브랜치: feat/market-talk-db-random-20261012
상태: 개발·로컬 검증 완료, 원격 CI 확인 및 운영 적용은 별도.

## 구현 결과
- 발행 전 Facebook 전체 게시 목록 조회·관측 호출을 Market Talk 정상 경로에서 제거.
- TalkStoreV4와 TalkPublisher로 Market Talk 정책·원장 제어를 분리. 기존 Sidestory v3 제어/RPC 보존.
- KST 평일 13:00~17:30 중 분 단위 난수 1개를 DB에 확정. 재실행·동시 후보는 최초 저장 시간을 재사용.
- 10분 poll은 목표 전에는 모델/POST를 호출하지 않음. 목표 이후 현재 유효 DB 자료로 생성·검수·발행.
- 당일18:00부터 신규 모델 비용 예약·발행 예약 차단. 예약을 통과한 외부 호출 완료 시각은 다를 수 있음.
- KST 하루1건·월요일 기준 주5건, talk track 원장만 집계. 다른 게시물의 횟수·간격 제한 없음.
- Page 식별 GET 및 이번 게시물 post_id GET 검증 유지.
- Talk의 UNKNOWN/REJECTED는 talk_policy만 정지. 미확정 결과 자동 재POST 금지.
- 신규 SQL은 Supabase CLI가 생성한 20261012104810_market_talk_db_only_v4.sql. 정책 disabled 및 다음 KST날짜 effective_from 기본값.

## 검증 결과
- 외전 전체 Python: 439 passed, skipped 없음. Market Talk152개 포함.
- PostgreSQL(PGlite) 계약: 기존48 + Sidestory 진단8 + v4 신규33 =89개 통과.
- Ruff 검사, git diff --check, actionlint1.7.12(변경한 Market Talk workflow 전체), workflow 내 Python compile 통과.
- 실제 독립 연결 PostgreSQL 테스트3건 작성 및 CI 별도 talk-v4-concurrency job 연결. 로컬 사용자/그룹 전환 권한 제한으로 실행하지 못했으므로 PGlite 결과를 독립 연결 잠금 증명으로 표시하지 않음.
- 본편 전체 첫 실행:1688passed/3failed. 세 실패 모두 로컬 SOCKS 프록시용 socksio 누락. 로컬 환경 보완 후 tests+sidestory/tests 통합 재실행 결과는 아래 최종 검증 추가 기록 참고.
- 폰트가 없던 초기 외전 실패는 NotoSansCJK 설치 후 재검증. 소스/검증 조건을 완화하지 않음.

## 코드 리뷰 및 보완
독립 리뷰에서 발견한3건 모두 수정·재검증했다.
1. 실제 DB policy_version 정수4를 문자열로 비교하던 일정 검증: 정수값 처리 및 malformed 시각 테스트 추가.
2. 신규 DB 상태코드6종 소실: 원래 안전 코드 보존 및 CLI 실패/정상skip 구분.
3. 토큰 계산 호출이 늦어질 때 마감 이후 비용 예약 가능: talk_cost_reserve_v4에서 DB시각·정책·한도 최종검사.

## 테스트 시나리오
feed 조회가 항상 실패하는 fake에서도 talk POST/개별검증 성공; 재실행 POST1회 유지.
100개 external 이력 및 sidestory UNKNOWN은 talk 허용에 영향 없음.
정확한 revision/claim token/CAS, day/week cap 및 월요일 경계, 비용 키 중복, disabled·18시 cutoff·주말·date mismatch 검사.
저장 슬롯 난수 endpoint13:00/17:30, 재실행 목표 유지, 시간대/초/마이크로초/마감 불일치 거부.
watcher는18시 이후 당일 슬롯의 NO_RUN/미발행/미검증/미확정을 검사.

## 운영 전 남은 작업
원격 CI의 실제 PostgreSQL 동시성 검증, main 병합, 운영 additive migration, talk_policy 활성화·적용일 확인,
기존 모델/단가/예산/허용 캐릭터 및 스케줄/live/watch 변수 확인, 실 계정1건 베타와 DB/게시물 대조.
현재 운영DB/변수/실제Facebook 게시는 변경하지 않았다. 기존 당일18:30슬롯/원고를 강제로 변경하거나 감사 원장을 삭제하지 않는다.
운영 절차는 db-only-v4-operations.md, 상세설계는 db-only-random-schedule-20261012.md 참고.


## 최종 통합 재검증

로컬 SOCKS 의존성 보완 후 tests/ 및 sidestory/tests/ 통합 실행: **2130 passed, 90 warnings, 0 failed, 0 skipped** (Python3.12). 경고는 기존 PostgREST SDK timeout/verify deprecation이며 운영 오류가 아니다. GitHub Python3.11 CI는 별도 확인한다.
