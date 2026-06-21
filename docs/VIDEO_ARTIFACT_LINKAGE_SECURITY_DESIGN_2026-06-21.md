# Video Artifact Linkage Security Design (2026-06-21)

## 배경

전투씬 영상 add-on 발행은 `publish_sns.yml` 실행 환경에 mp4 파일이 있어야 한다. 이전 방식처럼 GitHub repository artifact 목록에서 최신 `video-*`를 broad scan하면 다른 날짜/다른 에피소드의 artifact를 잘못 내려받을 수 있고, 불필요하게 repository artifact 목록 조회 권한에 의존한다.

## 결정

1. `run_video_trailer.yml` 실행 중 `GITHUB_RUN_ID`를 `icg.video_assets.artifact_run_id`에 저장한다.
2. `scripts.resolve_episode`는 `episode_id`로 `icg.video_assets`를 조회하고 명시 저장된 run id만 `video_run_id`로 출력한다.
3. `publish_sns.yml`은 `video_run_id`가 있을 때만 `actions/download-artifact`를 호출한다.
4. `scripts.run_publish`는 다운로드된 `output/videos/<episode_id>/*.mp4`와 DB의 `cut1_video_uri`/`video_path` 계열 필드만 발행 후보로 사용한다.
5. `artifact_run_id` 컬럼이 아직 배포되지 않은 환경에서도 영상 생성 자체가 실패하지 않도록 `run_video_trailer.py`는 해당 컬럼 누락 시 payload에서 제거하고 1회 재시도한다.

## 보안 원칙

- Repository-wide artifact scan 금지.
- 에피소드 ID와 DB에 저장된 artifact run id로만 다운로드 범위를 좁힌다.
- 영상 add-on 실패는 기존 이미지 발행을 롤백하지 않는다.
- 경로 문자열만으로 발행하지 않고 로컬 mp4 존재 확인을 거친다.

## 운영 체크리스트

1. Supabase에 `migrations/2026_06_21_video_assets_artifact_run_id.sql` 적용.
2. `Run Video Trailer`를 `operation_mode=full_pipeline`, 실제 생성 시 `dry_run=false`로 실행.
3. `icg.video_assets.artifact_run_id`와 `cut1_video_uri`가 같은 `episode_id`에 저장되었는지 확인.
4. `Publish SNS` 실행 로그에서 `video_run_id`와 `output/videos/**/*.mp4` 확인.
