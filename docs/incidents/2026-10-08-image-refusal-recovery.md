# 2026-10-08 이미지 생성 중단 및 복구 회고

상태: **복구 완료 · 정상 종료**.

대상 회차: `ICG-2026-10-08-001`. 2026-10-08 07:29:58 KST 사용자가 “복구완료. 정상종료”로 결과를 확인했다. 이 기록의 종료 근거는 사용자 확인이며, 성공 실행 ID·최종 이미지의 시각적 품질·조립 및 게시 완료 여부는 별도로 확인하지 않았다.

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
| 실제 복구 정상 종료 | 2026-10-08 07:29:58 KST 사용자 확인 |

재시도는 무조건 같은 입력을 반복하는 방식이 아니라, 비용과 결과가 정산된 거절에 대해서만 검토된 다음 입력으로 진행해야 한다. 성공 이미지와 원장을 보존하면 부분 실패 이후에도 중복 비용 없이 이어서 생성할 수 있다.

워크플로 변경은 YAML 파싱뿐 아니라 GitHub Actions 컨텍스트 유효성도 검증해야 한다. 이번에는 job env의 허용 컨텍스트 회귀 검사와 실제 경로 초기화 실행 검사를 추가했다. 향후 변경에서도 actionlint 검사를 수행한다. 공급자 입력과 거절 진단은 runner 종료 후에도 확인할 수 있도록 서버 전용 저장소에 남긴다.

실행 입력과 중단 대응은 [복구 운영 가이드](../webtoon-quality/image-resume-operations-20261008.md)를 참고한다.
