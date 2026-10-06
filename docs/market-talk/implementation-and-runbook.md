# Market Talk: 구현 및 운영 절차

작성일: 2026-10-07 KST. 최초 분석 main: `b324935bf2b5e2fe45614bc069de61c2abf69553`. 구현 검증 기준 main은 신규 QC완화 커밋 `cfc325029122fc95949aeaf817f028528c3ee49b`로 갱신했다.

## 구현 범위

Facebook Page 1곳을 위한 **사람이 검수한 텍스트의 예약 발행 MVP**다. 캐릭터·시장 데이터에서 초안을 만드는 기능과 실제 게시 기능을 분리했다. 자동으로 글을 승인하거나 계정의 제한을 우회하는 기능은 없다. Threads, 신규 이미지, 댓글·좋아요는 포함하지 않는다.

- 신규 경로: `python -m sidestory.market_talk`.
- 본편은 `icg_side.main_feed_market_v1`만 읽는다. 카논은 `config/characters.yaml`의 지정된 인물만 읽는다.
- Context에 검증자가 확인한 출처·관측시각·시장 세션·유효기간을 넣는다. 기존 시장 view에 원천 관측시각/출처가 충분하지 않으므로 이를 자동 추정하지 않는다.
- Claude 유료 preview: 명시 모델/요금/예산, 토큰 사전 계산, 호출 전 비용 예약, SDK 재시도 없음. 최초 생성+명시 수정 1회 제한. 불명확 비용은 자동 환급하지 않는다.
- 원고는 원문 근거, 해설, 명시적 창작 대사로 분리된다. 생성 자체는 사실성 검증 완료를 뜻하지 않는다.
- 원고/근거/카논/예약시각을 묶은 SHA-256 revision을 사람이 승인한다. 원고는 불변이며 수정 시 보류 후 새 revision을 만든다.
- 사실 수치 복사·기준시점·버전 검사와 금칙 표현, 주장키/근거키·문자열 유사도 검사를 수행한다. 의미/인과관계/말투 전체를 코드가 증명하는 것은 아니므로 인간 검수를 유지한다.
- 페이지 최근 24시간 게시물을 완전히 읽은 뒤 통합 예약한다. 페이지당 최근24h 2건·최소4h, 신규는 KST 하루1건·주5건. 이 값은 내부 제한이며 Meta 안전 보장값이 아니다.
- HTTP 전송 의도를 DB에 먼저 남긴다. 응답 유실 또는 프로세스 종료 후에는 해당 페이지가 계속 차단된다. 누락된 최근글 검색 결과로 재게시하지 않는다.
- 신규 큐는 해당 KST 날짜의 승인·미만료 원고만 선택한다. 이전 날짜의 놓친 글을 몰아 발행하지 않는다.
- 기존 외전 dry-run 계약은 그대로 유지한다. 신규 `inspect`와 `publish` 기본 모드는 DB 읽기 전용이며 유료 API·Facebook 호출·원격 변경이 없다. 보고서 로컬 파일은 쓸 수 있다.

## 요구사항 대비 구현 판단

| 구분 | 상태/제약 |
|---|---|
| MT-01~06 근거/카논 | 코드 검사+인간 provenance 확인 방식. 원천 시각/출처 자동 수집은 미구현 |
| MT-07~11 생성/중복/승인 | 구현. 게시할 새 원고가 없으면 정상 스킵. 의미중복은 검수자 확인 필요 |
| MT-12 통합 상한 | 기존 외전과 신규 양쪽 `FACEBOOK_CONTROL_ENABLED=true` 및 동일 Page 정책이 전제 |
| MT-13~15 선점/복구 | 원자 SENDING 예약+claim token. UNKNOWN/REJECTED는 수동 확인 후 재개. 자동 재시도보다 보수적 운영 |
| MT-16~17 dry-run/preview | 분리 구현. preview는 비용 예약을 기록하는 유료 작업이므로 dry-run이 아님 |
| MT-18~22 통제/감사/보안 | 페이지 스위치·기능 플래그·원고 보류·감사 및 비용 원장 구현 |
| MT-23 성과 수집 | 후속 단계. 현재 게시 결과/감사/비용만 기록 |
| MT-24 Threads | 후속 단계 |
| 품질 검증 후 완전자동 승인 | 미활성·미구현. 14일/10건 검수 실적 후 별도 설계 판단 |

