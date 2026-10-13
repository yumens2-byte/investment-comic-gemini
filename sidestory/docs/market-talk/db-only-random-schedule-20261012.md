# ICG Market Talk 상세설계 v1.0
작성: 2026-10-12 KST
대상: yumens2-byte/investment-comic-gemini / sidestory/market_talk
코드 검토 기준: main 33f22a51c35a10ed53a6872270e20c99a35a8b53
상태: 설계 완료. 구현·마이그레이션·운영 설정 변경·실발행 미수행.

## 1. 결정사항과 설계 기본값
사용자 요구: Facebook 페이지 전체의 게시 목록 조회 및 다른 게시물과의 간격 제한 제거. Market Talk만 관리. 점심 이후 무작위 시각에 원고를 작성하고 발행.
하루 5건은 이전 콘텐츠 예시의 가정일 뿐 채택 요구가 아니다. 평일 하루 최대 1건·KST 월요일 시작 주 최대 5건을 유지한다.
정확한 오후 시간대는 사용자가 지정하지 않았으므로 다음은 조정 가능한 설계 기본값이다.
- 목표 시각: 평일 13:00~17:30 KST 중 분 단위 무작위 1개.
- 실제 발행 허용: 목표 시각 이상, 당일 18:00 미만. 지연이 크면 미발행할 수 있다.
- 가장 늦은 목표 시각에도 마감까지 30분 여유를 둔다. 이 여유가 실행을 보장하지는 않는다.
- 점검 실행: 평일 13:00~18:00 KST, 10분 주기(종료 시각 실행은 누락 판정만 수행).
- 최소 시간 간격을 별도로 추가하지 않는다. 당일 1건·주 5건으로 통제한다. 하루 1건은 연속 24시간 제한과 다르다.
- 자료는 목표 시각에 도달한 실행에서 최신 유효 DB 스냅샷을 선택한다. 아침에 원고를 미리 만들지 않는다.
- GitHub 예약 지연으로 목표 시각 정확한 실행이나 발행은 보장하지 않는다. 목표 도달 후 첫 실제 실행에서 처리한다.

## 2. 현재 코드에서 확인한 변경 필요점
| 위치 | 현재 동작 | 변경 |
|---|---|---|
| publishing.py ControlledPublisher | check/create_post에서 recent_receipts 호출 | Market Talk용 별도 publisher 구성, 목록 조회 없음 |
| facebook_begin RPC | 관측 2분 이내·페이지 총량·4시간 간격·페이지 전체 UNKNOWN 검사 | 기존 RPC 보존, talk 전용 RPC 추가 |
| __main__.py automate | 생성·검수 이후 발행 전 검사 | 비용 이전에 슬롯·DB 정책·잔여 한도·미해결 발행 검사 |
| automation.py prepare_context | 18:30 due_at·23:59 만료 고정 | 저장된 목표 시각·18:00 종료 사용 |
| talk_record_outcome | 슬롯 최초 저장 시 18:30 고정 | 일정 생성 RPC에서 시간 확정, 결과 기록은 시간 변경 금지 |
| policy.py·monitoring.py | 기존 슬롯 시간 정책 | 저장된 슬롯·window_end 기준 |
| release probe | Meta feed 읽기 실패가 준비 차단 | DB 계약·talk 정책 확인, feed 읽기 제거 |
| watch workflow | 별도 활성화 변수 | 새로운 마감 기준 점검·미실행 감지 검증 |

Sidestory의 #118은 설정 분리이지 Market Talk 목록 조회 오류 해결이 아니다. 기존 ControlledPublisher 및 Sidestory workflow는 이 변경으로 수정하지 않는다.

## 3. API 유지·제거 범위
| API/조회 | 처리 | 목적 |
|---|---|---|
| Facebook GET page/feed 목록 | 정상 Market Talk 경로에서 제거 | 외부 게시량 합산 폐지 |
| facebook_observe | Market Talk 경로에서 호출 제거 | 외부 관측 원장 의존 제거 |
| DB 시장 스냅샷 | 유지 | 원고의 실제 근거 |
| DB Market Talk 원장 | 유지·강화 | 중복·일/주 한도·불명확 결과 관리 |
| Facebook GET page id/name | 유지, 신규 유료 생성 전 1회 | 설정된 Page 식별, 게시 권한 전체 증명 아님 |
| Facebook POST page/feed | 유지 | 실제 글 발행 |
| Facebook GET post_id | 유지 | 이번 게시물 본문·Page·공개 상태 검증 |
| 장애 복구 확인 | 정확한 post_id 조회 또는 운영자 증거 | UNKNOWN 자동 재POST 금지 |

