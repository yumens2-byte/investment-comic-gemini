-- Run BEFORE 0001: confirms the main columns the contract views depend on exist.
-- Expected: every row returns present = true. Read-only.
with expected(table_name, column_name) as (values
  ('episode_assets','episode_date'),('episode_assets','episode_no'),('episode_assets','status'),
  ('episode_assets','event_type'),('episode_assets','scenario_type'),('episode_assets','heroes_json'),
  ('episode_assets','battle_json'),('episode_assets','script_json'),
  ('daily_snapshots','snapshot_date'),('daily_snapshots','us10y'),('daily_snapshots','vix'),
  ('daily_snapshots','oil_wti'),('daily_snapshots','spy_change'),('daily_snapshots','nasdaq_change'),
  ('daily_snapshots','dollar_index'),('daily_snapshots','hy_spread'),('daily_snapshots','fear_greed'),
  ('arc_state','id'),('arc_state','arc_day'),('arc_state','arc_tension'),('arc_state','hero_momentum'),
  ('arc_state','active_villain'),('arc_state','last_outcome'),('arc_state','last_episode_date'),
  ('published_comics','publish_date'),('published_comics','episode_no'),
  ('daily_analysis','analysis_date')
)
select e.table_name, e.column_name,
       exists (select 1 from information_schema.columns c
               where c.table_schema = 'icg' and c.table_name = e.table_name
                 and c.column_name = e.column_name) as present
from expected e order by present, e.table_name, e.column_name;
