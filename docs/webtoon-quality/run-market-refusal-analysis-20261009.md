# Run Market 공급자 거절 재발 분석 및 수정

작성일: 2026-10-09 KST. 분석 기준 main: `041767657e28e3b8a94f9c3a734c539f2cb1fbef`.

## 확인된 운영 상태

| 대상 날짜(KST) | 정기 실행 | 확인한 결과 | 현재 DB 상태 |
|---|---|---|---|
| 2026-10-07 | 37532126593 | 이미지 P1~P6 성공, 정상 발행 | published |
| 2026-10-08 | 37690049331 | P4 FinishReason.PROHIBITED_CONTENT로 중단 | 복구 실행 37696333937 이후 published |
| 2026-10-09 | 37846891956, job 113549872814 | P1 성공 후 P2 FinishReason.PROHIBITED_CONTENT로 중단 | narrative_done |

운영 `icg.episode_assets`, `icg.image_generation_calls`, `icg.run_logs`를 읽기 전용으로 대조했다. 최근 세 날짜가 모두 실패했다는 설명은 이 자료와 일치하지 않는다. 다른 실행의 오류 여부는 위 표로 단정하지 않는다.

원본 로그: https://github.com/yumens2-byte/investment-comic-gemini/actions/runs/37846891956

## 직접 실패 원인과 판정 한계

Gemini API의 HTTP 200 응답 안에 이미지 대신 PROHIBITED_CONTENT 종료 사유가 반환됐다. 일반 경로는 이를 terminal로 원장에 정산한 뒤 원장의 HOLD 응답 때문에 STEP_6 및 전체 작업을 중단했다. 요청 실패, 이미지 실패, 미확정 비용을 구분해야 한다. 이 실행은 이미지 생성 거절이며 로그의 입력 토큰 계산 비용은 0.000621 USD다. 공급자 청구서를 검증한 값은 아니다.

공식 API 문서에서 PROHIBITED_CONTENT는 잠재적인 금지 콘텐츠로 인해 생성을 종료한 사유다. 특정 단어나 REF 요소가 원인이라는 의미는 아니다.

출처: https://ai.google.dev/api/generate-content#FinishReason

오늘 P2의 저장된 action은 데이터 화면을 관찰하는 장면이다. 이 사실만으로 폭력·무기·저작권·연령 중 어떤 항목이 거절 원인인지 확정할 수 없다. 원본 최종 입력/REF 해시와 공급자 상세 진단을 비교해야 한다.

## 재발 대응을 막은 구현 결함

1. 정기 실행의 `ICG_IMAGE_RETRY_V2_ENABLED` 기본값은 false다. 10월 8일 복구 계획은 그 날짜의 script/REF/fingerprint에 결합되어 있으며 10월 9일에 자동 복제되지 않는다. 기존 복구가 완료됐다는 사실은 모든 미래 회차의 자동 복구가 활성화됐다는 뜻이 아니다.
2. 일반 경로는 검토 retry plan이 없어서 `finish_message`, `safety_ratings`, 최종 전체 입력의 비공개 진단 저장 분기에 들어가지 않는다. 실제 오늘 `image_prompts_json`은 NULL, `_reviewed_image_inputs`/`_reviewed_image_retry_plans`는 없음, 해당 날짜의 private diagnostic은 0건이었다. fingerprint만으로 전체 원문을 역산할 수 없다.
3. OBSERVATION_ACTION_CONFLICT 검사는 STEP_6에만 연결되어 있었다. 기존 production narrative 검사에는 연결되지 않아 이미지 단계에서 발견한 관찰/타격 충돌을 기존 대본 quality retry가 수정할 수 없었다.
4. 일반 경로가 GenerationHold로 중단되면 panel summary를 기록하지 않아 성공/중단/미호출 패널을 하나의 결과로 확인하기 어려웠다.
5. 런타임 style의 원문에는 특정 출판사·작가 스타일 요청 및 모든 개체에 긴 인간 팔다리를 적용하라는 지시가 있었다. 원본 캐릭터·REF 해부학 계약과 충돌하므로 수정했지만, 이 충돌이 오늘 P2 거절의 원인이라는 실증은 없다.

## 수정 내용