‘조회 제거’는 발행 전 페이지 전체 목록 조회 제거다. 게시 후 개별 글 확인은 목적이 달라 유지한다. 개별 조회 실패 시 POSTED_UNVERIFIED, 재POST 없이 verify만 수행한다.

## 4. 스케줄 및 슬롯
신규 모듈 scheduling.py에서 주말/목표시각/마감/정책을 계산한다. 표준 시계는 DB now(), 저장은 timestamptz, 업무 날짜는 Asia/Seoul이다.
talk_slots의 (page_id,slot_date) PK를 활용한다. 신규 일정 RPC talk_schedule_ensure는 해당 날짜 레코드가 없을 때만 무작위 due_at을 삽입한다.
- 난수 후보는 Python secrets.randbelow(271)로 13:00~17:30의 271개 분 중 선택한다.
- RPC가 후보의 KST 날짜·평일·범위를 검사하고 ON CONFLICT로 기존 시간을 반환한다.
- 경쟁 실행의 패자는 저장된 시간을 재사용한다. 재실행·설정 변경으로 당일 시간을 다시 뽑지 않는다.
- policy_version 및 schedule_origin을 슬롯에 추가해 기존 18:30 슬롯과 구분한다.
- 기존 슬롯/원고의 due_at을 강제로 변경하지 않는다. 새 정책은 배포 다음 영업일부터 적용한다.
- 최초 poll이 늦게 시작되어도 18:00 전이면 이미 지난 목표 시각을 즉시 처리할 수 있다. 예정 지연 시간을 기록한다.
- 18:00 이상이면 신규 생성·POST 금지. 이미 SENDING인 요청은 강제 취소하지 않고 결과 기록/검증만 마친다.
- 후보 cron: '*/10 4-9 * * 1-5' (UTC). 18:10 이후 실행은 애플리케이션에서 no-op. 구현 시 공식 Actions 문서 및 actionlint로 검증한다.
- 장시간 sleep, 자가 workflow dispatch, 미래 날짜 미리 생성은 사용하지 않는다.

## 5. 처리 흐름
1. 실행 플래그·DB 계약 버전 확인.
2. 기존 PUBLISHED/UNKNOWN 등 당일 상태 확인. 완료면 유료 호출·POST 없이 종료.
3. 평일인지 확인하고 슬롯 생성/조회.
4. due_at 이전이면 WAITING_SLOT; 종료 시각 이후면 MISSED_WINDOW.
5. talk 전용 정책·당일/주간 건수·미해결 talk 발행·예산 검사.
6. 기존 원고가 없다면 최신 유효 시장자료 조회 및 출처/세션/중복 검사.
7. Page 식별 확인 후 생성 비용 원자 예약 → 모델 1회 → DRAFT 영속 저장.
8. 검수 비용 원자 예약 → 별도 모델 검수 → 승인 또는 CONTENT_HOLD.
9. 발행 직전 원고 해시·자료 변경·기한을 재검사. 동일 DB 정책을 원자 RPC에서 다시 확인.
10. SENDING 예약을 먼저 commit한 뒤 Facebook POST 1회.
11. 결과·원고·슬롯 상태를 기록하고 정확한 post_id를 GET으로 검증.
12. 성공은 PUBLISHED + verified=true. 실패는 안전 코드와 단계 기록.

스냅샷 재검사는 생성 중 원천 변경을 감지하는 검사다. 외부 실시간 시세 재수집 기능은 추가하지 않는다. 변경된 자료를 무시하거나 같은 날짜 원고를 자동 무한 재생성하지 않는다.

