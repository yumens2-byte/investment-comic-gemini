# 메일 기반 업무지시 비서 시스템 병렬 분장 브레인스토밍 및 상세설계 (v1.0)

## 1) 문서 목적 / 전제
- 본 문서는 제공된 요구사항 정의서를 **실행 가능한 개발 계획**으로 전환하기 위한 분석 결과다.
- 목표는 다음 3가지다.
  1. 요구사항의 핵심 제약(보안/컴플라이언스, 1,000자 제한, PDF 첨부 정책, 허용 발신자 정책)을 누락 없이 구조화
  2. 팀이 즉시 착수 가능한 **병렬 업무 분장(Workstream)** 정의
  3. Cloud Run + Secret Manager + Gmail + AI Router 기반의 **상세 설계** 확정

---

## 2) 핵심 요구사항 요약 (의사결정 포인트)

### A. 보안/컴플라이언스 우선순위
- 외부 AI API 호출 전 **민감정보 탐지(PII/금융/인증/내부정보)** 필수
- 고위험 탐지 시 외부 전송 금지 + 차단 회신/로그
- Secret은 오직 Secret Manager에서 조회, 코드/로그/이미지 유출 금지
- 운영 초기에는 비민감 샘플만 허용하는 보수적 운영

### B. 메일 처리 정책
- 허용 발신자만 처리(ALLOWED_COMMAND_SENDERS)
- 미허용 발신자는 SKIPPED 감사로그만 남기고 미처리
- message_id 기반 중복 방지, 단 [재처리] 정책 예외 허용

### C. 출력 정책
- 본문 1,000자 초과 금지
- 코드/SQL/설정/스크립트/장문설계/표 복잡도 높음 → PDF 첨부
- 본문 금지 문구 제거(모델명, AI 자동 생성 문구)
- 제목은 업무형 동적 생성

### D. 플랫폼 정책
- Cloud Scheduler(OIDC) -> Cloud Run /jobs/poll-mail 주기 호출
- Cloud Run 비공개(unauthenticated 금지)
- 최소권한 IAM(런타임/배포계정 분리)

---

## 3) 병렬 분장 브레인스토밍 (권장 5개 트랙)

> 전제: 트랙 간 의존성을 줄이기 위해 공통 인터페이스를 먼저 고정하고 병렬 개발

## Track 0. 아키텍처/표준/품질게이트 (1명, 선행 1~2일)
**목표**
- 전 트랙 공통 계약(interfaces, DTO, 에러코드, 로그 스키마) 선확정

**산출물**
- API 계약서: /health, /jobs/poll-mail, /jobs/reprocess
- 도메인 모델: MailMessage, ProcessResult, RiskLevel, TaskType, ModelPlan
- 공통 오류코드: SECRET_MISSING, SENDER_NOT_ALLOWED, HIGH_RISK_BLOCKED 등
- 감사로그 JSON 스키마

**완료기준**
- 이후 Track 1~4가 Stub 없이 병렬 개발 가능

---

## Track 1. 인프라/런타임/배포 (DevOps 1~2명)
**범위**
- Cloud Run 앱 구동, Dockerfile, cloudbuild.yaml, Scheduler OIDC, IAM 최소권한

**주요 작업**
1. FastAPI 실행 컨테이너 이미지 빌드
2. Cloud Run 서비스 배포 스크립트
3. Scheduler Job 생성(POST /jobs/poll-mail, OIDC SA)
4. Secret 접근 권한 검증(Secret Accessor)
5. 버전/헬스체크 엔드포인트 운영화

**리스크/체크리스트**
- unauthenticated 허용 여부 실수 방지
- 런타임 SA 과권한 금지
- 배포계정과 런타임 계정 분리 검증

---

## Track 2. 메일 입출력 + 정책 엔진 (Backend 2명)
**범위**
- Gmail Reader/Sender, Sender Policy Validator, 중복 처리 저장소

**주요 작업**
1. Gmail OAuth refresh token 기반 인증 모듈
2. query 기반 미처리 메일 조회(gmail_reader)
3. 허용 발신자 검증(sender_policy)
4. message_id 저장소(processed_store: Firestore or GCS+index)
5. thread reply + PDF attachment 발송(gmail_sender)

**리스크/체크리스트**
- From 헤더 파싱 안정성(이름+이메일 형태)
- message_id + 재처리 플래그 정책 충돌 처리
- 첨부파일 MIME 처리/인코딩

---

## Track 3. 보안필터/가드레일 (Security+Backend 2명)
**범위**
- pii_detector, masking_service, content_guard, 결과 검증기

**주요 작업**
1. 정규식 + 키워드 기반 PII/Secret 탐지기
2. 위험도 분류(Low/Medium/High) 정책 테이블
3. High 발생 시 외부 AI 호출 차단 로직
4. 본문 금지 문구 제거/치환 필터
5. 1,000자 제한 + 코드 포함 탐지기(ResultValidator)

**리스크/체크리스트**
- 오탐/미탐 밸런스(금융권 기준 보수적으로)
- 로그에 원문 민감정보 기록 금지
- 차단 시 사용자 안내문도 보안친화적 표현 사용

