# Weekly Digest Shorts v2 — 상세설계 및 배포 기록 (2026-09-25)

## 1. 결정 사항 (마스터 확정)

- 품질 정의: **정지 없음 · 빠름 · 움직임 많음**
- 규격: **B안 — 4초 × 4샷 = 16초** (전환 0.1초 × 3 차감 → 실길이 15.7초)
- 샷 구성: HOOK(도발) → CLASH(격돌) → TURN(전환) → RESOLVE(결말)

## 2. v1 결함 근거 (DB·코드 실측)

| 항목 | v1 실측 |
|---|---|
| 정지 구간 | 인트로/아웃트로 스틸 6초 (18초 중 33%) |
| video_prompt 길이 | W35~W38: 689~1,508자, W37 한 컷에 "Scene 1/2/3" |
| 컷당 캐릭터 | W37 5명, W38 4명 (히어로 전원 강제 + Canon 전문 주입) |
| 영상 내 글자·숫자 | "VIX 17.1", "57 and 69", "GOLD BOND" 요구 |
| 캐릭터 고정 | T2V 텍스트만 (REF 11장 미사용) |
| 인코딩 | 자막 단계 CRF23 + 최종 CRF18 이중 손실, loudnorm 미적용 |
| 각색 입력 | script_json 원문 전체(W38 55,696자, 외부 뉴스 요약 포함 가능) |

## 3. 구성

| 모듈 | 역할 |
|---|---|
| `engine/video/weekly_v2.py` | 캐스트 선정(코드), 압축 사실·`<source_data>` 래핑, v2 스키마, 검증, 각색, 저장/로드(스키마 분기) |
| `engine/video/weekly_media.py` | REF 키프레임(9:16) → Veo I2V 4샷, Motion QA(freezedetect/scene score), 비용 누적 원장 |
| `engine/video/weekly_render.py` | lanczos 업스케일·중간 펀치인·fadewhite 전환·ASS(정제)·Veo 효과음+나레이션·loudnorm·**1회 인코딩** |
| `engine/video/veo_client.py` v1.4.0 | I2V 실장, 단가 env(`VEO_UNIT_PRICE_USD`) |
| `scripts/run_video_trailer.py` v2.1.0 | `WEEKLY_FORMAT` 분기, 파일럿 처리, 발행 로더 분기 |
| `engine/publish/telegram_gate.py` v1.4.0 | 주간 ID 기반 중단 안내, 파일럿 안내 |

## 4. 운영 스위치

| 변수 | 기본 | 설명 |
|---|---|---|
| `WEEKLY_FORMAT` (Variable) | v1 | 파일럿 확인 후 v2 로 전환 |
| `VEO_UNIT_PRICE_USD` (Variable) | 0.15 | 청구 단가 확인 후 정정 |
| `WEEKLY_USE_VEO_AUDIO` (Variable) | true | Veo 효과음 활용 여부 |
| `WEEKLY_FREEZE_MAX` | 0.25 | 샷 정지 비율 상한 |
| `WEEKLY_MOTION_REGEN_MAX` | 1 | 샷당 재생성 횟수 |
| `VIDEO_BUDGET_USD_MONTHLY` | 16 | v2 회차 ≈$2.66(단가 0.15) × 월 5회 대응 |

## 5. 파일럿

`Weekly Digest Shorts` → Run workflow → `pilot=true`, `pilot_tag=P01`, `dry_run=false`.
episode_id `icg-vw-YYYY-Www-P01`, status 는 `assembled` 까지, release_at 미기록 → 자동 발행 불가.
X/YouTube 발행 스테이지는 파일럿 ID 를 거부한다.

## 6. 배포 순서

1. Supabase: `migrations/2026_09_25_video_assets_media_manifest.sql` 적용 (미적용이어도 코드는 manifest 제외 후 동작)
2. 파일 업로드 (본 문서 체크리스트)
3. 파일럿 실행 → 텔레그램 검토본 확인
4. 승인 시 repo Variable `WEEKLY_FORMAT=v2`

## 7. 검증

- 단위/통합 테스트: `tests/test_weekly_v2.py`, `tests/test_weekly_v2_media_render.py`
- E2E(외부 API 가짜, 코드·ffmpeg·DB 전이 실제): gate→narrative→media→assembly→notify 통과,
  최종 15.70초 · 1080×1920 · 정지 0 · -14 LUFS, 파일럿 release_at 미기록, 발행 리졸버 미선택.
