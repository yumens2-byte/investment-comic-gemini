# 전투씬 영상 Add-on 상세설계 (2026-06-20)

## 목표

기존 이미지 생성 + PIL 조립 + 이미지 업로드 프로세스를 기본/정본 경로로 유지하면서, 전투 이벤트에 한해 짧은 전투씬 mp4를 추가 업로드한다. 영상 자산이 없거나 영상 업로드가 실패해도 기존 이미지 발행은 롤백하지 않는다.

## 적용 범위

- 적용 이벤트: `BATTLE`, `BATTLE_PLUS`, `BATTLE_PLUS_FORM2`, `BATTLE_PLUS_FORM3`
- 적용 채널: `telegram`, `x`, `all`
- 비적용 이벤트(`SHOCK`, `AFTERMATH`, `NORMAL` 등)는 기존 이미지/PIL 경로만 실행한다.

## 자산 계약

`episode_assets` row에서 다음 중 하나로 로컬 mp4 경로를 찾는다.

1. Top-level string
   - `battle_video_path`
   - `final_video_path`
   - `video_path`
2. Nested JSON
   - `battle_video_json`
   - `video_json`
   - `video_assets`
3. Nested path key
   - `path`
   - `video_path`
   - `final_mp4_path`
   - `final_video_path`
   - `video_uri`
   - `uri`

경로가 없거나 파일이 존재하지 않으면 `STEP_8_VIDEO` 로그만 남기고 이미지 발행 결과는 유지한다.

## 발행 순서

1. 기존 X 이미지 스레드 발행
2. 기존 Telegram 이미지 앨범 발행
3. 전투씬 영상 add-on plan 생성
4. plan이 `ready`이면 Telegram video 발행
5. plan이 `ready`이면 X chunked video 발행
6. 기존 `record_publish` 호출

## 실패 격리 원칙

- 영상 add-on은 `engine.publish.battle_video_publish`에서 plan만 생성한다.
- `scripts.run_publish`는 기존 이미지 발행 완료 후 영상 add-on을 실행한다.
- 영상 업로드 예외는 `STEP_8_TG_VIDEO` 또는 `STEP_8_X_VIDEO`에 기록하고, 이미지 발행 완료 상태를 되돌리지 않는다.
- 영상 파일 부재는 에러가 아닌 스킵으로 취급한다.

## 품질 게이트

- Unit: 전투 이벤트 게이트, 자산 경로 추출, caption limit, plan 상태 검증
- Publisher: Telegram Bot API `sendVideo` 호출 형식, X chunked upload 호출 형식 검증
- Regression: 기존 `run_publish` 메이저 이벤트 게이트 테스트 유지
- Syntax: `scripts/run_publish.py`, `engine/publish/*video*.py` py_compile

## 운영 메모

- Telegram 실발행 환경변수: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_FREE_CHANNEL_ID`
- X 실발행 환경변수: `X_API_KEY`, `X_API_SECRET`, `X_ACCESS_TOKEN`, `X_ACCESS_SECRET` 또는 `X_ACCESS_TOKEN_SECRET`
- 기본 dry-run은 기존 `DRY_RUN` 환경변수를 따른다.
