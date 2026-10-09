# Market Talk 출시 전 보완 및 운영 계약

2026-10-09. 이 문서는 이전 MVP 운영 문서의 자동화·출처·게시 확인 관련 설명을 대체한다. 개발 기준 main: `b8c995c4a987fcb4e0a5747dd18913cb956daacb`. 개발 브랜치에서 검증하며 운영 적용·실제 모델 호출·Facebook 게시를 수행하지 않는다.

## 변경된 동작

| 영역 | 동작 |
|---|---|
| 예약 | `automate/publish --scheduled`는 평일 KST 18:30 이상, 23:59 미만에만 진행. 이른 시각·자정 지연은 닫힌 이전 평일 슬롯으로 기록하며 다음 날 원고를 미리 생성하지 않는다. 지나간 슬롯 catch-up 없음 |
| 출처 | 신규 `icg_side.market_talk_source_v1`에서 기존 수치와 `created_at`, `data_quality`를 함께 읽고 검사. metadata가 비면 유료 호출 전 차단 |
| 비용 | 생성/검수 각각 비용 예약 후 모델 시도 상태 기록. COMPLETE/FAILED/UNKNOWN을 구별하고 불확실 비용을 환급하거나 자동 재호출하지 않는다 |
| 공개 형식 | v3도 해설 + 빈 줄 + `EDT : “대사”`. 내부 근거·출처·운영 코드가 공개 본문에 붙지 않는다 |
| 게시 완료 | POST ID만으로 완료를 주장하지 않는다. 원장 및 원고 PUBLISHED 상태와 실제 GET receipt의 Page/ID/본문 hash/공개 상태/생성시각을 확인해야 `verified=true` |
| 확인 실패 | POSTED_UNVERIFIED는 실패 종료. 원장의 PUBLISHED는 유지해 재POST를 방지. 결과 원장 저장 실패는 PUBLISHED_REPORT_PENDING |
| 관측 | 슬롯 요약·실행 이력·단계/안전한 사유 코드. 사건 원장 수정/삭제 권한 없음. 원문 예외·토큰·요청 URL을 보고서에 출력하지 않는다 |
| 감시 | `watch`는 완료된 평일 슬롯을 읽기 전용 검사. 성공 영수증과 검증 이벤트가 맞아야 WATCH_OK. 누락·미확정·미검증은 WATCH_ALERT 및 exit 1 |
| 운영 | workflow_dispatch에 pause/resume/hold/reconcile/verify/watch 제공. 운영 변경은 YES, actor, 20자 이상 사유 필요. approve는 10자 이상 검수 사유 |

GitHub schedule은 정시 실행 보장이 없다. 스케줄의 원래 발화 날짜가 event payload에 없으므로 현재 유효 시간창 기준 정책이며, 수동 재현에는 `--slot-date YYYY-MM-DD`로 정확한 슬롯을 지정한다. 감시도 GitHub 지연 영향을 받는다. 독립적인 외부 가용성 감시는 별도 과제다.

## 상류 데이터 계약 — 현재 정식 오픈 차단 조건

`data_quality.status=complete`, `fallbacks=[]`, `missing_after=[]`, `blocked_fields=[]`를 요구한다. 각 필드의 `data_quality.source_status[field]`에는 다음 실제 수집 근거가 필요하다.

| 필드 | 요구 단위 |
|---|---|
| vix, fear_greed | index |
| us10y, spy_change, nasdaq_change | percent |
| oil_wti | USD_per_barrel |

각 값은 `status=ok`, 비어 있지 않은 `provider`, timezone 포함 `observed_at`, `market_session_date`(YYYY-MM-DD), 해당 `unit`을 함께 제공해야 한다. snapshot은 KST 기준 0~3일 이내, collection/observation은 4일 이내 및 미래 5분 이내, 주식 관련 3개 지표는 같은 세션을 요구한다. 값 범위는 비정상 수치 탐지용이며 시세 정확성 검증이 아니다. 음의 WTI 가능성을 허용한다.

현재 검토한 운영 snapshot의 `source_status={}`는 이 계약을 충족하지 않는다. provider 이름·관측시각·시장 세션을 DB 조회 시각으로 만들어 넣지 않는다. 실제 수집 계층의 원천 응답과 계산 방법을 확인해 metadata를 생산하고, 유효 snapshot으로 별도 사전 검증해야 한다. 이번 변경은 본편 수집 코드/DB 데이터를 변경하지 않는다. 이 연계가 완료되기 전에는 정식 오픈 불가다.

## 마이그레이션과 배포 전 절차

적용 순서:

1. 기존 `sidestory/migrations/0001_icg_side_schema.sql`.
2. `20261006103606_market_talk.sql`.
3. `20261007151940_market_talk_automatic.sql`.
4. 신규 `20261009084103_market_talk_hardening.sql`.