논리 설계의 PLANNED/VALIDATED/READY 단계는 프로세스 내부 단계로 처리하고 DB는 DRAFT/APPROVED/CONTENT_HOLD/PUBLISHED 원고와 별도 전달 원장으로 단순화했다. 전달 원장의 SENDING은 임대 만료로 해제하지 않는다. 정확히 한 번 외부 실행을 보장한다고 주장하지 않으며, 결과가 불명확할 때 진행을 멈춰 중복을 예방한다.

## 운영 적용 전 필수 확인

1. 실제 Page ID·관리 권한·게시 권한·앱 모드/심사·API 지원 버전을 Meta 공식 문서와 앱에서 확인한다. Page 이름 조회 성공만으로 게시 권한 검증을 완료하지 않는다.
2. 기존 외전 스케줄/실제 게시 계정과 신규 Page가 동일한지 확인한다. API를 거치지 않는 동시 수동 게시가 있으면 합산 제한을 엄밀히 보장할 수 없다. 관리 절차를 단일화한 뒤 `exclusive_managed=true`로 기록한다.
3. 본편 카논 텍스트 사용 인물을 `MARKET_TALK_CHARACTER_IDS`로 승인한다. 그림의 캐릭터 사용 규칙은 바꾸지 않는다.
4. 생성 모델과 해당 모델 요금, 일/월 예산을 확정한다. 기본 예산 0이면 유료 생성은 막힌다.
5. 운영 DB 적용, 실제 Page 계약 테스트, 다중 연결 경쟁 검증 후 운영 활성화를 승인한다. 이번 개발 과정에서는 실행하지 않았다.

## DB 적용 순서

기존 `sidestory/migrations/0001_icg_side_schema.sql`이 적용된 프로젝트에서 아래 신규 파일을 검토 후 적용한다.

`sidestory/supabase/migrations/20261006103606_market_talk.sql`

Supabase CLI `migration new`로 생성한 로컬 산출물이다. 운영에 자동 적용되지 않는다. 새 파일은 기존 본편 테이블을 수정하지 않고 `icg_side`에 5개 테이블·인덱스·트리거·RPC를 추가한다. 모든 신규 테이블 RLS 활성화, anon/authenticated 접근 금지, SECURITY INVOKER 함수에 backend service_role만 권한을 준다. 기존 `SUPABASE_KEY`가 어떤 역할인지는 운영에서 확인해야 한다.

운영자는 Page 정책을 생성하되 기본 비활성을 유지한다. 아래 값은 **교체할 예시이며 실행 완료를 의미하지 않는다**.

```sql
insert into icg_side.facebook_page_policy
  (page_id, daily_budget_usd, monthly_budget_usd)
values ('REPLACE_WITH_REAL_PAGE_ID', 0, 0);
```

일/월 예산은 USD다. 등록 전 실제 금액을 결정한다. public/anon에 권한을 넓혀 권한 문제를 해결하지 않는다. 신규 read/write 권한은 icg_side에 한정하지만, 기존 service_role 키 자체가 본편 DB를 쓸 수 있다면 이것은 DB 계정 차원의 완전 격리가 아니다. 전용 최소권한 역할은 후속 운영 보안 과제다.

## 설정