---

## Track 4. AI 라우터 + 클라이언트 추상화 (AI Backend 2명)
**범위**
- task_classifier, model_router, openai/claude/gemini client, retry/fallback

**주요 작업**
1. TaskType 분류(코드분석/요구사항/요약/복합)
2. 모델 우선순위 및 fallback 매트릭스 구현
3. timeout/retry/backoff 표준화
4. 모델 실패 시 체인형 fallback + 원인로그
5. 민감정보 정책과 연동(호출 금지 상태 지원)

**리스크/체크리스트**
- 모델별 응답 포맷 차이 정규화
- 타임아웃/재시도 누적으로 지연 증가
- 금지 문구 생성 시 후처리 필수

---

## Track 5. 출력생성/PDF/운영문서/테스트 (Backend+QA 2명)
**범위**
- mail_body_builder, pdf_generator, title_builder, README/운영문서, 테스트 자동화

**주요 작업**
1. 1,000자 이하 요약 본문 빌더
2. PDF 생성(한글 폰트 내장, 목차 1~7)
3. 제목 자동 생성 규칙
4. 단위/통합 테스트(TC-01~10) 구현
5. 운영 매뉴얼(재처리, 장애대응, 보안주의)

**리스크/체크리스트**
- 한글 폰트 깨짐
- 첨부 파일 크기/메일 API 제한
- PDF 실패 시 graceful fallback 회신

---

## 4) 권장 병렬 일정(2주 스프린트 예시)

### Day 1~2: 설계 고정
- Track 0 계약 확정
- Track 1 베이스 인프라 시작
- Track 2/3/4/5 인터페이스 기반 Stub 개발 시작

### Day 3~6: 핵심 기능 병렬 구현
- Track 2 Gmail + sender policy + dedup 완성
- Track 3 탐지/차단/마스킹 완성
- Track 4 라우터/fallback 완성
- Track 5 본문/PDF/제목/테스트 뼈대 완성

### Day 7~8: 통합/결함수정
- E2E: poll-mail -> 분류 -> AI -> 회신
- 보안/실패경로 테스트(고위험 차단, 모델 장애, PDF 실패)

### Day 9~10: 배포/운영준비
- Cloud Run 배포 검증
- Scheduler OIDC 운영점검
- README/운영체크리스트 확정

---

## 5) 상세 설계 (구현 청사진)

## 5.1 디렉터리 구조(요구사항 준수)
```text
mail-secretary/
  app/
    main.py
    config/
      settings.py
      secret_loader.py
    mail/
      gmail_reader.py
      gmail_sender.py
      mail_models.py
      sender_policy.py
    command/
      command_parser.py
      task_classifier.py
    security/
      pii_detector.py
      masking_service.py
      content_guard.py
    ai/
      model_router.py
      base_client.py
      openai_client.py
      claude_client.py
      gemini_client.py
    output/
      mail_body_builder.py
      pdf_generator.py
      title_builder.py
    audit/
      audit_logger.py
      processed_store.py
    common/
      errors.py
      logging.py
  tests/
  Dockerfile
  requirements.txt
  cloudbuild.yaml
  README.md
```

## 5.2 엔드포인트 계약
### GET /health
- 반환: `{status:"ok", app_env:"prod"}`
- 용도: 런타임 상태 확인

### POST /jobs/poll-mail
- 인증: Cloud Scheduler OIDC 필수
- 처리: 미처리 메일 조회 후 파이프라인 실행
- 반환: 처리 요약(총건수, SUCCESS/FAILED/SKIPPED)

### POST /jobs/reprocess
- 입력: `message_id`
- 권한: 관리자 토큰/내부 인증
- 처리: dedup 우회 재처리

### GET /version (옵션)
- git sha, build time, app version

## 5.3 핵심 도메인 모델
- `MailMessage`: message_id, thread_id, sender, subject, body, attachments
- `SecurityScanResult`: risk_level, findings, masked_text, block_external
- `TaskType`: CODE_REFACTOR / REQUIREMENT_DOC / SUMMARY / COMPLEX
- `ModelPlan`: primary, fallbacks[]
- `ProcessOutcome`: status, reply_subject, reply_body, pdf_path(optional)

## 5.4 처리 시퀀스 상세
1. `secret_loader`가 실행시 필요한 Secret 선로딩 + 누락 즉시 fail-fast
2. `gmail_reader`가 MAIL_QUERY로 메시지 조회
3. `sender_policy`에서 allowlist 검증
4. `processed_store`에서 dedup 확인(재처리 플래그 예외)
5. `command_parser`가 제목/본문/첨부 메타 수집
6. `pii_detector` + `content_guard`로 위험도 산정
7. High risk면 AI 호출 차단 및 보안 회신 경로
8. 정상 건은 `task_classifier` -> `model_router` -> AI 클라이언트 호출
9. `result_validator`가 금지문구/코드포함/길이초과 검사
10. 규칙 충족 시 `mail_body_builder` 본문 생성, 아니면 `pdf_generator`
11. `gmail_sender`로 thread reply
12. `audit_logger` + `processed_store` 기록

