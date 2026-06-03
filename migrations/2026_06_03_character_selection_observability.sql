-- ============================================================
-- ICG Character Selection Observability Migration
-- DATE: 2026-06-03
-- SCOPE:
--   1. icg.daily_analysis — character_selection JSONB + reporting summary columns
--   2. icg.episode_assets — optional final episode snapshot columns
--   3. icg.character_selection_candidates — optional candidate-level fact table
-- ROLLBACK: DROP COLUMN/TABLE/INDEX statements at bottom.
-- ============================================================

-- ── 1. daily_analysis 관측성 컬럼 ─────────────────────────────
ALTER TABLE icg.daily_analysis
  ADD COLUMN IF NOT EXISTS character_selection JSONB,
  ADD COLUMN IF NOT EXISTS character_selector_version TEXT,
  ADD COLUMN IF NOT EXISTS character_selector_mode TEXT,
  ADD COLUMN IF NOT EXISTS selected_hero_id TEXT,
  ADD COLUMN IF NOT EXISTS selected_villain_id TEXT,
  ADD COLUMN IF NOT EXISTS support_heroes_json JSONB DEFAULT '[]'::jsonb,
  ADD COLUMN IF NOT EXISTS neutral_guests_json JSONB DEFAULT '[]'::jsonb,
  ADD COLUMN IF NOT EXISTS top_hero_score INTEGER,
  ADD COLUMN IF NOT EXISTS top_villain_score INTEGER,
  ADD COLUMN IF NOT EXISTS neutral_guest_count INTEGER DEFAULT 0,
  ADD COLUMN IF NOT EXISTS character_selection_reason TEXT;

CREATE INDEX IF NOT EXISTS idx_daily_analysis_selected_hero
  ON icg.daily_analysis (selected_hero_id);

CREATE INDEX IF NOT EXISTS idx_daily_analysis_selected_villain
  ON icg.daily_analysis (selected_villain_id);

CREATE INDEX IF NOT EXISTS idx_daily_analysis_character_selector_version
  ON icg.daily_analysis (character_selector_version);

CREATE INDEX IF NOT EXISTS idx_daily_analysis_character_selection_gin
  ON icg.daily_analysis USING GIN (character_selection);

-- ── 2. episode_assets 최종 산출물 snapshot 컬럼 (선택 저장) ─────
ALTER TABLE icg.episode_assets
  ADD COLUMN IF NOT EXISTS character_selection_json JSONB,
  ADD COLUMN IF NOT EXISTS active_character_cards_json JSONB;

CREATE INDEX IF NOT EXISTS idx_episode_assets_character_selection_gin
  ON icg.episode_assets USING GIN (character_selection_json);

-- ── 3. 후보별 상세 fact table (점수 튜닝/리포팅용) ─────────────
CREATE TABLE IF NOT EXISTS icg.character_selection_candidates (
  id BIGSERIAL PRIMARY KEY,
  analysis_date DATE NOT NULL,
  event_type TEXT NOT NULL,
  scenario_type TEXT,
  risk_level TEXT,
  selector_version TEXT,
  char_id TEXT NOT NULL,
  faction TEXT NOT NULL,
  role TEXT,
  appear BOOLEAN NOT NULL DEFAULT FALSE,
  selected BOOLEAN NOT NULL DEFAULT FALSE,
  score INTEGER NOT NULL DEFAULT 0,
  threshold INTEGER NOT NULL DEFAULT 0,
  rank INTEGER,
  reasons JSONB DEFAULT '[]'::jsonb,
  score_breakdown JSONB DEFAULT '{}'::jsonb,
  metrics_used JSONB DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_character_selection_candidate
  ON icg.character_selection_candidates (analysis_date, event_type, char_id, faction);

CREATE INDEX IF NOT EXISTS idx_character_selection_candidates_char_date
  ON icg.character_selection_candidates (char_id, analysis_date DESC);

CREATE INDEX IF NOT EXISTS idx_character_selection_candidates_selected
  ON icg.character_selection_candidates (selected, faction, analysis_date DESC);

CREATE INDEX IF NOT EXISTS idx_character_selection_candidates_score
  ON icg.character_selection_candidates (faction, score DESC);

-- ── 4. 운영 검증 쿼리 ────────────────────────────────────────
-- SELECT analysis_date, selected_hero_id, selected_villain_id,
--        top_hero_score, top_villain_score, character_selection_reason
-- FROM icg.daily_analysis
-- ORDER BY analysis_date DESC
-- LIMIT 7;
--
-- SELECT analysis_date, char_id, faction, score, threshold, selected
-- FROM icg.character_selection_candidates
-- WHERE analysis_date >= CURRENT_DATE - 7
-- ORDER BY analysis_date DESC, faction, rank NULLS LAST;

-- ── ROLLBACK SQL (필요 시) ────────────────────────────────────
-- DROP INDEX IF EXISTS icg.idx_character_selection_candidates_score;
-- DROP INDEX IF EXISTS icg.idx_character_selection_candidates_selected;
-- DROP INDEX IF EXISTS icg.idx_character_selection_candidates_char_date;
-- DROP INDEX IF EXISTS icg.uq_character_selection_candidate;
-- DROP TABLE IF EXISTS icg.character_selection_candidates;
-- DROP INDEX IF EXISTS icg.idx_episode_assets_character_selection_gin;
-- ALTER TABLE icg.episode_assets
--   DROP COLUMN IF EXISTS character_selection_json,
--   DROP COLUMN IF EXISTS active_character_cards_json;
-- DROP INDEX IF EXISTS icg.idx_daily_analysis_character_selection_gin;
-- DROP INDEX IF EXISTS icg.idx_daily_analysis_character_selector_version;
-- DROP INDEX IF EXISTS icg.idx_daily_analysis_selected_villain;
-- DROP INDEX IF EXISTS icg.idx_daily_analysis_selected_hero;
-- ALTER TABLE icg.daily_analysis
--   DROP COLUMN IF EXISTS character_selection,
--   DROP COLUMN IF EXISTS character_selector_version,
--   DROP COLUMN IF EXISTS character_selector_mode,
--   DROP COLUMN IF EXISTS selected_hero_id,
--   DROP COLUMN IF EXISTS selected_villain_id,
--   DROP COLUMN IF EXISTS support_heroes_json,
--   DROP COLUMN IF EXISTS neutral_guests_json,
--   DROP COLUMN IF EXISTS top_hero_score,
--   DROP COLUMN IF EXISTS top_villain_score,
--   DROP COLUMN IF EXISTS neutral_guest_count,
--   DROP COLUMN IF EXISTS character_selection_reason;
