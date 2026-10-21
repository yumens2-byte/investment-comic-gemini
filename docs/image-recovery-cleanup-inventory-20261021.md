# 이미지 복구 일회성 파일 정리 후보 및 삭제 선행조건

작성일: 2026-10-21 (KST)  
대상: `yumens2-byte/investment-comic-gemini`  
조사 기준 운영 SHA: `a4c0910a08c52cfe9b7ad1f3456e03479d2397e7`  
상태: **목록·분석 완료, 실제 삭제 없음. 운영반영 전 검토 자료.**

## 결론

조사 시점 운영 브랜치에는 workflow YAML 28개가 있다. 그중 날짜·회차·원본 실행을 고정한 이미지 복구용 일회성 workflow는 `reviewed_image_recovery_20261021.yml` 1개다.
이에 결합된 helper·요청 JSON 2개를 함께 대체하는 것이 1차 정리 범위다.
관련 테스트 1개는 공통 모듈 테스트로 기능을 이관한 뒤 제거·전환할 수 있다.

이름이 beta·probe·recovery라는 이유만으로 나머지를 불필요한 일회성 파일로 분류하지 않았다.
이들은 변경 경로에 따른 지속 회귀, 운영 읽기 점검, 수동 유료 canary, 장애 알림 등 서로 다른 역할을 갖는다.
즉시 삭제로 확정한 파일은 없으며, 아래 선행조건을 충족한 뒤 별도 정리 변경으로 처리한다.

## 조사 근거와 한계

- Git tree와 아래 파일은 기준 SHA를 명시하여 직접 읽었다.
- workflow 28개의 trigger와 실행 모듈을 확인했다.
- GitHub Actions 최근 100개 run을 조회했다. 최근 사례가 없다는 것은 미사용의 증거가 아니다.
- GitHub 코드 검색 결과 일부는 이전 `a44b562`를 반환했다. 핵심 일회성 helper·요청·테스트의 실제 참조는 기준 SHA 직접 읽기로 재확인했다.
- 실행 파일 삭제, workflow 비활성화, 실행 이력 삭제, artifact 삭제, DB 변경은 수행하지 않았다.
- 라이브 episode 상태는 이 대화의 운영 검증 결과를 참고한 것으로, 이 목록 작업에서 별도 DB 조회로 재검증하지 않았다.

