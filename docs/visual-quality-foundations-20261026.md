# 시각 품질 개선: 상세분석 및 1차 개발 결과

- 작성일: 2026-10-26 KST
- 기준 커밋: `24592efccee1de3430cd30095cf46c6679f69a1f`
- 개발 브랜치: `feat/visual-quality-foundations`
- 설계 기준: `ICG_Visual_Quality_Detailed_Design_20261026.md` v1.1
- 판정: **입력 경로 기반 보완 구현·로컬 회귀 통과. 전체 고도화 구현 및 운영 적용 미완료.**

## 1. 상세분석 결과와 구현 경계

문제는 이미지 생성 API의 성공 여부와 실제 시각 품질을 같은 결과로 취급한 데 있다.
현재 대본·REF·프롬프트·조립·검수·발행 사이에는 별도 계약이 필요하다.
이번 변경은 DB 승인 계약 없이 revision 하한을 완화하거나 신규 품질 모드를
켜는 방식 대신, 기존 입력의 보존과 신규 입력의 검증을 먼저 보완한다.

| 확인 사항 | 코드에서 확인한 원인 | 이번 구현 |
|---|---|---|
| 고정 입력과 구형 performance 설정 충돌 | `step_image`가 reviewed 입력 확인 전에 구형 compiler를 실행 | reviewed 키가 있으면 구형 compiler 우회. 잘못된 bundle도 live 입력으로 대체하지 않음 |
| 스타일·캐논의 충돌 지시 | renderer가 scene만 검증하고 이후 외부 block을 결합 | 결합 직전 별도 검증. 접촉·정지·전신·표면 문자 충돌은 HOLD |
| 캐릭터의 명시 form 미반영 | ID-only REF 로더가 default form 선택 | 신규 v2 builder와 quality prepare에 form-aware strict 로더 연결 |
| 감사 메모의 오탐 | provider에 전달하지 않는 review evidence까지 긍정 동작 검사 | 감사 메모는 모델 검증·기존 해시 대상으로 유지하고 동작 검사에서만 제외 |
| CI 재실행 번호 의존 | summary는 attempt 1인데 실행 환경 값은 명시하지 않음 | attempt 1·5 각각 일치 조건 검증, 불일치 시 pointer 갱신 금지 검사 |
| DB 쓰기 실패 테스트의 거짓 통과 가능성 | 실제 patch 호출 없이 원래 HOLD만 확인해도 통과 | patch가 실제 한 번 호출됐음을 확인 |
| 루트 Shorts 테스트의 오래된 계약 | 정규 `tests/`와 중복이며 2컷 거절·옛 캐논 fixture가 남음 | 두 중복 파일 제거, 정규 테스트 유지 |

## 2. 구현 계약

### 고정 입력 우선

`_reviewed_image_inputs` 키가 있으면 구형 performance compiler에 진입하지 않는다.
bundle이 잘못됐거나 빈 값이면 기존 reviewed validator가 거절한다.
고정 입력의 실제 prompt·REF·fingerprint를 live Notion 자료로 다시 만들지 않는다.
revision 1의 일반 허용은 이번 변경에 포함하지 않는다.

### 신규 REF 선택

`get_ref_bindings_for_panel`은 다음 값을 반환한다.

```json
{"char_id":"hero","form":"form1","ref":"assets/characters/hero_form1.png","sha256":"<64 hex>"}
```

- 명시 form은 정확히 그 항목을 사용한다. 생략한 form만 캐논에 등록된 default를 사용한다.
- 미등록 form·중복 cast·미승인 해시·파일 부재·파일 변경은 중단한다.
- 캐논 디렉터리 밖 경로, traversal 및 외부 파일로 향하는 symlink를 거절한다.
- 신규 quality prepare는 `ref_binding_version=canon-form-1`과 패널별 bindings를 고정한다.
- reviewed validator는 해당 버전의 bindings와 현재 승인된 form·파일을 대조한다.
- 버전 표시가 없는 과거 고정 입력은 기존 ID-only 검증을 유지한다.
  과거 성공 입력을 새 로더로 바꾸거나 재생성하지 않는다.

### 렌더 문구 검사

scene 검증 후 들어오는 CANON/STYLE도 검사한다. 입력에 충돌이 있으면
금지문 하나를 뒤에 추가하는 것으로 해결하지 않고, provider 호출 전에 HOLD한다.
정확히 제한된 무문자 금지문은 허용하되, `No`로 시작하는 임의 문장을
검사 제외로 취급하지 않는다.

이는 보수적인 문구 검사다. 자연어의 모든 모순을 판정하거나 실제 그림의
동작·문자·캐논을 검수하는 기능은 아니다. 긍정 동작이 들어 있는 기존
STYLE/CANON 자료는 새 후보 준비 과정에서 HOLD될 수 있다.
역할별 스타일·외형 투영과 제외 내역 보고의 전체 구현은 후속 작업이다.
이미 고정한 프롬프트는 이 renderer로 다시 만들지 않는다.

