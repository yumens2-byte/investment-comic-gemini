# 페이지 발행 사전 검증 (2026-10-11 KST)

실행 38066135515는 이미지 8장 업로드 이후 PAGE_GATE_UNAVAILABLE로 중단됐다. 같은 시간 DB 로그에 facebook_observe/begin 호출이 없어 페이지 이력 조회 실패가 유력하지만, Meta 원본 오류가 숨겨져 있어 인증/권한 원인은 확정되지 않았다.

ControlledPublisher.check는 페이지 식별 확인에 이어 최근 24시간 게시 이력의 완전성 및 DB 계약 버전을 읽기 전용으로 검사한다. Sidestory live publish와 auto 경로는 이 검사를 이미지 업로드와 publishing 선점 전에 수행한다. 실패 시 assembled 상태에서 error를 반환하며 업로드 및 공개 게시 요청을 하지 않는다.

사전 검증은 실제 게시 권한 전체나 최종 발행 성공을 보장하지 않는다. 페이지 정책·동시성·한도·관측 RPC의 쓰기 권한은 최종 원자적 게이트가 계속 판정한다. 사전 조회 결과를 캐시하지 않고 발행 시 이력을 다시 읽는다.

실패 단계는 page_history, page_gate_contract, page_gate_observe, page_gate_begin으로 구분한다. 알려진 DB 오류는 기존 안전 오류 코드로 분류하며, 원본 예외 메시지·URL·토큰은 출력하지 않는다. Meta 상세 HTTP 코드 분류는 이 변경 범위에 포함되지 않는다.

추가 테스트 7건: 이력/계약 검사 실패 무변경 및 비밀정보 비노출 2건, observe/begin 실패 시 게시 차단 2건, 사전검사 후 실제 전송 시 재조회 1건, 실제 run_publish에서 업로드 전 차단 및 assembled 유지 2건.

검증: Market Talk + P2 + auto 관련 테스트 164건 통과, 수정 파일 ruff 및 git diff --check 통과. 실제 Meta 연결 검증·발행은 아직 실행하지 않았다.
