# run_video_trailer.yml 고도화 분석/설계 (2026-04-20)

## 0) 목적
`run_video_trailer.yml`의 현재 구조를 운영 관점(안정성/비용/속도/디버깅)으로 분석하고,
즉시 적용 가능한 개선안과 단계적 고도화 설계를 제시한다.

---

## 1) 현재 워크플로우(As-Is) 분석

## 1-1. 트리거/실행 정책
- 스케줄: 매주 토요일 UTC 00:00 (KST 09:00)
- 수동 실행: `target_date`, `dry_run`, `log_level` 입력 지원
- 동시성 그룹: `icg-video-${target_date || today}`

### 강점
- 정기/수동 실행 병행으로 운영 유연성 확보.
- 날짜 기준 동시성 그룹으로 동일 날짜의 중복 실행을 완화.

### 한계
- 스케줄 실행 시 `target_date`가 비어 `today`로 고정되어, “재처리 run”과 구분이 어렵다.
- `cancel-in-progress: false`로 동일 그룹 중첩 시 대기열이 길어질 수 있다.

## 1-2. 스테이지 파이프라인
현재 단일 job에서 순차 실행:
1. data
2. scenario
3. narrative
4. persist_init
5. veo
6. assembly
7. gate_notify

### 강점
- 단계 이름이 명확해 운영자 가독성이 높다.
- 실패 지점이 직관적이라 장애 분석이 쉽다.

### 한계
- 모든 단계가 단일 실행축에 묶여, 특정 단계 재실행이 비효율적.
- `veo`/`assembly` 장시간 구간에서 전체 timeout(60분) 초과 위험.

## 1-3. 의존성/환경 구성
- Python 3.11 + `requirements-video.txt`
- FFmpeg apt 설치
- Secret 주입(Anthropic/Gemini/FRED/Notion/Supabase/X/Telegram)

### 강점
- 필요한 외부 연동 키가 workflow 레벨에서 중앙화.
- `dry_run`, `log_level`, `VIDEO_BUDGET_USD_MONTHLY` 운영 플래그 제공.

### 한계
- 시크릿 존재/형식 검증 단계가 없어, 중간 단계에서 늦게 실패할 수 있음.
- `pip install` 고정 잠금(lock) 부재로 재현성 변동 가능.

## 1-4. 관측성/산출물
- `logs/*.log` tail 출력
- `output/videos/`, `logs/` artifact 업로드

### 강점
- 실패 시에도 artifact 업로드(`if: always()`)로 사후 분석 가능.

### 한계
- 단계별 소요시간/성공률의 기계 집계 포맷(JSON 메트릭) 부재.
- 알림/게이트 결과의 구조화 요약이 부족해 운영 대시보드 연동이 어려움.

---

## 2) 리스크 맵

### R1. 비용 통제 리스크
- `veo` 단계 실패/재시도 누적으로 월 예산 초과 가능.
- 현행은 `VIDEO_BUDGET_USD_MONTHLY` 값 전달 중심이며, 사전 차단 정책이 불명확.

### R2. 장시간 실행 리스크
- apt + deps + generation + ffmpeg까지 단일 job 60분 제한.
- 외부 API 지연 시 전체 실패 확률 증가.

### R3. 운영 디버깅 리스크
- 텍스트 로그 중심이라 “어느 입력/어느 비용/어느 산출물”이 실패했는지 정량 파악이 느림.

### R4. 재실행/멱등성 리스크
- 날짜 기준 재실행 시 기존 산출물/DB 상태와 충돌 가능.
- 실패 지점 이후 resume 전략(자동/수동)이 workflow 레벨에 드러나지 않음.

---

## 3) 고도화 목표(To-Be)
1. **Fail Fast**: 시작 1~2분 내 구성/시크릿/예산 사전 검증.
2. **Resume Friendly**: 단계별 재실행 비용 최소화.
3. **Cost Guardrail**: 생성 단계 전/중 예산 차단.
4. **Observable by Default**: 구조화 요약 + 아티팩트 표준화.
5. **Safe Publish Gate**: 사람 승인/알림 흐름 명확화.

---

## 4) 설계안

## 4-1. Job 분리(권장)
단일 job → 3개 job 분리:
- `prepare` (checkout/setup/deps/validate)
- `generate` (data~veo)
- `assemble_and_gate` (assembly/gate_notify/artifact)

`needs`로 연결하고, `generate` 성공 시에만 `assemble_and_gate` 수행.