### 감사 정보

`review_evidence`의 strict model/길이 검증과 scene digest는 유지한다.
이 필드는 provider 프롬프트에 넣지 않으므로 긍정 동작 검사 대상에서만 제외한다.
실제 action·setting·motion·사실·소품 등의 검사는 유지한다.

## 3. 리뷰 항목별 상태

| ID | 상태 | 남은 조건 |
|---|---|---|
| R01 최초 revision 1 | 미구현 | 원자적 입력 확정 RPC·DB 정책 영수증·예약 전 fingerprint 검증 |
| R02 정책 무결성 | 미구현 | DB 권위 정책·별도 digest·assembly manifest v2 및 검수 현재성 |
| R03 여러 생성 run 출처 | 미구현 | 패널별 생성 영수증·컨테이너 출처 분리 및 SQL 계약 변경 |
| R04 v2 부분 거절 복구 | 미구현 | v2 전용 복구 및 보호 PNG/spec/fingerprint 유지 검사 |
| R05 발행 동시성 | 미구현 | 검수·선택·claim의 원자적 snapshot, 발행 중 변경 거절 |
| R06 최종 지시 검사 | 부분 구현 | 확정 충돌 사례 차단 완료. 역할별 투영·전체 서사/캐논 결합은 남음 |
| R07 form REF | 부분 구현 | 신규 builder/prepare/reviewed 경로 연결. v2 복구 경로는 R04와 함께 구현 필요 |
| R08 선택본의 실제 연출 | 미구현 | 패널별 effective render manifest와 선택·조립·검수 연결 |
| R09 감사 메모 오탐 | 구현·검증 | 감사 메모 무결성 유지, provider 미전달 및 실제 동작 제한 유지 확인 |

따라서 기존 설계의 36개 수용 시나리오 전체가 통과했다고 판정하지 않는다.
신규 enforce 경로를 켜지 않으며 DB 계약이 연결되기 전에는 배포 준비 완료로 보지 않는다.

## 4. 검증 결과

| 범위 | 결과 |
|---|---|
| 최초 관련 집중 검사 | 112 통과 |
| 추가 문구/실제 builder 경로 검사 후 전체 정규 회귀 | **1,920 통과, 실패·오류·스킵 0** |
| 저장소 ruff | PASS |
| `git diff --check` | PASS |
| 운영 DB/격리 SQL 변경 검사 | 이번 변경에 SQL이 없으며 실행하지 않음 |
| GitHub CI | 이번 브랜치에서는 아직 실행하지 않음 |
| 실제 생성·시각 품질 파일럿 | 미실행 |

전체 회귀 실행:

```bash
DRY_RUN=true GITHUB_RUN_ATTEMPT=5 ICG_CJK_FONT_PATH=<NotoSansCJK-Bold.ttc> \
  <isolated-python> -m pytest tests/ -q --tb=short --junitxml=<result.xml>
ruff check . --line-length=100
git diff --check
```

초기 전체 실행은 환경 부재로 7건 실패했다. 한글 폰트 부재 4건과
로컬 SOCKS 프록시 초기화 의존성 부재 3건이다. 폰트와 로컬 테스트 환경의
`socksio`를 준비한 뒤 전체 회귀를 재실행했다. 실패를 숨기기 위해 assertion을
완화하거나 운영 의존성 파일을 바꾸지 않았다.

루트 테스트와 정규 테스트를 함수명·본문으로 대조했다.
제거한 Shorts media 파일의 테스트는 모두 정규 파일에 있으며,
Shorts pipeline에서 없어진 유일한 옛 검사는 `test_scenario_rejects_two_cuts`이다.
정규 테스트의 `test_scenario_accepts_two_cuts_for_weekly`와
`test_scenario_rejects_single_cut`이 현행 컷 수 계약을 검사한다.
루트 중복 실행 횟수를 고유 커버리지 수로 더하지 않는다.

## 5. 후속 개발 순서

1. R01/R02: 최초 생성 입력의 DB 확정과 정책 권위를 먼저 구현한다.
2. R03/R04: 패널 출처를 고정하고 v2 일부 실패를 기존 성공 이미지 재생성 없이 복구한다.
3. R05/R08: 실제 선택된 이미지·연출·조립·검수와 발행 claim을 연결한다.
4. 역할별 스타일/캐논 투영, 컷 리듬, 모바일 예약 밴드 및 실제 배치 보고를 연결한다.
5. 격리 DB의 실패·동시성·권한 검사 후 미발행 실제 이미지 파일럿을 수행한다.

운영 코드 배포, 운영 DB 쓰기, 기존 성공 PNG 변경, 유료 이미지 생성,
SNS 발행은 이번 개발에서 수행하지 않았다. 회차별 일회성 코드·워크플로는 추가하지 않았다.