근거 링크:
- [기준 커밋](https://github.com/yumens2-byte/investment-comic-gemini/commit/a4c0910a08c52cfe9b7ad1f3456e03479d2397e7)
- [원본 실패 run 39489073022](https://github.com/yumens2-byte/investment-comic-gemini/actions/runs/39489073022)
- [복구 전 동일성 검사 중단 run 39493992835](https://github.com/yumens2-byte/investment-comic-gemini/actions/runs/39493992835)
- [복구 성공 run 39494505638](https://github.com/yumens2-byte/investment-comic-gemini/actions/runs/39494505638)

## 1차 삭제 후보 — 공통 복구 기능 대체 검증 후

| 경로 | 현재 역할·고정값 | 실제 참조 | 정리 조건 |
|---|---|---|---|
| `.github/workflows/reviewed_image_recovery_20261021.yml` | main push의 특정 요청 JSON 변경 또는 수동 실행. 날짜 2026-10-21, source run 39489073022, revision 2 고정 | `tests/test_reviewed_image_release.py`가 workflow 경로와 trigger를 직접 검사 | 공통 workflow가 검증·원본 복원·CAS 등록·이미지 실행·부분 artifact 보존을 대체하고 회귀 통과 후 삭제 |
| `scripts/recover_reviewed_images_release.py` | 특정 episode·revision·terminal receipt·원본 PNG·원본 hash에 고정된 실행 helper | 위 workflow와 `tests/test_reviewed_image_release.py`가 import·호출 | 공통 모듈에 source/PNG/정산/권한/비공개 저장/수동 Resume 표식 검증을 이관한 뒤 삭제 |
| `.github/icg-image-recovery/2026-10-21.json` | 해당 일회성 실행의 source hash·원본 artifact·P4 terminal·성공 PNG hash를 고정한 invocation manifest | 일회성 workflow의 push paths, helper의 REQUEST_PATH, 테스트 fixture | 앞 두 파일과 직접 참조를 함께 제거. 승인·실행 증거는 해당 Git 커밋과 run으로 보존 |
| `tests/test_reviewed_image_release.py` | 일회성 helper import, 날짜 고정 request 및 workflow 경로 읽기. 수동 Resume gate 회귀 포함 | 기존 CI의 `pytest tests/`가 자동 수집 | 단순 삭제 금지. source drift·PNG 변경·정산/등록 순서·private 파일 권한·manual gate·일회성 trigger 제한 검증을 공통 테스트로 모두 이관한 뒤 파일 제거 또는 범용화 |

위 workflow는 복구 성공 후에도 수동 실행 항목으로 남아 있지만, helper는 원본 revision 1과 미등록 receipt를 요구하므로 동일 회차 재실행은 차단한다.
일회성 UI 항목을 계속 유지하는 기능적 이점은 작으며, 공식 공통 workflow로 교체하는 우선순위가 높다.

## 증거·fixture — 삭제하지 않고 보존

| 경로·자원 | 보존 이유 |
|---|---|
| `docs/incidents/2026-10-21-reviewed-scenes.json` | 실제 복구에 사용한 장면 변경 증거. `tests/test_incident_oct21_recovery.py`와 incident 문서가 참조한다. 공통화 후 실행 입력은 새 승인 절차를 사용하되 이 파일은 증거/fixture로 유지한다. |
| `tests/test_incident_oct21_recovery.py` | 실제 canon REF와 카드·대본·cast 보존, 유료·DB 호출 없는 후보 준비 검증. 날짜가 있다고 일회성 테스트가 되는 것은 아니다. |
| `docs/incidents/2026-10-21-image-content-isolation.md` 및 기존 incident·verification 문서 | 장애 원인, 준비 범위, 복구 계약 및 한계의 감사·회고 근거다. 날짜 고정 실행 코드와 구분하여 보존한다. 운영 후 결과는 PR #134와 성공 run에 추가되어 있다. |
| `docs/sql/image-generation-*.sql`, 관련 migrations | 배포된 계약·설치 순서·권한·과금 안전장치의 근거. 파일 제거를 DB 함수 제거·ledger 초기화와 연결하지 않는다. |
| 기존 run·artifact·DB recovery receipts·generation calls | 성공 PNG, 최초 거절·비용·재처리 영수증의 이력이다. workflow 파일 정리 대상과 다르다. 삭제·예산 초기화 금지. |

조사 시 artifact API로 확인한 보존 상태:
- 원본 `episode-39489073022`: artifact ID `12294333956`, 만료 `2026-11-03T20:10:08Z`, 조사 시 expired=false.
- 복구 `episode-39494505638`: artifact ID `12295539747`, 만료 `2026-11-03T20:46:12Z`, 조사 시 expired=false.
- 이전 운영 검증에서 episode의 `artifact_run_id=39494505638`, `require_manual_resume=true`가 확인되었다. 이 포인터·표식은 일회성 파일 제거 후에도 유지해야 한다.
- workflow 파일 삭제와 GitHub artifact 삭제는 별개다. artifact의 현재 접근 및 retention을 확인하고, 장기 보존이 필요한 증거는 만료 전에 보존한다.

## beta·release probe 6개 — 현재 삭제하지 않고 통합 후보로 관리

| workflow | 실제 trigger·역할 | 관찰된 최근 실행·주의점 |
|---|---|---|
| `assembly_artifact_beta.yml` | main의 composer/Resume/beta helper 변경 + 수동. 실제 artifact를 복원해 로컬 조립 검증 | run 39493992996 성공. `scripts/prepare_assembly_beta.py`, `scripts/run_assembly_artifact_beta.py`, `tests/test_assembly_beta_source.py` 의존 |
| `generation_guard_beta.yml` | main의 engine/image/** 변경 + 수동. DB 예약·정산 장애·중복 호출 방어 검증 | run 39492741431 성공. **push에서도 실제 DB 테스트 scope 기록을 생성한다.** 유료 이미지 smoke는 수동 dispatch만 허용하므로 읽기 전용 테스트로 오분류하면 안 된다. `tests/test_generation_guard_beta.py`가 helper를 import |
| `operational_beta.yml` | 운영 metadata·설정·Notion/DB adapter 계약의 읽기 점검. 관련 경로 main push + 수동 | 최근 100개 run 표본에는 없음. `scripts/run_narrative_contract_beta.py`가 operational helper 사용, `tests/test_operational_beta.py` 의존 |
| `publish_dry_beta.yml` | publish/preflight 관련 변경 + 수동. 실발행 없이 readiness·불변성 확인 | run 39336467434 성공. `scripts/run_publish_dry_beta.py`를 기존 publish 전 검증 기능으로 보존 |
| `run_market_dry_beta.yml` | Run Market/preflight 관련 변경 + 수동. dry-run 계약 검증 | run 39493992891 성공. source 또는 workflow 변경 때마다 재사용되는 회귀이므로 날짜별 복구용 파일이 아님 |
| `sidestory_market_talk_release_probe.yml` | Market Talk 코드 변경 + 수동. 배포 DB·source·설정·Facebook Page GET 점검 | 최근 100개 run 표본에는 없음. 생성·발행 권한을 검증한 것으로 보고하지 않는 읽기 전용 release probe |

이 여섯 workflow는 향후 `Operational Validation` 같은 단일 workflow의 job 또는 reusable workflow로 통합할 수 있다.
다만 read-only/DB-write/paid-manual의 실행 권한과 secret 범위를 분리해야 한다.
공통 **이미지 복구** 기능이 이 검증을 자동으로 대체하지는 않으므로 현재 PR에서 삭제할 근거는 없다.

## 추가 확인 후 별도 정리할 후보

| 경로 | 확인된 문제·특성 | 권고 |
|---|---|---|
| `.github/workflows/sidestory_recovery_check.yml` | 재사용 가능한 date 입력이 있지만 default, TARGET_DATE fallback, concurrency fallback이 2026-10-15에 고정됨. 수동 + 해당 workflow/helper 변경 시 push. 읽기만 수행 | 날짜 기본값을 제거하거나 명시적 요청 필수로 일반화. Side schema·checkpoint·publish receipt 검사를 다루므로 ICG 이미지 공통화 완료만으로 삭제하지 않는다. |
| `sidestory/app/recovery_preflight.py` | 본 workflow 외에도 Side CLI의 `recovery_check` stage에서 사용. `sidestory/tests/test_recovery_preflight.py`가 unknown 과금·원본/retake scope·partial PNG·기발행 영수증 검증 | 유지. YAML wrapper를 정리하더라도 실제 recovery safety 모듈은 보존 |
| `.github/workflows/market_source_probe.yml` | 현재 source 수집 후 별도 checkout을 커밋 `105dc521059fd7169905103faebb90276dc73cf8`에 고정해 Side 계약 검증 | 해당 pin이 의도된 호환성 기준인지 확인 후 현행 계약 기반 validation으로 통합. 단순 미사용으로 삭제하지 않는다. helper `scripts/market_source_probe.py`와 `tests/test_market_source_probe.py`는 보존 |
| `.github/workflows/migrate_ref_images.yml`, `scripts/migrate_ref_images.py` | 과거 Notion 페이지·episode 목록에서 REF를 이식하고 canon SHA를 갱신하는 수동 도구. 신규 REF 운영과 별도 역할. 최근 100개 run 표본에는 없음 | 이식 완료·신규 canon 관리 경로·운영 참조를 확인한 뒤 YAML 제거/CLI archive 검토. 사용 이력 부족만으로 삭제 확정하지 않는다. |

## 공식 운영·CI·canary — 유지 18개

| 구분 | workflow |
|---|---|
| 핵심 CI | `ci.yml`, `sidestory_ci.yml`, `sidestory_market_talk_ci.yml` |
| 일일 ICG·조립·SNS | `run_market.yml`, `resume_episode.yml`, `publish_sns.yml` |
| 품질 승인·REF 관리 | `image_quality.yml`, `generate_ref_images.yml` |
| 영상·주간 | `run_video_trailer.yml`, `run_weekly_shorts.yml`, `publish_shorts.yml` |
| 감시·수동 canary | `notify_watchdog.yml`, `path_canary.yml` |
| Side·Market Talk 운영 | `sidestory_run.yml`, `sidestory_market_talk.yml`, `sidestory_market_talk_execute.yml`, `sidestory_market_talk_watch.yml`, `sidestory_market_talk_watchdog.yml` |

`notify_watchdog.yml`은 workflow **표시 이름**으로 완료 이벤트를 구독한다. 공식화로 이름을 바꾸면 감시 대상 목록과 관련 테스트도 함께 확인해야 한다.
`sidestory_market_talk_execute.yml`은 workflow_call로 운영·watchdog에서 재사용하는 공통 실행부이므로 중복 YAML로 취급하지 않는다.
`path_canary.yml`은 기본 dry-run, 명시적 수동 실행일 때 최대 한 패널의 유료 검증을 수행하는 공식 검증 경로다.

## 정리 순서와 완료 기준

1. 공통 workflow/CLI가 날짜·episode·revision·원본 artifact·source hash·REF/PNG·terminal 정산·CAS·비용 한도를 처리하도록 구현한다.
2. 실제 source hash는 Python이 읽은 원본 타입으로 계산한다. 외부 JSON 전달에서 `100.0→100`으로 바뀐 값을 기준 원본 hash로 사용하지 않는다.
3. 일회성 테스트의 유효한 안전 검증을 공통 테스트로 이관하고, 전체 CI에서 새 공통 모듈과 기존 정상 경로를 검증한다.
4. 새 workflow가 원본·부분 PNG를 기존 `episode-{run_id}` 규약으로 올리고 수동 Resume 표식을 유지하는지 확인한다. private source·candidate는 artifact 업로드 대상에서 제외한다.
5. 기존 core CLI·helper·SQL 계약·watchdog 참조와 현재 artifact 포인터를 유지한 상태에서 목록의 일회성 runtime 3개와 대체된 테스트를 함께 정리한다. 사고 문서와 회귀 fixture는 남긴다.
6. 삭제 변경에서 남은 import·Path·trigger 참조를 전수 점검하고 CI를 통과시킨다. 과거 run·artifact·DB ledger를 삭제하는 작업은 포함하지 않는다.

현재 단계에서는 **공통화 상세설계·구현·테스트와 삭제 목록만 준비**하며, main 반영·실제 파일 삭제는 수행하지 않는다.