## 6. DB 책임 분리
신규 talk_policy 테이블(제안): page_id PK, enabled, day_limit=1, week_limit<=5, timezone='Asia/Seoul', policy_version, updated_at, updated_by, hold_reason.
생성 예산은 기존 talk_costs 및 현행 예산 필드 사용. 예산 변경·확대 없음.
기존 facebook_page_policy.enabled/exclusive_managed/coexistence_allowed/observed_at는 신규 talk 발행 허용 조건에서 제외한다.
신규 RPC 세트(명칭은 설계안):
- talk_schedule_ensure: 날짜별 일정 1회 확정.
- talk_begin_v4: talk 정책 행 잠금 → 동일 revision 및 슬롯·해시·승인·한도·UNKNOWN 검사 → SENDING 예약.
- talk_finish_v4: token/CAS로 결과 저장. talk 오류는 talk 정책만 정지.
- talk_set_hold_v4 / talk_resolve_v4: talk만 pause/resume/reconcile. Sidestory 상태에 영향 없음.
- talk_record_outcome_v4: 기존 슬롯의 due_at/window_end를 바꾸지 않고 사건 추가 및 상태 전이.
- talk_contract_version_v4: 신규 전용 계약 확인. 기존 버전 3 함수는 보존하여 공유 경로 회귀 방지.

기존 facebook_deliveries 원장을 재사용하되 모든 한도·미해결 조회에 page_id AND track='talk'를 강제한다. external/sidestory 이력은 집계하지 않는다.
당일/주간 집계는 published_at의 KST 경계로 계산한다. 같은 revision의 PUBLISHED는 정책·시간 검사보다 먼저 기존 post_id를 반환한다.
정책 행 잠금 직렬화로 서로 다른 revision의 동시 발행도 차단한다. SENDING/UNKNOWN이 있는 talk는 신규 talk 발행을 막는다.
DB lock은 외부 API 동안 유지하지 않는다. 원장 SENDING이 영속 잠금 역할을 한다.
비용 예약은 기존 Page·날짜 키를 유지해 두 worker의 같은 날 중복 호출을 막는다. 재시도 시 COMPLETE/FAILED/UNKNOWN/RESERVED를 구별하고 불확실 결과는 재호출하지 않는다.
RLS·SECURITY INVOKER·service_role 한정 유지. public/anon/authenticated 권한 추가 금지. 신규 인덱스는 (page_id,track,state,published_at) 조회 패턴과 실행계획 확인 후 적용한다.

## 7. 상태와 실패 정책
| 상황 | 결과 | 후속 |
|---|---|---|
| 목표 전 | WAITING_SLOT | 다음 poll |
| 당일 이미 발행 | ALREADY_PUBLISHED | 생성/POST 없음 |
| 자료 미도착·일시 DB 읽기 실패 | SOURCE_NOT_READY / DB_READ_FAILED | 유료 시도 전이면 다음 poll 재검사 |
| 자료 계약 오류 | SOURCE_INVALID | 유료 호출 없음, 마감까지 교정 가능 |
| 생성/검수 호출 결과 불명 | MODEL_UNKNOWN | 비용 예약 유지, 자동 재호출 없음 |
| 콘텐츠 미달 | CONTENT_HOLD | 당일 반복 생성 없음 |
| 게시 명백한 거절 | REJECTED | talk 정지, 원인 교정 후 명시 복구 |
| 게시 응답 불명 | UNKNOWN 또는 SENDING | 자동 재POST 없음 |
| POST 성공·DB 저장 실패 | SENDING 잔존 | 증거 기반 reconcile |
| 개별 게시 확인 실패 | POSTED_UNVERIFIED | 같은 post_id verify만 |
| 시간창 종료 미발행 | MISSED_WINDOW | 다음 날로 원고 이월 안 함 |

poll 증가로 같은 장애 알림이 반복되지 않도록 Page·날짜·reason별 중복 알림 억제. run_events는 시도별 남기되 슬롯 요약이 PUBLISHED에서 WAITING으로 퇴행하지 않는다.
18:10 이후 watcher는 오늘 종료 슬롯을 확인한다. 슬롯 자체가 없어도 NO_RUN 경보를 내야 한다. 기존 completed_day가 전날만 조회하면 당일 마감 검사에 맞게 변경한다.
보고서: slot_date, due_at, actual_started_at, lateness_seconds, source_date, revision, status, reason_code, post_id, verified, paid_call_count. 토큰·원문 예외 출력 금지.

## 8. 수정 대상과 영향 범위
신규: scheduling.py, talk 전용 DB/publisher 모듈, 마이그레이션 1개, 스케줄/격리/통합 테스트.
수정: __main__.py, automation.py, policy.py, store.py, monitoring.py, diagnostics.py, Market Talk 실행/release probe/watch workflows, 관련 문서 및 테스트.
기존 service.py의 검증은 재사용하되 Page check 중복 호출 방지 인터페이스를 검토한다. shared graph.py 오류 구조 개선은 필요 시 별도 회귀 범위로 분리한다.
개발 전 rg로 18:30·23:59·facebook_begin/finish/set_hold/resolve·FACEBOOK_CONTROL_ENABLED 참조를 전수 검색한다. 변경 파일 수는 구현 diff 확정 전 추정하지 않는다.
Sidestory workflow, 본편 생성 로직, 시장 수집 파이프라인, 기존 게시물은 변경 범위 밖이다.

