-- Publish Shorts의 만료된 승인 대기 건 조회를 위한 인덱스.
-- status 동등 조건 + release_at 범위/정렬을 인덱스에서 처리하고,
-- 이미 YouTube에 발행된 행은 인덱스에서 제외한다.
CREATE INDEX IF NOT EXISTS idx_video_assets_pending_release
  ON icg.video_assets (status, release_at DESC)
  WHERE youtube_video_id IS NULL;
