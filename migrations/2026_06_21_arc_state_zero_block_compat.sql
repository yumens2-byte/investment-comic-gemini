-- ============================================================
-- ICG Arc State zero_block compatibility migration
-- DATE: 2026-06-21
-- SCOPE:
--   Add the optional zero_block_just_appeared flag used by Phase 2.3
--   pair-tension trigger suppression.
-- ============================================================

ALTER TABLE icg.arc_state
  ADD COLUMN IF NOT EXISTS zero_block_just_appeared BOOLEAN DEFAULT FALSE;

UPDATE icg.arc_state
SET zero_block_just_appeared = COALESCE(zero_block_just_appeared, FALSE)
WHERE id = 1;

-- ROLLBACK:
-- ALTER TABLE icg.arc_state DROP COLUMN IF EXISTS zero_block_just_appeared;
