-- ============================================================
-- ICG Phase 2.3 — Pair Tension + Narrative Depth Migration
-- DATE: 2026-05-14
-- AUTHOR: PM팀 (Claude)
-- SCOPE:
--   1. icg.arc_state — pair_tension(JSONB) + edt_pressure(float) 추가
--   2. icg.arc_state — emergence_deficit_days(int) 추가 (RULE EMR-01)
--   3. icg.daily_analysis — pair_tension(JSONB) + edt_pressure(float) 스냅샷
--   4. icg.daily_analysis — battle_modifiers(JSONB) 진단 컬럼
-- DEPENDS_ON:
--   - 기존 icg.arc_state (id=1 단일 행)
-- ROLLBACK: DROP COLUMN으로 100% 복구 가능
-- ============================================================

-- ── 1. icg.arc_state 컬럼 추가 ───────────────────────────────
ALTER TABLE icg.arc_state
  ADD COLUMN IF NOT EXISTS pair_tension JSONB
    DEFAULT '{"PAIR_A": 0, "PAIR_B": 0, "PAIR_C": 0}'::jsonb,
  ADD COLUMN IF NOT EXISTS edt_pressure NUMERIC(5,2)
    DEFAULT 0.0,
  ADD COLUMN IF NOT EXISTS emergence_deficit_days INTEGER
    DEFAULT 0;

-- 기존 단일 행 (id=1) 강제 초기화 (옵션 A 권장 — 모두 0)
UPDATE icg.arc_state
SET pair_tension = '{"PAIR_A": 0, "PAIR_B": 0, "PAIR_C": 0}'::jsonb,
    edt_pressure = 0.0,
    emergence_deficit_days = COALESCE(emergence_deficit_days, 0)
WHERE id = 1
  AND pair_tension IS NULL;

-- ── 2. icg.daily_analysis 스냅샷 컬럼 추가 ───────────────────
ALTER TABLE icg.daily_analysis
  ADD COLUMN IF NOT EXISTS pair_tension JSONB,
  ADD COLUMN IF NOT EXISTS edt_pressure NUMERIC(5,2),
  ADD COLUMN IF NOT EXISTS triggered_pair TEXT,
  ADD COLUMN IF NOT EXISTS battle_modifiers JSONB;

-- battle_modifiers 구조:
-- {
--   "crowd_momentum_modifier": 2,
--   "villain_signature_bonus": 8,
--   "emergence_deficit": -10,
--   "form_bonus": 0
-- }

-- ── 3. 인덱스 (관측성용) ─────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_daily_analysis_triggered_pair
  ON icg.daily_analysis (triggered_pair)
  WHERE triggered_pair IS NOT NULL;

-- ── 4. 검증 쿼리 (마이그레이션 후 실행 권장) ──────────────────
-- SELECT id, pair_tension, edt_pressure, emergence_deficit_days
--   FROM icg.arc_state WHERE id = 1;
-- 결과 예시:
-- id | pair_tension                                      | edt_pressure | emergence_deficit_days
--  1 | {"PAIR_A": 0, "PAIR_B": 0, "PAIR_C": 0}          | 0.00         | 0

-- ── ROLLBACK SQL (필요 시) ────────────────────────────────────
-- ALTER TABLE icg.arc_state
--   DROP COLUMN IF EXISTS pair_tension,
--   DROP COLUMN IF EXISTS edt_pressure,
--   DROP COLUMN IF EXISTS emergence_deficit_days;
-- ALTER TABLE icg.daily_analysis
--   DROP COLUMN IF EXISTS pair_tension,
--   DROP COLUMN IF EXISTS edt_pressure,
--   DROP COLUMN IF EXISTS triggered_pair,
--   DROP COLUMN IF EXISTS battle_modifiers;
-- DROP INDEX IF EXISTS idx_daily_analysis_triggered_pair;
