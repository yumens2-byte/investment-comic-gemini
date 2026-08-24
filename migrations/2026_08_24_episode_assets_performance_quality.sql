-- Structured image-performance validation result produced during STEP_6.
-- The application treats this observability field as optional so code and
-- migration deployments can occur safely in either order.
ALTER TABLE icg.episode_assets
  ADD COLUMN IF NOT EXISTS performance_quality_json JSONB;