| 키 | 용도/기본값 |
|---|---|
| SUPABASE_URL / SUPABASE_KEY | 기존 backend 연결; 로그에 노출 금지 |
| FACE_PAGE_ID / FACE_PAGE_TOKEN | 기존 Page 연결. 토큰은 Secret 사용 |
| FACEBOOK_CONTROL_ENABLED | 기존 외전+신규 통합 Page 제어. 기본 false |
| MARKET_TALK_LIVE | 신규 실제 게시 허용. 기본 false |
| MARKET_TALK_SCHEDULE_ENABLED | 신규 예약 workflow 허용. 기본 false |
| MARKET_TALK_CHARACTER_IDS | 승인된 캐릭터 ID를 쉼표로 구분. 기본 비어 있음 |
| DRY_RUN | 신규 CLI에서는 기본 true. live에는 false 필요 |
| MARKET_TALK_MODEL | 유료 preview 모델. 기본 없음 |
| MARKET_TALK_INPUT_USD_PER_MTOK / OUTPUT_USD_PER_MTOK | 확인된 해당 모델 요금. 기본 0으로 생성 차단 |
| ANTHROPIC_API_KEY | preview에만 필요. 예약 게시 workflow에는 주입하지 않음 |

`SIDESTORY_GRAPH_VERSION`은 기존 어댑터 설정이다. 코드에 있는 기본 버전 문자열을 공식 지원 확인 대신 사용하지 않는다.

## 원고 생성·검수·발행

환경변수는 안전한 Secret 주입 방식으로 설정한다. 아래 명령에 토큰을 직접 넣지 않는다.

```bash
pip install --require-hashes -r sidestory/market_talk/requirements.lock
python -m sidestory.market_talk --help
```

1. 검수자가 `provenance.json`을 만든다. 필드는 `topic`, `claim_key`, `kind`(market_close/concept/episode), `snapshot_date`, `character_id`, `evidence`(id/statement/source_url/observed_at/market_session), `expires_at`, `provenance_reviewer`, `provenance_note`다. HTTPS 출처는 실제 공개 자료를 사용한다. 관측시각은 timezone 포함, 휴일은 마지막 거래 세션을 명시한다. snapshot은 현재 시각으로 대체하지 않는다.
2. `prepare`가 실제 읽기 view의 정확한 snapshot hash와 카논 hash/설정을 붙인다. 잘못된 source statement를 이 단계가 자동 팩트체크해 주지는 않는다.

```bash
python -m sidestory.market_talk --stage prepare --input provenance.json --output context.json
python -m sidestory.market_talk --stage preview --input context.json --output draft.json
```

유료 preview에는 설정된 생성 예산이 필요하다. 결과 `draft.json`의 `text.commentary`·`text.dialogue`를 검토하고 `due_at`을 유효기간 안의 발행 예정시각으로 정한다. 원고를 사람이 작성한 경우에는 Context와 동일 JSON 구조의 `text`를 직접 작성해 preview 비용을 생략할 수 있다. 수정 재생성이 필요하면 `--attempt 2 --note '구체적인 수정 이유'`를 사용한다. 동일 Context/attempt 재호출은 비용 원장이 차단한다.

```bash
python -m sidestory.market_talk --stage inspect --input draft.json --output inspect.json
python -m sidestory.market_talk --stage submit --input draft.json
python -m sidestory.market_talk --stage approve --revision EXACT_REVISION \
  --actor REVIEWER --note '원천 자료와 수치, 세션, 창작 대사 및 카논 검수 완료' --confirm YES
python -m sidestory.market_talk --stage publish --revision EXACT_REVISION
```

마지막 명령은 dry-run이다. 실제 게시에는 `--live`, `DRY_RUN=false`, `MARKET_TALK_LIVE=true`, `FACEBOOK_CONTROL_ENABLED=true`, DB 정책 enabled/exclusive_managed, 유효한 승인·Page 관측·한도를 모두 충족해야 한다. 외부 원고를 검수 없이 반복 생성/승인하는 스크립트는 운영 범위가 아니다.

GitHub `Market Talk` workflow는 수동 inspect/approve/publish와 평일 KST 18:30 예약 게시를 제공한다. 스케줄은 승인된 원고가 없으면 정상 종료한다. 자동으로 새 원고를 생성하거나 승인하지 않는다. 유료 생성은 별도 명시 실행이며, 시장 출처 자동화와 무인 승인 단계는 후속 과제다.