신규 migration은 Supabase CLI로 생성했으며 **운영 미적용**이다. `icg.daily_snapshots`를 읽는 SECURITY INVOKER view, 슬롯/이력/모델 시도 3개 테이블, 3개 RPC만 추가한다. anon/authenticated 금지, 테이블 RLS, backend service_role 권한. source view는 SELECT만 허용하며, 기반 테이블의 기존 SELECT/RLS와 schema usage가 필요하다. 본편 DDL/DML 변경 없음. 기존 service_role 키 전체의 본편 쓰기 권한까지 격리하는 것은 아니다.

코드는 `talk_contract_version()=3`을 확인한다. 미적용 상태는 DB_MIGRATION_REQUIRED 또는 계약 불일치로 차단하며 권한을 public에 넓혀 우회하지 않는다. 운영 적용 전 별도 staging에서 신규 migration 및 rollback(기능 비활성화, 원장 유지)을 확인한다.

## 운영 명령 및 복구

```bash
pip install --require-hashes -r sidestory/market_talk/requirements.lock
python -m sidestory.market_talk --stage inspect --output output/market-talk-report.json
python -m sidestory.market_talk --stage watch --slot-date YYYY-MM-DD --output output/market-talk-report.json
python -m sidestory.market_talk --stage verify --revision EXACT_REVISION --output output/market-talk-report.json
```

`inspect` 및 dry-run `publish`는 DB 읽기만 수행한다. `watch`는 모델/Meta 호출 및 DB 쓰기 없음. `verify`는 Meta GET 및 검증 결과의 DB 이벤트 기록만 수행하며 모델 호출·재POST는 없다. 원고 만료 후에도 전달 확인이 가능하고 원래 원고 슬롯에 기록한다. receipt 조회 실패 시 해당 명령으로 재확인하며 POST를 다시 보내지 않는다. UNKNOWN/SENDING은 기존 reconcile 절차로 운영자가 실제 Page/본문/시각을 확인해야 한다. verify는 미확정 전송을 자동 해제하지 않는다.

신규 watcher는 `MARKET_TALK_WATCH_ENABLED=true`일 때 평일 종료 후 KST 00:15(Tue~Sat) 실행한다. 기본 false. watcher에는 Meta/Anthropic Secret을 주입하지 않는다. 누락은 GitHub 실패·경고·안전한 summary/artifact로 확인한다. 기존 Telegram 발송은 추가하지 않았다. 운영자는 GitHub 실패 알림 수신 설정을 확인해야 한다.

자동 생성/검수/승인은 `MARKET_TALK_AUTO_ENABLED`가 켜져야 하며 사람 검수 완료로 표시하지 않는다. 실제 게시에는 기존 DRY_RUN/LIVE/CONTROL 플래그, Page 정책, 승인·시각·통합 한도·불확실 원장 차단을 모두 통과해야 한다. `automate --scheduled --live`는 유료 생성이 포함되는 운영 명령이므로 테스트용 연결 없이 실행하지 않는다.

## 통합 CI에서 발견한 기존 외전 호환성

공용 이미지 엔진의 일반 생성 경로는 provider 호출 전에 `image_generation_store_attempt_diagnostic`에 비공개 입력을 기록하도록 강화되었으나 외전 DB에는 해당 RPC가 없었다. 실제 외전 PostgREST 통합 CI에서 이미지 단계 HOLD로 확인했다. 이에 `20261009091525_side_image_attempt_diagnostics.sql`을 추가했다. 기존 외전 `0001`/`0003` ledger 이후 적용하며 본편 SQL의 동일한 입력 증거 계약을 icg_side에 제공한다. 신규 테이블은 RLS 및 service_role SELECT/INSERT만 허용하고, token/scope/panel/fingerprint 일치·입력 선기록·불변 payload를 요구한다. 외전 이미지 비용 상한·재시도·불확실 보류를 변경하지 않는다. 이 migration도 운영 미적용이다.

## 검증 범위 및 오픈 판정

순수 정책/진단/감시 단위테스트, 실제 SDK의 격리 HTTP 통합테스트, 임베디드 PostgreSQL SQL 계약, 기존 외전 회귀를 수행한다. HTTP fixture는 SQL 엔진을 대체하지 않으며 별도 SQL 계약과 함께 해석한다. 실제 PostgreSQL 독립 연결 경쟁은 PR CI에서 실행한다.

정식 오픈 조건: 모든 개발/CI 검사 통과, 상류 provenance 계약 충족, staging migration 검증, 운영 Meta 권한·지원 버전 확인, 승인된 제한 게시 1건의 실제 receipt 및 watcher 확인. 이번 offline 통합테스트는 실제 Supabase 배포·Meta 권한·시세 정확성·유료 모델 한국어 품질을 증명하지 않는다.
