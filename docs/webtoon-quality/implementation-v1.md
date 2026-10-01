# 미국시장 히어로웹툰 품질 개발 v1

2026-10-01 / base: bff615b9d2d77f70f54d6a08384dce7dc77557f9

추가 3인 리뷰와 개선은 [code-review-v1.md](code-review-v1.md)에 기록했다. 아래 내용은 최초 구현 시점의 기록이다. 최신 수정에서는 최종 원천 계약 재검증, 실제 비용 초과 HOLD, 기존 발행의 조건부 episode claim, 영상의 정확한 회차 연결·면책 보존·대사 HOLD를 추가했다. 기존 SNS의 자동 부분 성공 재개·영상 전용 파트 이력·운영 DB 실증은 여전히 후속 범위다.

## 적용 범위

미국시장 히어로웹툰 고도화 설계를 오프라인 검증 가능한 Python 계약과 실행기로 구현했다. 신규 품질 트랙은 운영 SNS 발행과 분리되어 있다. 실제 생성 이미지·영어 편집·10개 역할의 사람 검수·12편 파일럿 성적은 이번 단위테스트로 증명하지 않는다.

| 요구 | 구현 | 한계와 다음 단계 |
|---|---|---|
| R01 근거 | 관측·수집 시각/거래일/출처/단위/가격기준, 유한값, 합성 데이터 표시 | 제공된 거래일 정책을 검증하며 실제 거래소 캘린더 조회는 별도 연결 |
| R02 랭킹 | 단위와 기준이 같은 승인 스케일로 정규화, 미래 스케일 차단 | 스케일 승인·보정 데이터의 통계 적합성은 검수 대상 |
| R03 주장 | 표시 필드별 주장 분류, 근거 ID, 숫자 인용 값/단위/기준 대조, 확정 예측·근거 없는 확정 인과 차단 | 자연어 전체 의미·인용 숫자와 텍스트의 의미 일치는 사람 검수 필요 |
| R04 서사 | 7개 드라마 비트+면책 1컷, 목표/행동/저항/비용/상태 변화/앞선 인과/필수 인물 | 계약 작성은 수동; 기존 생성기가 자동 작성하지 않음 |
| R05 연속성 | 기한 스레드 전체 회수 또는 사유·새 날짜, 새 스레드 최대 1, NO_BATTLE 모순 차단 | 회수 장면의 실제 설득력은 편집 검수 |
| R06 카논 | 승인 manifest 버전/폼/REF SHA256, 경로 탈출·누락·중복·폼 대체 차단 | 기존 registry 자동 변환과 이미지 내 소품·손·방향 판독은 후속 |
| R07 이미지 | 실제 이미지 QC와 사람 역할 평가 누락 시 release 차단 | 이미지 인식 판정기는 구현하지 않음 |
| R08 호출/비용 | 원자적 비용 예약, UTC 일/월/에피소드 상한, 패널 최대 2회, 영속 호출 횟수, 불명확 과금 재호출 차단 | 단일 호스트 SQLite; 실제 SDK 어댑터는 단일 호출 보장 후 연결 |
| R09 모바일 | 원본 비율 보존, 픽셀 측정 줄바꿈, 360 기준 최소 14px(원본 42px), 보호 사각형 충돌·넘침 차단, 360/390 미리보기 | 사각형은 1080x1350 합성 캔버스 좌표로 공급; 실제 가독성은 사람 검수 |
| R10 release | 입력·결과물·리포트·채널·버전 해시 결합, 8컷과 두 해상도 미리보기 전체 필수, 합성 표시 제거 차단 | 승인자는 인증 시스템과 연결되지 않은 기록; 서명/권한 검증은 후속 |
| R11 발행 | 파일럿에서 채널/파트 claim, 부분 성공 기록, fencing, timeout 대사 전 재전송 차단 | 분산 GitHub Actions용 PostgreSQL 어댑터·운영 공급자 대사 미구현; live=True 명시 차단 |
| R12 상태 | 기대 파트 missing/unknown/partial, 미정산 호출을 HOLD로 보고 | 운영 스케줄 누락·stalled·외부 알림 연결 미구현 |
| R13 QC | 20항목/100점, 80점·영역 하한·Critical/Major 0·10개 역할·필수 사람 판정 | 모의 승인 데이터는 테스트 전용. 10개 역할은 10명의 실제 참여를 증명하지 않음 |
| R14 측정 | 실제 호출/비용/발행 이벤트 기록 | 독자 성과·first-pass율·수동 검수 시간은 수집하지 않음 |

## 기존 코드 안전성 수정