## 중단·수정·결과 대사

```bash
python -m sidestory.market_talk --stage pause --actor OPERATOR \
  --note '계정 및 게시 결과 확인을 위한 페이지 발행 중단' --confirm YES
python -m sidestory.market_talk --stage hold --revision EXACT_REVISION --actor REVIEWER \
  --note '원천 수치 정정이 필요하여 기존 승인 원고를 보류 처리함' --confirm YES
```

수정한 원고는 새 revision으로 submit/approve한다. 이미 SENDING/UNKNOWN/PUBLISHED인 원고는 hold로 재작성할 수 없다. 공개된 오류 글의 정정/삭제는 운영자가 별도 확인한다. 코드에 자동 삭제 기능은 없다.

UNKNOWN/SENDING이 남아 있으면 Page 조회로 정확한 외부 ID를 확인한다. CLI는 Page·본문 hash·게시시각까지 검증한다. ‘최근 글에서 못 찾음’만으로 미발행을 확정하지 않는다.

```bash
python -m sidestory.market_talk --stage reconcile --revision EXACT_BUSINESS_KEY \
  --post-id VERIFIED_PAGE_POST_ID --actor OPERATOR \
  --note '실제 페이지에서 본문과 생성시각 및 게시 ID를 대조하여 확인함' --confirm YES
```

미발행을 별도 증거로 확정한 경우만 `--not-posted`를 사용할 수 있다. 이 경로는 자동 증명이 아니라 운영자 책임 확인이다. 원고 key는 revision, 기존 외전 key는 SIDE-날짜-01 형식이다. 복구 RPC는 재시도 가능 상태만 만들고 Page는 자동 재활성화하지 않는다. 같은 작업은 최대 총3회까지만 시작 가능하다.

```bash
python -m sidestory.market_talk --stage resume --actor OPERATOR \
  --note '제한 해소 및 모든 미확정 게시 건의 결과 확인을 완료함' --confirm YES
```

이미 전송 중인 HTTP는 중지 스위치로 취소할 수 없다. 중단은 새 전송 의도 생성을 막으며, 진행 중 결과는 대사해야 한다.

## 관측·운영

- `talk_items`: DRAFT/APPROVED/CONTENT_HOLD/PUBLISHED. 미만료 승인 원고가 없으면 정상 무게시.
- `facebook_deliveries`: SENDING/UNKNOWN이 오래 남으면 운영자 확인. 로컬 임대시간으로 자동 해제하지 않는다.
- `talk_audit`: 승인·보류·전송·복구·페이지 설정 이력. 임의 수정 금지.
- `talk_costs`: 보수적으로 예약한 비용이며 실제 청구액과 동일하다고 표시하지 않는다.
- Workflow 실패/보고서로 상태를 확인한다. 신규 Telegram 알림 연계는 포함하지 않았고 기존 알림 코드는 변경하지 않는다.
- 미수집 도달/반응/숨김/신고를 0으로 표시하지 않는다. API 한도 숫자는 하드코딩하지 않고 플랫폼 오류 시 추가 전송을 멈춘다.

## 검증 및 제한

`validation.md`에 실제 실행 결과를 기록한다. PGlite 검사는 PostgreSQL SQL/권한/원자 동작의 계약 검사다. 실제 Supabase/PostgREST 전체 스택, 다중 DB 연결 경쟁, 실제 Meta 권한·게시, 모델의 한국어 품질은 별도 운영 전 검증 대상이다.

롤백은 신규 스케줄/라이브 플래그 비활성화와 Page pause를 먼저 수행한다. DB 원장과 이미 발행한 글은 삭제하지 않는다. 기존 외전의 최근글 미발견 재게시 방지 수정은 안전 보완이므로 원복 여부를 별도로 판단한다.