**효과**
- 실패 범위 축소, 재실행 단위 최적화.
- 각 job timeout 개별 설정 가능(예: generate 90분, others 20분).

## 4-2. 사전 검증 Step 추가
`python -m scripts.run_video_trailer --stage preflight` 신설(또는 validate 스크립트).
검증 항목:
- 필수 시크릿 누락 확인
- target_date 포맷/시간대 확인
- 월 예산 잔여치/당일 예상비용 체크
- output/log 경로 권한 확인

**정책**
- 실패 시 즉시 중단(`exit 1`) + 요약 리포트 artifact 업로드.

## 4-3. 캐시/재현성 강화
- pip 캐시 유지 + lock 파일 도입(`requirements-video.lock` 혹은 uv/pip-tools)
- FFmpeg 설치는 고정 버전 또는 prebuilt action 검토

**효과**
- 실행 시간/재현성 개선.

## 4-4. 구조화 실행 요약(JSON) 표준
각 stage 완료 시 `logs/{run_id}/summary.jsonl`에 append:
- `stage`, `status`, `duration_sec`, `cost_usd_est`, `output_count`, `error_code`

workflow 마지막에 markdown 요약 생성:
- 총 시간
- 단계별 성공/실패
- 예산 사용량(추정/확정)
- 생성 파일 리스트

## 4-5. 멱등성/재개 전략 명시
수동 실행 입력 확장:
- `resume_from`: `data|scenario|narrative|persist_init|veo|assembly|gate_notify`
- `force_rebuild`: `true|false`

실행 정책:
- `resume_from` 이전 단계는 스킵하되, 입력 무결성 체크는 수행.
- `force_rebuild=true`면 기존 산출물 클린 후 재생성.

## 4-6. 게이트/승인 모델 개선
- `gate_notify` 이후 GitHub Environment 보호 규칙(승인자 1인 이상) 적용 검토.
- 승인 전에는 publish 단계(추가 예정)를 절대 수행하지 않음.

## 4-7. 실패 후 자동 후속 처리
- `if: failure()`에서 `scripts/notify_failure.py` 호출.
- 실패 유형별 알림 템플릿 분리:
  - 시크릿/구성 오류
  - 외부 API 오류
  - 미디어 조합 오류
  - 예산 초과 차단

---

## 5) 권장 YAML 리팩터링 청사진

### 입력 파라미터(예시)
- `target_date` (기존)
- `dry_run` (기존)
- `log_level` (기존)
- `resume_from` (신규)
- `force_rebuild` (신규)

### Concurrency
- 그룹 키에 `resume_from` 포함 검토:
  - `icg-video-${target_date}-${resume_from||full}`

### Timeout
- prepare: 20
- generate: 90
- assemble_and_gate: 30

### Artifact
- 업로드 대상을 명시적으로 분리:
  - `logs/`
  - `output/videos/`
  - `output/manifests/` (신규)

---

## 6) 단계별 실행 로드맵

## Phase 1 (즉시, 1~2일)
1. preflight stage 도입
2. 실패 알림 자동화 연결
3. summary.jsonl 최소 필드 도입

## Phase 2 (단기, 3~5일)
1. workflow 3-job 분리
2. resume_from/force_rebuild 입력 추가
3. timeout 재설계

## Phase 3 (중기, 1~2주)
1. 비용 가드레일 정교화(예상비용+실사용비용)
2. 환경 승인 게이트 적용
3. 주간 운영 리포트 자동 발행

---

## 7) KPI/SLO 제안
- 실행 성공률(주간): `>= 95%`
- 평균 총 소요시간: `<= 45분`
- P95 총 소요시간: `<= 80분`
- 예산 초과 차단율: `100%` (초과 시 생성 중단)
- 실패 후 알림 도달률: `100%`

---

## 8) 결론
`run_video_trailer.yml`은 이미 운영 가능한 최소 요건(스케줄/수동 실행/로그/artifact)을 갖췄다.
다만 비용·시간·재실행·관측성 축에서 성장 여지가 크다.

가장 ROI가 높은 순서는 다음과 같다:
1. **preflight(시크릿/예산/입력 검증) 추가**
2. **단계별 구조화 요약(summary.jsonl) 도입**
3. **job 분리 + resume 전략 명시**

이 3가지를 먼저 적용하면 장애 복구 시간(MTTR)과 운영 리스크를 동시에 줄일 수 있다.
