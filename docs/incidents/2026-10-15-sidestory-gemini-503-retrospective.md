# 2026-10-15 Sidestory 이미지 생성 503 장애 및 운영 전환 회고

- **회고 기록일:** 2026-10-16 (KST)
- **대상:** `🌐 Sidestory Run (Facebook side canon)`, `SIDE-2026-10-15-01`
- **최종 의사결정:** **과거 실패 회차는 복구하지 않는다. 다음 정기 동작일에 신규 회차의 정상 실행을 모니터링한다.**
- **종료 구분:** 과거 회차 *미복구·보존* / 방어코드 *배포 및 진단 검증 완료* / 정기 실운영 검증 *예정*
- **원본 장애 실행:** [GitHub Actions #38689330263](https://github.com/yumens2-byte/investment-comic-gemini/actions/runs/38689330263)
- **추적 이슈:** [#127](https://github.com/yumens2-byte/investment-comic-gemini/issues/127)

## 1. 발생 현상 및 확인된 원인

2026-10-15 14:55:48 KST경 `gemini-2.5-flash-image`의 P1 이미지 생성 요청이 **HTTP 503 UNAVAILABLE** (`The service is currently unavailable`)로 종료되었다. 공급자가 일시적으로 이용 불가 응답을 반환한 것이 이번 장애의 **직접 원인**이다. 서버가 503을 반환한 구체적인 내부 사유는 확인되지 않았다.

Sidestory는 `echo` 및 `narrative` 단계를 정상 완료했고 이미지 생성 P1에서 중단되었다. 이미지 생성 결과·비용이 확정되지 않아 지속 원장의 `unknown`과 에피소드의 `hold`를 유지하는 안전장치가 동작했다. **원고 완료를 전체 파이프라인/발행 완료로 해석하지 않는다.**

| 검증 항목 | 확인 결과 |
|---|---|
| 에피소드 | `SIDE-2026-10-15-01` |
| 에피소드 DB 상태 | `hold` |
| 원고 `script_json` | 존재 |
| 패널 `panels_json` | 없음 / 성공 확정 패널 0건 |
| 슬라이드 `slides_json` | 없음 |
| 이미지 P1 Ledger | `unknown`, `output_hash=NULL` |
| Ledger의 `cost` | USD 0.10 (**예약·한도 관리 값**, 실제 청구액 아님) |
| 실제 Gemini 과금 | **미확정**; 청구/사용량 증거 없음 |
| Facebook 실발행 내역 | 없음 |

증거는 원본 실행 로그, artifact **11951056291**, `icg_side.side_episodes`, `icg_side.image_generation_calls`, `icg_side.side_publications`, `side_run_logs` 및 이미지 진단 `inputs` 기록을 대조한 결과다. HTTP 503을 확인했다고 해서 특정 요청의 실제 청구액까지 0으로 확정되는 것은 아니다.

## 2. 개선·반영 이력

| 변경 | 결과 및 링크 |
|---|---|
| Gemini 공급자 오류와 Ledger 정산 오류 분리·진단 정보 보존 | [PR #126](https://github.com/yumens2-byte/investment-comic-gemini/pull/126), Main 병합 |
| 미확정 원장 HOLD 해제 차단, 패널별 SG-8·SHA256 체크포인트, 기존 성공 파일 재사용 및 복구 테스트 | [PR #125](https://github.com/yumens2-byte/investment-comic-gemini/pull/125), Main 병합 |
| 결제·재시도·발행 권한 없는 읽기 전용 `recovery_check` CLI와 전용 Actions 점검 작업 | [PR #128](https://github.com/yumens2-byte/investment-comic-gemini/pull/128), Main 병합 |

최종 반영 당시 Main 커밋: `90f08d8f2c8ead55112cc9c2ef0823b2e5bce0c2`.

PR #128 병합 전 CI 11개 항목이 통과했고, 병합 후 Main에서 확인한 7개 검사도 전부 통과했다. **CI 통과는 실시간 이미지 공급자 호출이나 Facebook 발행 완료를 뜻하지 않는다.**

## 3. 운영 베타 진단

- [읽기 전용 Recovery Check #38825669789](https://github.com/yumens2-byte/investment-comic-gemini/actions/runs/38825669789): 워크플로 실행 **SUCCESS**.
- 실제 진단 결과: `status=BLOCKED_LEDGER_RECONCILIATION`, `episode_status=hold`, `has_script=true`, `has_slides=false`, `has_live_publication=false`.
- P1은 `unknown`, 검증 완료 체크포인트 0개. `may_retry_paid=false`, `may_publish=false` 확인.
- 진단은 **읽기 전용으로 완료**되었다. 과금·HOLD 해제·이미지 재생성·Facebook 발행을 수행하거나 완료 처리하지 않았다.

## 4. 사용자 최종 결정 — 과거 회차 미복구

2026-10-16 사용자는 **“점검 완료했으면 복구는 안하고 다음 정기 동작일에 모니터링 하겠다”**고 결정했다.

이에 따라 다음 운영 방침을 확정한다.

1. **`SIDE-2026-10-15-01`은 복구 대상에서 제외**한다. 과거 회차를 위한 `retry_hold`, `auto`, `p1`, 원본 Actions `Re-run jobs`, 이미지 재호출 및 Facebook 소급 발행을 실행하지 않는다.
2. **Ledger `unknown`과 에피소드 `hold`를 임의 수정·삭제·정산하지 않는다.** 실제 청구 여부가 확인되지 않은 기록과 원본 로그/아티팩트는 감사 증거로 보존한다. USD 0.10을 실제 비용으로 확정하지 않는다.
3. 이번 회차를 **발행 성공 또는 기술적 복구 완료로 표시하지 않는다.** 운영 조치 단계만 “미복구 결정에 의한 종료”로 기록한다.
4. 다음 정기 실행에서 **새로운 날짜의 신규 회차** 정상 동작을 검증한다. 10월 15일 실패 회차에 대한 재개·백필 작업은 하지 않는다.
5. 차후 과거 회차 재처리가 다시 필요해질 경우, 이번 결정과 별개의 명시적 승인 및 비용·증거 검증이 필요하다.

## 5. 다음 정기 실행 모니터링 체크리스트

현재 `.github/workflows/sidestory_run.yml`의 스케줄은 **매주 화·목 10:17 KST** (`17 1 * * 2,4`)이다. 회고 작성일 이후 다음 예정 슬롯은 **2026-10-20(화) 10:17 KST**다. 단, GitHub Actions 스케줄 작업은 지연될 수 있고, 해당 job 실행에는 repository variable `SIDESTORY_SCHEDULE_ENABLED=true`가 필요하다. 변수의 현재 활성화 여부는 여기서 검증하지 않았다.

- [ ] GitHub Actions가 신규 날짜 `2026-10-20` 슬롯으로 실제 시작했는지 확인 (미실행·지연·건너뜀을 성공으로 판단하지 않음).
- [ ] 실행 SHA가 수정 Main 계열인지 확인하고 `echo → narrative → image → assembly → publish → verify` 단계 결과 구분.
- [ ] 이미지 6개·SG-8·체크포인트·슬라이드 8개 생성 여부 및 Ledger 상태·비용 검증.
- [ ] Facebook은 `dry_run=false`와 공급자 게시 ID, `icg_side.side_publications`의 실제 발행 영수증을 대조. 워크플로 `SUCCESS`만으로 발행 성공 단정 금지.
- [ ] 신규 에피소드에 HOLD, UNKNOWN, 중복 과금/중복 발행, 기존 10월 15일 상태 전이 또는 다른 회차 영향이 없는지 확인.
- [ ] 결과를 별도 운영 모니터링 기록에 추가하고 이상 발생 시 신규 Incident로 추적.

관련 운영 가이드: [Sidestory image HOLD runbook](../../sidestory/docs/image-hold-recovery-20261016.md).

## 6. 교훈 및 종료 판단

- **직접 원인과 진단 불가능 요소를 구분한다.** HTTP 503은 확인되나 내부 공급자 장애 원인과 실제 과금 결과는 미확정이다.
- **운영 안정성과 과거 미복구 차수를 분리한다.** 방어코드 배포·회귀 테스트·읽기 전용 점검 성공은 해당 실패 회차의 발행 성공을 의미하지 않는다.
- **불명확한 비용에는 보수적으로 대응한다.** 예약금액, 최종 청구금액, 공급자 처리 성공 증거를 혼동하거나 UNKNOWN을 실패로 치환해 우회하지 않는다.
- **회고의 종료 기준은 의사결정까지 포함한다.** “실패 회차 미복구·기록 보존·다음 정기 실행 모니터링”은 성공적 재발행과 다른 종류의 정상적인 운영 결정이다.

**최종 상태:** 코드 개선·진단 검증 완료 / 2026-10-15 회차 미복구 유지 / 2026-10-20 정기 실행 모니터링 전환.
