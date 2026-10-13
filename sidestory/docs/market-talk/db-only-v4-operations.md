# Market Talk v4 운영·이행 가이드

작성: 2026-10-13 KST. 개발 변경이며 운영 적용 전이다.

## 변경 후 동작

평일 13:00~17:30 KST 중 하루 목표 시각을 한 번 저장한다. 10분마다 실행되는 poll은 목표 전에는 모델을 호출하지 않는다. 목표 이후 첫 실행에서 최신 유효 DB 스냅샷으로 원고를 생성·검수·발행한다. 18:00 이후 신규 생성 비용 예약·발행 예약은 거부한다. 이미 예약한 외부 요청의 완료 시각까지 18시 이전으로 보장하는 것은 아니다.

다른 앱·관리자의 글은 집계하지 않는다. Market Talk DB 원장 기준 KST 하루 1건·월요일 시작 주 5건이며, 연속 24시간 최소 간격 규칙은 없다. 최근 Facebook 게시 목록은 정상 발행 경로에서 조회하지 않는다. Page 식별 GET과 발행된 개별 post_id 확인 GET은 유지한다.

## 운영 적용 순서

1. 기존 Market Talk 예약/live를 비활성화한 뒤 신규 migration과 코드 적용 순서를 확정한다.
2. 기존 v3 migration 이후 `20261012104810_market_talk_db_only_v4.sql`을 적용한다. 새 v4 함수가 추가되며 기존 v3 함수는 유지한다. 새 `talk_policy.enabled`는 false다.
3. `talk_contract_version_v4()`가 4인지 확인한다. `talk_policy`의 실제 Page 행, 예산, 기존 talk SENDING/UNKNOWN을 확인한다. 미확정 원장은 삭제하지 않는다.
4. 정책 적용일은 기본적으로 migration 적용일 다음 KST 날짜다. 주말이면 다음 영업일 이후 처음 평일에 동작한다. 기존 18:30 슬롯을 덮어쓰지 않는다.
5. 읽기 전용 release probe로 계약·시장 출처·설정·Page 식별을 검사한다. PREPARED는 실제 게시 권한 및 게시 성공 증명이 아니다.
6. 승인된 운영 적용 절차에서 `talk_policy.enabled=true`로 활성화한다. 모델/단가/허용 캐릭터/기존 예산을 확인하고 AUTO/LIVE/SCHEDULE/WATCH 변수를 설정한다.
7. 유효한 오후 시간창에서 제한된 1건을 검증한다. 실제 글과 DB revision/post_id/본문 해시·verified 결과를 확인한다.

현재 사용자 요청은 문서 최신화·개발이다. 위 운영 DB 변경·main 병합·변수 활성화·공개 게시를 이번 개발 단계에서 수행하지 않았다.

## GitHub Actions 입력

| 목적 | stage | 추가 입력 | 결과 |
|---|---|---|---|
| 설정 읽기 | inspect | 나머지 비움 | 정책/플래그 확인, 생성·게시 없음 |
| 자동 원고 준비 | automate | confirm 비움 | due 이후에만 유료 생성·검수, 게시 없음 |
| 자동 생성·실발행 | automate | confirm=YES | live 플래그·정책·시간창 충족 시 게시 |
| 기존 승인 원고 실발행 | publish | revision, confirm=YES | 해당 슬롯/시간창과 DB 한도 검사 |
| 이미 게시된 글 확인 | verify | 정확한 revision | 동일 post_id 조회, 재POST 없음 |
| 마감 감시 | watch | slot_date 비움 또는 완료 날짜 | 18시 이후 오늘 슬롯 확인 |
| Talk 정지·재개 | pause/resume | YES, 20자 이상 review_note | Talk 전용 정책 변경 |
| 결과 불명 복구 | reconcile | revision, YES, 사유 및 post_id 또는 not_posted | 명확한 운영자 증거 필요 |

`automate`의 confirm 비움도 due 이후 유료 호출이 가능하다. dry라는 이유로 비용 0이라고 해석하지 않는다. 즉시 확인하려고 날짜/목표/만료를 강제로 바꾸지 않는다.

## 플래그 및 DB 조건

`MARKET_TALK_AUTO_ENABLED`, `MARKET_TALK_LIVE`, `MARKET_TALK_SCHEDULE_ENABLED`, `MARKET_TALK_WATCH_ENABLED`는 용도별로 설정한다. `FACEBOOK_CONTROL_ENABLED`는 Market Talk v4 조건에서 제외한다. Sidestory는 기존 `SIDESTORY_FACEBOOK_CONTROL_ENABLED`와 기존 경로를 유지한다.

생성 예산은 기존 `facebook_page_policy`의 일·월 예산과 `talk_costs`를 사용한다. 새 `talk_policy`는 활성 상태·발행 횟수만 담당한다. 다른 게시 경로의 enabled 값으로 Talk를 정지하거나 재개하지 않는다.

## 주요 결과 코드

| 코드 | 처리 |
|---|---|
| WAITING_SLOT | 정상 대기, 다음 poll |
| MISSED_WINDOW | 당일 신규 생성/게시 종료, 다음 날 몰아 발행 없음 |
| ALREADY_PUBLISHED | 정상 중복 방지, 유료 생성/POST 없음 |
| CHANNEL_HOLD | Talk 정책 비활성, 실패 종료 |
| POLICY_NOT_EFFECTIVE / LEGACY_SLOT | 이행 조건 미충족, 실패 종료 |
| UNKNOWN / SENDING | 자동 재POST 금지, 조사 후 reconcile |
| POSTED_UNVERIFIED | 이미 게시됐을 수 있음, verify만 수행 |
| WATCH_ALERT | 슬롯 미실행/미발행/미검증/미확정 확인 |

생성/검수의 비용 예약이 FAILED/UNKNOWN이면 같은 날 무한 재생성하지 않는다. 게시 응답 후 DB 저장 실패도 재POST하지 않는다. 삭제로 문제를 숨기지 않고 원장과 감사 기록을 유지한다.

## 검증 범위

로컬 fake/mock는 목록 조회를 실패하도록 강제한 상태에서 정상 POST·개별 검증 및 재실행 무중복을 확인한다. PGlite는 PostgreSQL 함수·권한·시간창·한도 계약 검사다. 실제 독립 연결 동시성 검사는 별도 PostgreSQL CI 작업이며 로컬 환경 권한 제한으로 실행하지 못했다. 운영 모델 품질·실제 Facebook 게시 성공은 별도 베타 항목이다.