## 5.5 모델 라우팅 테이블 (정책 반영)
- 코드 분석/리팩토링: ChatGPT -> Claude -> Gemini
- 요구사항/설계서: Claude -> ChatGPT -> Gemini
- 요약/분류/메일초안: Gemini -> ChatGPT -> Claude
- 복합 기술 판단: ChatGPT -> Claude -> Gemini
- 민감정보 고위험: 외부 호출 금지

## 5.6 보안 설계 상세
- 탐지 카테고리
  - PII: 주민번호/전화/주소/고객명 패턴
  - 금융정보: 계좌/카드/대출/계약번호
  - 인증정보: API Key, Token, Password, OAuth Secret
  - 내부정보: 내부 IP/서버명/내부 URL/시스템코드
- 정책
  - High: 외부전송 차단 + 최소 회신 + 감사로그
  - Medium: 마스킹 후 제한 전송
  - Low: 정상 전송
- 감사로그
  - 원문 저장 금지, 지표/해시/카테고리 중심 저장

## 5.7 PDF 생성 설계
- 생성 조건
  - 본문 1,000자 초과
  - 코드/SQL/설정/스크립트 포함
  - 장문 설계/표 복잡 구조
  - 보안상 본문 노출 부적절
- 목차 고정
  1) 제목
  2) 요청 요약
  3) 검토 결과 요약
  4) 상세 분석
  5) 코드/설계/테이블
  6) 보안 및 운영 주의사항
  7) 결론
- 구현 메모
  - Noto Sans CJK 등 한글 폰트 번들/내장
  - 생성 실패 시 본문 최소 요약 + FAILED 보조로그

## 5.8 설정/비밀/환경변수
- Secret Manager
  - GMAIL_CLIENT_ID
  - GMAIL_CLIENT_SECRET
  - GMAIL_REFRESH_TOKEN
  - SYSTEM_MAIL_ACCOUNT
  - ALLOWED_COMMAND_SENDERS
  - OPENAI_API_KEY
  - CLAUDE_API_KEY
  - GEMINI_API_KEY
- 비민감 ENV
  - GCP_PROJECT_ID
  - SECRET_PREFIX
  - APP_ENV
  - POLL_MAX_RESULTS
  - MAIL_QUERY
  - PDF_FORCE_FOR_CODE

## 5.9 실패/재시도 설계
- Gmail API: 지수백오프 + 최대시도 초과 시 FAILED
- Secret 조회 실패: 즉시 중단(메일 처리 금지)
- AI 1차 실패: fallback 체인
- 모든 AI 실패: 실패 회신 또는 로그 저장 정책
- 중복 message_id: SKIPPED

## 5.10 테스트 설계 (TC-01~10 매핑)
- 단위 테스트
  - sender_policy / pii_detector / model_router / mail_body_builder / pdf_generator
- 통합 테스트
  - poll-mail end-to-end with mocked Gmail/AI
- 필수 시나리오
  - 허용/미허용 발신자
  - 1,000자 임계값
  - 코드 포함 시 PDF 강제
  - API Key 탐지 차단
  - primary 실패 fallback
  - 중복 메시지 SKIPPED
  - 금지문구 제거

---

## 6) 최종 브리핑 (의사결정용)

### 무엇을 먼저 해야 하나?
1. **Track 0 계약 고정**: 인터페이스/로그/오류코드 먼저 잠그면 병렬 효율이 급상승
2. **Track 3 보안필터 선구현**: 외부 AI 호출 차단 경계가 시스템 리스크를 좌우
3. **Track 2+4+5 동시개발**: 메일 I/O, 라우터, 출력을 인터페이스 기반으로 병렬 진행
4. **Track 1은 초기에 뼈대 배포**: /health와 /jobs/poll-mail 조기 실배포로 통합 리스크 축소

### 성공의 핵심 지표(KPI)
- 미허용 발신자 100% SKIPPED
- High risk 탐지 시 외부전송 0건
- 본문 1,000자 초과 0건
- 코드 포함 결과의 PDF 첨부율 100%
- message_id dedup 정확도 100%
- TC-01~10 자동화 테스트 통과

### 운영 전 필수 게이트
- 보안팀 승인(외부 AI 전송 정책)
- 감사로그 보존 정책 확정
- Secret 회전/권한 점검
- 장애시 수동 재처리 Runbook 검증

---

## 7) 병렬 분장표 (즉시 실행용)

- Squad A (Platform)
  - Cloud Run 배포, Scheduler OIDC, IAM 최소권한, 운영 파이프라인
- Squad B (Mail Core)
  - Gmail 읽기/회신, sender allowlist, dedup store
- Squad C (Security Guard)
  - pii detector, masking, high risk block, forbidden phrase filter
- Squad D (AI Orchestration)
  - 분류기, 모델 라우터, 다중 클라이언트, retry/fallback
- Squad E (Output & QA)
  - 본문 1,000자 빌더, PDF 생성, 제목 빌더, 테스트/문서

> 권장 방식: 매일 통합 스탠드업에서 인터페이스 변경을 금지(변경 필요 시 Architecture owner 승인).