- 일반 호출도 예약 token에 결합된 정확한 입력과 REF SHA-256을 유료 호출 전에 서버 전용 테이블에 저장한다. 검토 retry plan을 만들거나 승인하지 않는다.
- 입력 저장 실패 시 공급자를 호출하지 않고 해당 미호출 예약을 확정 비용 0으로 정산한다. 이 실패로 유료 호출을 추가하지 않는다.
- 거절 정산이 HOLD를 반환해도 원본 공급자 이유/상세 진단을 저장한다. 원장 상태, 예산, terminal 차단은 변경하지 않는다.
- SDK snake_case 및 REST camelCase의 사유/상세 정보를 읽는다. 이미지 recitation, escalation, account policy 제한도 terminal로 분류하며 inline image가 함께 있어도 성공으로 인정하지 않는다.
- OBSERVATION_ACTION_CONFLICT를 production narrative 검증 및 대본 수정 피드백에 연결했다. 기존 bounded quality retry를 사용한다.
- style에서 기존 특정 출판사/작가 요청을 원본 금융 코믹 기법 설명으로 교체했다. 인간 비율 지시는 humanoid에만 적용하고 비인간 REF anatomy를 유지한다. 신규 프롬프트에 성인 가상 인물과 비유적 비그래픽 장면이라는 맥락을 명시한다.
- 일반 경로에서도 generation-summary.json을 저장한다. held 패널 뒤의 패널은 not_attempted이고, 비용 합계가 부분값이면 cost_complete=false다. 완전한 이미지가 없으면 기존 image_generated/발행 완전성 검사를 통과하지 않는다.

새 SQL은 `docs/sql/image-generation-attempt-diagnostics.sql`이다. RLS를 켜고 public/anon/authenticated 조회·쓰기·RPC 실행을 금지한다. service_role은 SELECT/INSERT/RPC만 가능하고 보존된 증거를 UPDATE/DELETE할 수 없다. token/kind PK와 payload 비교로 동일 저장은 멱등, 변경 저장은 거부한다. SQL은 SECURITY INVOKER이며 기존 생성 원장이나 회차 데이터를 수정하지 않는다.

## 검증

- 관련 이미지/대본 검사 82개 통과 후 공식 종료 사유 3개에 대한 추가 테스트를 도입했다.
- 추가 테스트 및 운영 장애 모의시험 15개 통과.
- PostgreSQL WASM PGlite 0.5.8에서 SQL/권한/멱등성/원장 보존 계약 8개 통과. 단일 backend이며 실제 Supabase 다중 세션 검증을 대신하지 않는다.
- Ruff 전체 검사 및 git diff --check 통과.
- 최종 Python 3.11 전체 회귀 결과는 아래 최종 검증 절에 기록한다.

초기 전체 회귀에서 기존 fake RPC가 신규 진단 endpoint를 구현하지 않아 모의 quota 테스트 1개가 실패했다. fake backend에 token/fingerprint 검증 및 진단 receipt를 추가한 후 해당 테스트를 통과했다. 생성 코드의 HOLD를 완화하지 않았다.

### 최종 검증

- Python **3.11.17**: `python -m pytest tests/ -q` → **1,627 passed / 66.26초**.
- 전체 Ruff 검사 및 diff 공백 검사 통과.
- CI에 별도 Image Attempt Diagnostics Contract job을 추가했다. PGlite는 0.5.8로 고정하며 운영 DB 자격증명 없이 새 SQL 8개 계약을 실행한다.
- 원인 분석·개발·테스트 변경은 총 11개 파일이며 생성된 output 디렉터리와 private 분석 자료는 커밋에 포함하지 않는다.

## 운영 반영 순서 및 현재 회차 복구 조건

이 변경은 운영 배포 및 오늘 회차 복구가 완료됐다는 보고가 아니다.

1. 신규 진단 SQL을 운영에 적용하고 서버 역할에서 저장/조회 및 anon/authenticated 차단을 확인한다. SQL보다 새 클라이언트를 먼저 반영하면 입력 진단 RPC 누락 때문에 유료 호출 전에 중단한다.
2. CI가 통과한 코드 변경을 main에 반영한다. 원복 시 코드부터 이전 버전으로 되돌리며 새 진단 테이블은 증거 보존을 위해 남긴다.
3. 10월 9일의 원본 P1 PNG는 실행 37846891956의 episode artifact에 있다. 기존 성공 fingerprint/output_hash를 보존하고, 복원된 PNG의 SHA-256을 원장과 대조한다.
4. 오늘 P2 terminal을 삭제하거나 같은 입력으로 반복하지 않는다. 확정 비용과 실제 원본 입력을 대조하고 기존 명시적 recovery receipt/revision 계약으로 검토한 대체 장면을 등록해야 한다.
5. 오늘의 전체 미완료 대본에는 손/방패/소총 위치 등 카논과 맞지 않는 action도 있으므로 복구 입력 검토에 포함한다. 성공한 P1을 새 style로 재생성하지 않는다. 새 빌더 입력은 fingerprint가 달라질 수 있다.
6. 이후 제한 복구 실행에서 모든 필수 이미지와 dialog gate 도달을 확인한 뒤 기존 발행 절차를 진행한다.

이번 조사·수정·로컬 테스트에서 운영 DB 쓰기, Gemini 유료 호출, 회차 발행 또는 main 병합은 수행하지 않았다. 운영 접근 제어의 다른 기존 문제를 이 변경에서 일괄 수정하지 않는다.
