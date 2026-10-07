# 2026-10-08 이미지 생성 중단 및 복구 회고

상태: **이미지 복구·조립·X/Telegram 발행 완료 · 정상 종료**.

대상 회차: `ICG-2026-10-08-001`. 2026-10-08 07:29:58 KST 사용자 복구 확인 이후, GitHub Actions 작업 단계와 실제 실행 로그를 점검했다. 이미지 6개 성공, 슬라이드 8개 조립, X 스레드 4개 및 Telegram 슬라이드 8개 발행, 발행 확정 RPC 성공을 확인했다. 이번 회차의 복구와 이미지 SNS 발행은 종료했다. 최종 이미지의 시각적 품질, 게시물의 현재 노출 상태, 운영 DB의 현재 상태를 별도 직접 조회한 결과는 포함하지 않는다.

## 발생 원인과 영향

초기 [Run Market 37690049331](https://github.com/yumens2-byte/investment-comic-gemini/actions/runs/37690049331)은 `narrative_done` 대본을 복원한 뒤 P1~P3 이미지 생성에 성공했다. P4 요청은 HTTP 200이었지만 Gemini가 `FinishReason.PROHIBITED_CONTENT`를 반환해 이미지가 없었다. 정산 원장이 terminal 상태가 되었고 `GenerationHold`로 파이프라인이 exit code 1로 중단됐다. HTTP 성공과 이미지 생성 성공은 구분해야 한다.

대본의 최종 결정은 `NO_BATTLE / OBSERVATION`인데 P4 action에는 주먹으로 홀로그램을 가격하는 동작이 있었다. P2/P3에도 관찰 모드와 충돌하는 표현이 있었다. 이는 사전 검토에서 발견한 모순이며, 공급자가 어떤 문구 때문에 거절했는지는 확인되지 않았다. 당시 최종 프롬프트·상세 거절 진단이 저장되지 않아 원인 추적에 추가 복원이 필요했다.

P1~P3 성공 원본은 artifact에 남았고, P5/P6는 호출되지 않았다. P7/P8은 TEXT_CARD/DISCLAIMER로 이미지 공급자 호출 대상이 아니다. 복구 준비 시 기존 기록 비용은 총 USD 0.118344였다. 이는 **복구 전 비용**이며 최종 복구 비용으로 해석하지 않는다.

## 조치 및 복구

- [PR #105](https://github.com/yumens2-byte/investment-comic-gemini/pull/105): 관찰 모드 action 사전 검사, 검토된 입력에 대한 최대 재시도 2회, 지속 원장 예약·정산, 서버 전용 입력/거절 진단 저장을 구현하고 main에 반영했다.
- 운영 DB에 재시도 SQL을 적용하고 revision 2 복구 대본, 6개 유료 패널의 입력·재시도 계획, P4 비용 확인 recovery receipt를 등록했다. 기존 실패 기록과 비용은 삭제하거나 초기화하지 않았다.
- 당시 Notion 내용으로 P1~P4 입력을 재구성해 운영 원장의 지문과 일치를 확인했다. artifact P1~P3 PNG SHA256도 확인하고, 추가 생성 없이 재사용하도록 준비했다.
- P2/P3 action 표현을 관찰 모드에 맞게 정리하되 이미 생성된 원본 이미지와 공급자 입력 기록은 유지했다. P4의 새 입력은 데이터 화면을 조용히 관찰하는 비전투 장면으로 수정했다.
- P4는 기존 1회 호출을 포함한 총 3회 한도로 추가 호출 최대 2회, P5/P6는 첫 호출과 재시도 2회로 제한했다. 타임아웃·비용 불명·정산 또는 진단 저장 실패는 자동 재시도 대상에서 제외했다.

운영 반영 후 [실행 37695695960](https://github.com/yumens2-byte/investment-comic-gemini/actions/runs/37695695960/workflow)은 runner 시작 전에 워크플로 검증에서 거부됐다. 구현 과정에서 job 수준 `env`에 `${{ runner.temp }}`를 넣은 설정 오류였다. YAML 파싱 테스트는 이 GitHub Actions 표현식 제약을 검출하지 못했다.

[PR #106](https://github.com/yumens2-byte/investment-comic-gemini/pull/106)에서 진단 경로 초기화를 첫 실행 단계로 이동하고 `$RUNNER_TEMP`와 `$GITHUB_ENV`를 사용하도록 수정했다. main 반영 커밋은 `09d9d8954e3fcc60e44469d1f08628620f81838a`다. 이후 사용자가 복구 실행 정상 종료를 확인해 사고를 종료했다.

## 검증과 교훈

| 검증 | 확인 결과 |
|---|---|
| Python 3.11 전체 테스트, 재시도 구현 단계 | 1,611개 통과 |
| PGlite SQL 통합 검사 | 11개 시나리오 통과 |
| 격리된 운영 PostgreSQL 17.6 동시 예약 검사 | 예약 1개·차단 7개, 검증 9개 통과 |
| 복구 준비 시 서비스 권한 cursor 검사 | 유료 패널 6개 통과 |
| 워크플로 수정 회귀 테스트 | 14개 통과 |
| actionlint 1.7.12 | 기존 오류 재현, 수정본 워크플로 검사 통과; shellcheck/pyflakes는 비활성화 |
| 워크플로 수정 브랜치 CI | [37695977992](https://github.com/yumens2-byte/investment-comic-gemini/actions/runs/37695977992) success |
| 실제 복구 정상 종료 | Run Market 37696333937 STEP 6 성공, 6/6 패널·fallback 0개 |
| 조립 정상 종료 | Resume Episode 37697228961 STEP 7 성공, 슬라이드 8개·slides_run_id DB 저장 |
| 실제 운영 발행 | Publish SNS 37697772330, dry_run=False, X 4개 및 Telegram 8개 슬라이드 |
| 발행 확정 | finalize_episode_publication HTTP 200 및 후속 DB 저장 성공, 발행 완료 로그 |

재시도는 무조건 같은 입력을 반복하는 방식이 아니라, 비용과 결과가 정산된 거절에 대해서만 검토된 다음 입력으로 진행해야 한다. 성공 이미지와 원장을 보존하면 부분 실패 이후에도 중복 비용 없이 이어서 생성할 수 있다.

워크플로 변경은 YAML 파싱뿐 아니라 GitHub Actions 컨텍스트 유효성도 검증해야 한다. 이번에는 job env의 허용 컨텍스트 회귀 검사와 실제 경로 초기화 실행 검사를 추가했다. 향후 변경에서도 actionlint 검사를 수행한다. 공급자 입력과 거절 진단은 runner 종료 후에도 확인할 수 있도록 서버 전용 저장소에 남긴다.

실행 입력과 중단 대응은 [복구 운영 가이드](../webtoon-quality/image-resume-operations-20261008.md)를 참고한다.

## 오늘의 실행 결과와 시간표

시각은 모두 2026-10-08 KST다. GitHub 로그의 UTC에 9시간을 더해 정리했다.

| 시각 | 작업 및 확인 결과 | 근거 |
|---|---|---|
| 06:35:13 | P4 콘텐츠 거절, GenerationHold로 중단 | [초기 실행 37690049331](https://github.com/yumens2-byte/investment-comic-gemini/actions/runs/37690049331) |
| 07:21:52 | 워크플로 표현식 오류로 실행 시작 실패 | [실행 37695695960](https://github.com/yumens2-byte/investment-comic-gemini/actions/runs/37695695960/workflow) |
| 07:27:49 | revision 2 이미지 복구 실행 시작 | [Run Market 37696333937](https://github.com/yumens2-byte/investment-comic-gemini/actions/runs/37696333937) |
| 07:29:31~38 | 6/6 패널 성공·fallback 0개, 이미지 정보와 artifact_run_id 저장, 파이프라인 완료 | 동일 실행 로그 |
| 07:36:12 | 후속 조립 실행 시작 | [Resume Episode 37697228961](https://github.com/yumens2-byte/investment-comic-gemini/actions/runs/37697228961) |
| 07:37:21~24 | S1~S8 조립 완료, slides_run_id=37697228961 DB 저장 | 동일 실행 로그 |
| 07:41:30 | SNS 발행 실행 시작 | [Publish SNS 37697772330](https://github.com/yumens2-byte/investment-comic-gemini/actions/runs/37697772330) |
| 07:46:31 | channels=['x', 'telegram'], dry_run=False 확인 | 동일 실행 로그 |
| 07:46:37~07:47:15 | X T1~T4 게시 및 건별 전달 기록 저장 성공 | 동일 실행 로그 |
| 07:47:21 | Telegram 슬라이드 1~8 전송·전달 기록 저장 성공 | 동일 실행 로그 |
| 07:47:23~26 | 발행 확정 RPC·후속 DB 저장 및 발행 완료, workflow success | 동일 실행 로그 |

X 게시 ID는 T1 `2107965848023368012`, T2 `2107965903698559079`, T3 `2107965957729669480`, T4 `2107966005192364203`이다. [첫 게시물](https://x.com/i/web/status/2107965848023368012)에서 스레드를 확인할 수 있다.

이미지 복구 실행의 실제 Gemini HTTP 호출은 3건으로, P1~P3는 추가 생성 없이 재사용하고 P4~P6를 생성했다. 생성 완료 로그의 비용은 USD 0.1178로 표시됐다. 이는 이번 복구 실행에 표시된 값이며, 기존 실패 비용까지 합산한 최종 원장 총비용을 직접 조회한 결과는 아니다.

SNS 사전 검사에서는 `status=ready`, 차단 사유·readiness issues·content QC warnings가 빈 목록이었다. X 4개 게시와 Telegram 전송 완료 뒤 발행 확정 RPC가 HTTP 200을 반환하고 후속 저장이 성공했다. 전투씬 영상은 `video_asset_missing`으로 생략됐다. 영상 생성·발행 완료로 기록하지 않는다.

## 잔여 작업과 운영 전환 기준

| 항목 | 현재 상태 | 후속 조치 |
|---|---|---|
| 이번 회차 이미지 복구·조립·SNS 발행 | 완료 | 재실행 불필요. 게시물 및 알림 모니터링 |
| 정기 실행의 검토 입력 재시도 | 준비 잔여 | run_market.yml은 `ICG_IMAGE_RETRY_V2_ENABLED: inputs.image_retry_v2 || 'false'`이므로 schedule에서는 새 재시도 기능이 기본 OFF다. 향후 회차별 검토 입력·계획 등록과 활성화 경로 설계 필요 |
| episode_assets 접근 권한 | 별도 보안 검토 잔여 | 앞선 점검에서 RLS 비활성화·anon 조회/수정 권한이 기록됐다. 개선 적용 및 재검증 필요. 이번 발행 점검에서 권한을 재조회하거나 수정하지 않음 |
| 영상 | 자산 없음으로 생략 | 이미지 SNS 발행 완료와 분리하여 관리 |

이번 사고의 복구 완료와 전체 자동화 고도화 완료는 구분한다. 이번 회차는 운영 모니터링으로 전환하되, 정기 재시도 준비와 권한 개선을 완료 처리하지 않는다.

## 이번 작업의 개선점

- 최초 장애는 공급자 콘텐츠 거절이며, 상세 거절 근거가 부족해 특정 문구를 원인으로 확정할 수 없었다. 공급자 입력·상세 종료 사유를 제한된 저장 경로에 보존하도록 개선했다.
- 복구에서는 성공 이미지·원장·기존 비용을 보존했다. 재시작이 호출 한도를 초기화하지 않도록 지속 원장으로 통제했다.
- 개발 중 추가한 job env의 runner.temp 오류는 변경 작업에서 발생한 별도 결함이다. YAML 파싱과 Python 테스트만으로 워크플로 실행 가능성을 보장할 수 없으며, actionlint와 컨텍스트 회귀 검증이 필요하다.
- 실행 화면의 success만으로 전체 완료를 판단하지 않았다. 실제 대상 회차, dry_run=False, 건별 게시 ID·전달 기록, 조립 및 발행 확정 로그를 확인해 종료 근거를 보강했다.
- 재시도 코드를 main에 반영한 것과 정기 실행에서 활성화한 것은 다르다. 배포 검증에는 실제 schedule의 환경 변수와 입력 계획 준비 여부를 포함해야 한다.
