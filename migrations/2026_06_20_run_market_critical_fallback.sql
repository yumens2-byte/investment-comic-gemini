-- ============================================================
-- ICG run_market Critical Fallback Observability
-- DATE: 2026-06-20
-- SCOPE:
--   Store source/fallback/freshness metadata emitted by CriticalFallbackResolver.
-- ============================================================

ALTER TABLE icg.daily_snapshots
  ADD COLUMN IF NOT EXISTS data_quality JSONB;

CREATE INDEX IF NOT EXISTS idx_daily_snapshots_data_quality_gin
  ON icg.daily_snapshots USING GIN (data_quality);

-- ROLLBACK (manual):
-- DROP INDEX IF EXISTS icg.idx_daily_snapshots_data_quality_gin;
-- ALTER TABLE icg.daily_snapshots DROP COLUMN IF EXISTS data_quality;
