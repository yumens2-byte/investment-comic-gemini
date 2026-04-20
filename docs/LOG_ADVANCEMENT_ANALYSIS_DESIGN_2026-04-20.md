# ICG 로그 고도화 분석/설계 (2026-04-20)

## 목적
현재 코드베이스에서 **발행/운영 로그 체계**를 점검하고, 운영 안정성/관측성(Observability) 강화를 위한 설계안을 제시한다.

---

## A. 현재 로그 구조 분석

### 1) 공통 StepLogger (이미지 트랙 중심)
- `StepLogger`는 `output/episodes/{date}/run.log`에 JSONL 로그를 남기고, 동시에 `icg.run_logs`에 INSERT한다.
- Supabase 실패 시 `_degraded=True`로 전환하여 파이프라인은 지속한다(파일 로그 우선).
- 마스킹 대상(키/PII) 패턴이 코드 레벨로 정의되어 있다.

**강점**
- 구조화 로그(JSONL) + DB 이중화.
- 민감정보 마스킹 내장.
- step_start/step_done 기반 duration 수집 가능.

**한계**
- 상태값(`ok/warning/error/fail`) 의미 체계가 운영 관점에서 일관적이지 않음.
- `run_id` 외 상관관계 키(예: workflow_run_id, episode_id, channel)가 레코드에 항상 포함되지 않음.

### 2) 발행 트랙(run_publish)
- `STEP_8`, `STEP_8_X`, `STEP_8_TG` 중심으로 로그를 기록.
- 중복 발행 방어가 강하게 구현되어 있어 실패 원인 추적에 유리함.

**강점**
- 중복 발행 차단 로그가 명확(이미 published / published_comics 중복).
- 채널별 단계 분리가 되어 있어 장애 위치 파악이 빠름.

**한계**
- 채널별 성공/실패 코드 분류(재시도 가능 vs 불가능)가 로그 message 텍스트에 의존.
- 결과 요약(실패율, 평균 runtime) 자동 집계 루틴 부재.

### 3) 비디오 트랙(run_video_trailer)
- `logs/{GITHUB_RUN_ID}/{stage}.log`에 plain text 로그를 남김.
- 환경변수 set/missing 및 stage 흐름이 상세 기록됨.

**강점**
- 런타임 컨텍스트(버전/플랫폼/GitHub run context) 추적성이 높음.
- stage 단위 로그 파일 분리로 디버깅 접근성이 좋음.

**한계**
- StepLogger(JSONL)와 포맷이 달라 트랙 간 통합 분석이 어려움.
- 로그는 상세하지만 메트릭형 집계(단계별 p95, 에러코드 상위) 자동화가 없음.

---

## B. 현재까지 분석 시점의 데이터 한계

이번 리포지토리 워킹트리에는 실제 산출 로그 파일(`output/episodes/*/run.log`, `logs/*/*.log`)이 포함되어 있지 않아,
**실행 이력 기반 통계 분석은 불가**했다.

따라서 본 문서는:
1. 코드 상 로그 발행 지점/포맷을 분석하고,
2. 실로그가 축적되었을 때 즉시 적용 가능한 분석 파이프라인/스키마 설계를 제안한다.

---

## C. 고도화 설계안

### 1) 로그 표준 이벤트 스키마(권장)
공통 필드를 모든 트랙에 강제:
- `ts` (UTC ISO8601)
- `run_id`
- `track` (`image|publish|video`)
- `step`
- `status` (`ok|warn|error|fail_closed|fail_open`)
- `duration_ms`
- `episode_date`
- `episode_id`
- `channel` (`x|telegram|shorts|none`)
- `error_code` (정규화된 코드)
- `message`
- `meta` (JSON)

> 핵심: 지금의 텍스트 중심 오류 메시지를 `error_code` 기반으로 재분류하면 주간 장애 Top-N이 자동 집계된다.

### 2) 실패 등급 체계
- `fail_closed`: 파이프라인 중단 필요 (예: 중복 발행 차단, 데이터 무결성 오류)
- `fail_open`: 경고 후 진행 (예: 보조 저장소 실패, 알림 실패)
- `warn`: 품질 저하 가능성이 있으나 성공 처리

### 3) SLO/알림 설계
- STEP_8 발행 성공률(SLI): `published / attempted` (일별)
- STEP runtime p95: STEP_3, STEP_6, STEP_8_X, STEP_8_TG
- 알림 규칙 예시:
  - 15분 내 `fail_closed` ≥ 1: 즉시 Pager
  - 24시간 발행 성공률 < 95%: 운영 경고
  - `degraded mode` 진입: 주의 알림 + 1시간 내 자동복구 체크

### 4) 저장소/조회 모델
- 단기(즉시): JSONL + Supabase `run_logs` 유지
- 중기: `run_logs` 파티셔닝(월 단위) + 인덱스
  - `(episode_date, step)`
  - `(status, ts)`
  - `(run_id)`
- 장기: BI용 뷰(주간 실패율, step p95, 채널 성공률)

### 5) 운영 루프(주간)
1. 실패 상위 error_code Top 10 확인
2. 재시도 정책 업데이트(가능/불가 분리)
3. 마스킹 누락 패턴 테스트 케이스 추가
4. SLO 미달 step의 타임아웃/병렬화 설계 반영

---

## D. 즉시 실행 가능한 구현(이번 반영)
- `scripts/analyze_logs.py` 추가:
  - JSONL run.log + video plain-text 로그를 자동 집계.
  - Level/STEP 빈도, 실패 집중, duration 분포를 리포트로 생성.
  - 로그가 없어도 “데이터 없음”을 명확히 출력.

**기본 실행**
```bash
python -m scripts.analyze_logs
```

**출력 파일**
- `output/log_analysis/report.md`

---

## E. 다음 스프린트 우선순위
1. 비디오 트랙에 StepLogger 호환 JSON 이벤트 병행 기록 추가.
2. `error_code` 표준화(발행 채널 API 오류/권한/중복/입력검증).
3. `run_logs` 주간 집계 SQL + 대시보드 템플릿(실패율, p95, degraded 횟수).
4. 장애 회고 자동 리포트(지난 7일 실패 Top + 재발방지 액션).

