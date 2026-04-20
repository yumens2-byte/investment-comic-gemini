# Video Pre-Op 수기 생성 운영 상세설계 + 개발착수 (2026-04-20)

## 1) 배경
영상 퀄리티가 아직 확정되지 않은 상태에서 Veo/조립/게시를 자동으로 강행하면 비용 소모와 운영 리스크가 크다.
따라서 운영 전(Pre-Op) 단계에서는 **텔레그램으로 프롬프트를 전달**하고,
운영자가 Gemini Chat에서 **수동 생성**을 수행한다.

추가 원칙:
- Pre-Op 단계에서는 **X 게시를 수행하지 않는다**.
- 자동화는 분석/내러티브까지 활용하고, 생성/게시는 수기로 검증한다.

---

## 2) 운영 모드 설계

## 2-1. 모드 정의
- `manual_prompt` (기본):
  - 실행: `data -> scenario -> narrative -> manual_prompt_notify`
  - 미실행: `persist_init/veo/assembly/gate_notify`
  - 정책: X 게시 금지
- `full_pipeline`:
  - 실행: 기존 자동 파이프라인 (`persist_init/veo/assembly/gate_notify` 포함)

## 2-2. 입력 파라미터
`run_video_trailer.yml`에 `operation_mode` 입력을 추가한다.
- default: `manual_prompt`
- options: `manual_prompt`, `full_pipeline`

---

## 3) Telegram 수기 생성 전달 상세

## 3-1. 신규 stage
- `manual_prompt_notify` stage를 `scripts/run_video_trailer.py`에 추가

동작:
1. `config/prompts/cut1_prompt.txt`, `cut2_prompt.txt`, `cut3_prompt.txt`에서 각 컷별 `PROMPT`, `CHARACTER_LOCK`, `NEGATIVE_PROMPT` 로드
2. `episode_id` 생성
3. 텔레그램 메시지 조립
   - 운영 모드
   - 정책(no X publish)
   - 24초 구성(8초 x 3컷) 명시
   - cut1/cut2/cut3 prompt/negative_prompt 본문
4. `MASTER_CHAT_ID`로 Bot API `sendMessage` 전송

예외/안전장치:
- `DRY_RUN=true`면 실제 전송 없이 payload preview 로그만 남김
- 긴 메시지는 3,500자 단위로 분할 전송(순번 `[1/N]` 헤더)
- `MASTER_CHAT_ID` 없으면 `TELEGRAM_FREE_CHANNEL_ID` fallback
- cut2/cut3 파일 누락 시 cut1 프롬프트 fallback 사용(운영 중단 방지)
- 텔레그램 전송 실패 시에도 `output/manual_prompts/{episode_id}.txt`에 저장 후 fail-open 지속

## 3-2. X 게시 차단
- `stage_publish_x`에서 `OPERATION_MODE=manual_prompt`면 즉시 skip/warn 처리
- 정책 위반 방지용 이중 가드(워크플로우 단계 + 런너 단계)

---

## 4) 개발착수 반영 범위

### A. Workflow 반영
- `operation_mode` input 추가
- `full_pipeline`에서만 `persist_init/veo/assembly/gate_notify` 실행
- `manual_prompt`에서는 `manual_prompt_notify` 실행

### B. Runner 반영
- `manual_prompt_notify` stage 추가
- Telegram Bot API 전송 helper 추가
- `publish_x` 모드 가드 추가

---

## 5) 롤아웃 플랜

## Step 1 (즉시)
- 기본 모드를 `manual_prompt`로 운영
- 수기 생성 결과물을 운영자가 리뷰/축적

## Step 2 (품질 안정화)
- 수기 생성 결과를 기준으로 prompt/negative_prompt 개선
- 품질 기준(해상도/일관성/텍스트 artifact 등) 정량화

## Step 3 (자동화 복귀)
- 합격 기준 충족 시 `full_pipeline` 전환
- 이후에만 X 게시 단계 활성 운영

---

## 6) 승인 기준(Pre-Op 종료 게이트)
- 최근 10회 수기 생성 중 품질 합격률 90% 이상
- 재생성 비율 20% 이하
- 텍스트 artifact/캐릭터 붕괴 치명 오류 0건

위 기준 충족 전까지는 `manual_prompt` 운영을 유지한다.
