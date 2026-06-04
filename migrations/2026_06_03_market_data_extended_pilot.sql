-- ============================================================
-- ICG Market Data Extended Pilot — sector/risk/formula observability
-- DATE: 2026-06-03
-- SCOPE:
--   1. icg.daily_snapshots JSONB fields for extended market data pilot
--   2. icg.daily_analysis JSONB fields for composite risk and formula traces
--   3. optional normalized icg.daily_market_signals table for later backtests
-- ============================================================

ALTER TABLE icg.daily_snapshots
  ADD COLUMN IF NOT EXISTS sector_heatmap JSONB,
  ADD COLUMN IF NOT EXISTS market_breadth JSONB,
  ADD COLUMN IF NOT EXISTS rates_detail JSONB,
  ADD COLUMN IF NOT EXISTS credit_detail JSONB,
  ADD COLUMN IF NOT EXISTS fx_detail JSONB,
  ADD COLUMN IF NOT EXISTS commodity_detail JSONB,
  ADD COLUMN IF NOT EXISTS event_calendar JSONB,
  ADD COLUMN IF NOT EXISTS news_items JSONB,
  ADD COLUMN IF NOT EXISTS signal_quality JSONB;

ALTER TABLE icg.daily_analysis
  ADD COLUMN IF NOT EXISTS risk_drivers JSONB,
  ADD COLUMN IF NOT EXISTS sector_rank JSONB,
  ADD COLUMN IF NOT EXISTS asset_rank JSONB,
  ADD COLUMN IF NOT EXISTS watch_areas JSONB,
  ADD COLUMN IF NOT EXISTS caution_areas JSONB,
  ADD COLUMN IF NOT EXISTS formula_trace JSONB;

CREATE TABLE IF NOT EXISTS icg.daily_market_signals (
  signal_date DATE NOT NULL,
  signal_id TEXT NOT NULL,
  domain TEXT NOT NULL,
  symbol TEXT,
  name TEXT,
  value NUMERIC,
  change_pct NUMERIC,
  relative_pct NUMERIC,
  z_score NUMERIC,
  state TEXT,
  story_role TEXT,
  scene_symbol TEXT,
  source TEXT,
  confidence NUMERIC,
  raw JSONB,
  created_at TIMESTAMPTZ DEFAULT now(),
  PRIMARY KEY (signal_date, signal_id)
);

CREATE INDEX IF NOT EXISTS idx_daily_market_signals_domain
  ON icg.daily_market_signals (signal_date, domain);

CREATE INDEX IF NOT EXISTS idx_daily_analysis_formula_trace_gin
  ON icg.daily_analysis USING GIN (formula_trace);

CREATE INDEX IF NOT EXISTS idx_daily_analysis_sector_rank_gin
  ON icg.daily_analysis USING GIN (sector_rank);

-- ROLLBACK (manual):
-- DROP INDEX IF EXISTS icg.idx_daily_analysis_sector_rank_gin;
-- DROP INDEX IF EXISTS icg.idx_daily_analysis_formula_trace_gin;
-- DROP INDEX IF EXISTS icg.idx_daily_market_signals_domain;
-- DROP TABLE IF EXISTS icg.daily_market_signals;
-- ALTER TABLE icg.daily_analysis
--   DROP COLUMN IF EXISTS risk_drivers,
--   DROP COLUMN IF EXISTS sector_rank,
--   DROP COLUMN IF EXISTS asset_rank,
--   DROP COLUMN IF EXISTS watch_areas,
--   DROP COLUMN IF EXISTS caution_areas,
--   DROP COLUMN IF EXISTS formula_trace;
-- ALTER TABLE icg.daily_snapshots
--   DROP COLUMN IF EXISTS sector_heatmap,
--   DROP COLUMN IF EXISTS market_breadth,
--   DROP COLUMN IF EXISTS rates_detail,
--   DROP COLUMN IF EXISTS credit_detail,
--   DROP COLUMN IF EXISTS fx_detail,
--   DROP COLUMN IF EXISTS commodity_detail,
--   DROP COLUMN IF EXISTS event_calendar,
--   DROP COLUMN IF EXISTS news_items,
--   DROP COLUMN IF EXISTS signal_quality;