## 9. 검증 계획 및 합격 기준
- 목록 조회 provider가 항상 실패하는 fake에서도 신규 talk 발행·개별 검증은 성공; feed GET 호출 0.
- 외부/Sidestory 이력 100건과 직전 게시가 있어도 talk만으로 허용 판단.
- talk 당일 1건·주 5건 도달 시 차단. 다른 revision 동시 두 요청 중 POST 허용은 하나.
- SENDING/UNKNOWN talk는 신규 talk 차단, Sidestory UNKNOWN은 신규 정책에 영향 없음.
- 슬롯 난수 최소/최대·주말·KST 자정·월요일 경계·18:00 경계·지연·재실행 목표 고정.
- 목표 전/마감 후 모델 호출 0. 정상 하루 생성 1회·검수 1회·POST 1회.
- 생성 후 자료 변경·검수 실패·비용 예약 불명 시 자동 재생성 0.
- POST timeout/원장 저장 실패/검증 실패 재실행 시 추가 POST 0.
- 기존 v3 함수 및 ControlledPublisher/Sidestory 계약 테스트 그대로 통과.
- 운영자 pause/resume/reconcile는 talk scope 및 감사 기록 검증.
- watcher는 당일 슬롯 없음/미발행/미검증 탐지, 정상 완료 WATCH_OK.
검증 계층: 순수 정책 단위 → 실제 PostgreSQL RPC 동시성/권한 → fake provider 통합 → CI → 운영 읽기 점검 → 제한된 실제 1건.
현재 설계 단계이며 이 테스트들을 수행 완료했다고 주장하지 않는다.

## 10. 배포·이행·롤백
1. 코드 작성 전 현재 main·운영 함수 최종 정의를 재확인. 기존 automatic migration 등 후속 정의와 충돌 확인.
2. Supabase 최신 문서·changelog 확인 후 로컬 DB 구현. CLI 생성 migration, 회귀·권한·동시성 검증.
3. additive DB v4 적용. 기존 감사/발행/비용 데이터 유지. talk 정책은 disabled로 생성.
4. 기존 당일 원고·미해결 발행 및 이전 정책 enabled 상태 조사. 필요한 원장 그대로 보존.
5. 신규 코드·workflow 적용, 자동화 비활성 상태에서 읽기 점검. 다음 영업일을 정책 적용일로 지정.
6. 실제 1건 베타: 목록 조회 0, 원고 근거, post_id/본문/공개 상태, DB 일치 검증.
7. 예약·watch 활성화 후 첫 정상 슬롯 확인.
롤백은 talk 예약/live 및 talk_policy.enabled를 끄고 감사 원장을 유지한다. v3 자동 경로로 즉시 되돌려 중복 발행하거나 DB를 삭제하지 않는다.
설계 요청만 받은 현재 단계에서는 위 운영 작업을 실행하지 않는다.

## 11. 확인 근거
- https://github.com/yumens2-byte/investment-comic-gemini/blob/33f22a51c35a10ed53a6872270e20c99a35a8b53/sidestory/market_talk/__main__.py
- https://github.com/yumens2-byte/investment-comic-gemini/blob/33f22a51c35a10ed53a6872270e20c99a35a8b53/sidestory/market_talk/publishing.py
- https://github.com/yumens2-byte/investment-comic-gemini/blob/33f22a51c35a10ed53a6872270e20c99a35a8b53/sidestory/market_talk/store.py
- https://github.com/yumens2-byte/investment-comic-gemini/blob/33f22a51c35a10ed53a6872270e20c99a35a8b53/sidestory/supabase/migrations/20261006103606_market_talk.sql
- https://github.com/yumens2-byte/investment-comic-gemini/blob/33f22a51c35a10ed53a6872270e20c99a35a8b53/sidestory/supabase/migrations/20261009084103_market_talk_hardening.sql
- 기존 장애 및 Sidestory 성공 로그는 앞선 코드리뷰에서 확인. 이 문서는 새로운 실운영 결과를 추가하지 않는다.