- Gemini 복구에서 첫 REF만 남기고 인물을 하나로 축소하던 분기를 제거했다. 모든 필수 REF를 보존한다.
- SNS 발행 조회에 episode_no를 추가하고 episode/date 충돌을 차단한다.
- 중복 이력 조회가 실패하면 발행을 중단한다.
- 요청 채널 실패나 결과 ID 누락을 완료로 처리하지 않는다.
- DRY_RUN은 발행 이력/상태를 쓰지 않는다.
- 이력 INSERT 실패 후 episode_assets를 published로 바꾸지 않는다. 상태 갱신은 날짜+에피소드 번호로 한정한다.
- 신규 품질 트랙 표식이 있는 에피소드는 기존 발행 경로에서 차단한다. 해당 표식은 `script_json._webtoon_quality` 또는 `quality_release`이며 생산자에 강제 연결하는 작업은 후속이다.

기존 SNS 경로의 다중 Actions 동시 실행, 파트 단위 부분 성공 재개, X/Telegram 공급자 timeout 대사는 이 수정만으로 해결되지 않는다. 전체 운영 경로를 원자적이라고 표시하면 안 된다. 운영 어댑터가 준비되기 전 신규 트랙을 live 발행하지 않는다.

## 실행

저장소 루트에서 Python 3.11 환경과 requirements.txt를 사용한다.

```bash
python -m scripts.run_webtoon_quality prepare --contract contract.json --root episode-root --output prepared.json
python -m scripts.run_webtoon_quality verify --manifest release.json --inputs inputs.json --report quality-report.json --root episode-root
python -m pytest tests/test_webtoon_quality.py -q
python -m pytest tests -q
ruff check . --line-length=100
```

`contract.json`의 최상위 키는 `evidence`, `editorial`, `claims`, `canon`, `script`, `calculation`이다. 각 타입은 engine/quality/contracts.py와 canon.py가 정의한다. prepare는 근거/서사/REF를 대조하고 입력 해시를 생성한다. 성공해도 상태는 `awaiting_images_and_human_review`이며 발행 승인이 아니다. 잘못된 계약은 HOLD와 종료 코드 1로 반환한다.

결과물은 `slides/P1.png`부터 `slides/P8.png`, 각각 `P{n}-preview-360.png`와 `P{n}-preview-390.png`를 사용한다. `compose_quality_panel`의 반환값에는 자동 geometry pass와 human_readability unverified가 분리되어 있다. 표시 문구에는 구조화 Claim이 필요하고 숫자 fact에는 정확한 quoted_value/unit/basis가 필요하다.

`prepare()` 출력 inputs에 `publication_parts`를 포함한 뒤 최종 content_hash를 계산하고 사람이 최종 결과물을 검수한다. 20항목 점수, 10개 역할, 모든 필수 검사, 결함을 QualityReport에 기록하고 동일 content_hash로 build_release를 호출한다. report는 선언된 평가의 완결성과 일관성을 검증하며 판정의 진실성을 대신 보장하지 않는다.

`generate_bounded`는 provider 콜백이 정확히 한 번 요청하고 `(image_bytes, actual_cost_usd)`를 반환하는 계약이다. 기존 tenacity 래퍼를 직접 연결하면 숨은 재시도로 횟수 상한을 깨므로 금지한다. 성공한 파일을 재사용할 때 승인 해시를 대조해야 하며 이 함수는 이미 존재하는 출력을 덮어쓰지 않는다. timeout/프로세스 중단 예약은 과금 내역 확인 후 `ledger.settle`로 정산해야 한다. 모든 비용은 provider에서 보고한 실제 값으로 기록하며 실제값이 예약값을 넘으면 이후 상한 예약이 차단된다. 예약값 자체가 공급자 최종 비용의 상한이라는 보장은 없다.

`publish_pilot`에는 네트워크 없는 모의 sender만 주입한다. 전송 payload도 inputs의 publication_parts와 같아야 한다. 성공 파트는 재전송하지 않는다. sending/unknown 파트는 reviewer와 proof를 넣은 reconcile 후에만 재개한다. 이는 운영 승인 또는 실제 SNS 발행 수단이 아니다.

## 검증과 운영 전 조건

신규 테스트 58개: 근거/인과/숫자/카논/서사 위반, hash 변경, 합성 표시 제거, 미검수 QC, 모바일 넘침/보호영역, 비용 예약 경쟁·재시작·월 경계, unknown 과금, 부분 발행·대사·fencing, CLI, 기존 발행 DRY_RUN/실패/에피소드 선택/이력 정합성, Gemini 필수 REF 보존을 검증한다. 모든 외부 호출은 mock 또는 주입된 모의 콜백이며 유료 생성과 운영 DB/SNS 변경은 수행하지 않았다.

최종 전체 테스트는 Python 3.11.16에서 **1,014 passed (53.67초)**, Ruff(`--line-length=100`)와 `git diff --check`도 통과했다. 운영 전에는 실제 거래 캘린더와 근거 어댑터, 단일 호출 SDK 연결, PostgreSQL 원자 claim/예산 어댑터, 공급자 대사, 권한 있는 QC 승인, 실제 미국 영어 편집과 12편 이미지·모바일 파일럿 검수를 완료해야 한다.

노션 최신화는 연결 API가 HTTP 500 `Cross-cell memcached access is not allowed`를 반환해 수행하지 못했다. 이 문서는 노션 반영 가능한 개발 상태 기록이다.
