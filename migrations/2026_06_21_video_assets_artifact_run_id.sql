-- Link generated video artifacts to publish_sns.yml without repository-wide artifact scanning.
-- Safe to apply repeatedly.
ALTER TABLE icg.video_assets
  ADD COLUMN IF NOT EXISTS artifact_run_id text;

CREATE INDEX IF NOT EXISTS idx_video_assets_artifact_run_id
  ON icg.video_assets (artifact_run_id)
  WHERE artifact_run_id IS NOT NULL;
