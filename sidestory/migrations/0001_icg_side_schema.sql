-- SIDESTORY P0 — icg_side schema (2026-10-05)
-- Main schema icg is NOT altered: this file only creates objects inside icg_side
-- and read-only views/functions that SELECT from icg.
-- Apply via Supabase SQL editor or CLI. After applying, add `icg_side` to the
-- PostgREST exposed schemas (Supabase dashboard → API settings) if not exposed.

begin;

create schema icg_side;
revoke all on schema icg_side from public, anon, authenticated;
grant usage on schema icg_side to service_role;

-- ── Side episodes ────────────────────────────────────────────────────────────
create table icg_side.side_episodes (
  side_episode_id text primary key check (side_episode_id ~ '^SIDE-\d{4}-\d{2}-\d{2}-\d{2}$'),
  episode_date date not null,
  format text not null default 'nn_log'
    check (format in ('nn_log','world','character','villain')),
  anchor_main_episode text not null check (anchor_main_episode ~ '^ICG-\d{4}-\d{2}-\d{2}-\d{3}$'),
  outcome_class text not null check (outcome_class in ('VICTORY','DRAW','DEFEAT','NO_BATTLE')),
  status text not null default 'draft'
    check (status in ('draft','narrative_done','image_done','assembled','publishing','published','hold')),
  echo_pack_json jsonb not null,
  script_json jsonb,
  panels_json jsonb,
  slides_json jsonb,
  manifest_json jsonb,
  publish_hold text,
  error_message text,
  created_at timestamptz not null default clock_timestamp(),
  updated_at timestamptz not null default clock_timestamp()
);
-- One side story per main anchor (prevents echoing the same main episode twice).
create unique index side_episodes_anchor_uidx on icg_side.side_episodes(anchor_main_episode);

create table icg_side.side_publications (
  id bigserial primary key,
  side_episode_id text not null references icg_side.side_episodes(side_episode_id),
  channel text not null check (channel in ('facebook')),
  post_id text,
  photo_ids jsonb not null default '[]'::jsonb,
  dry_run boolean not null,
  published_at timestamptz not null default clock_timestamp()
);
create unique index side_publications_live_uidx
  on icg_side.side_publications(side_episode_id, channel) where dry_run = false;

create table icg_side.side_run_logs (
  id bigserial primary key,
  stage text not null,
  status text not null,
  detail jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default clock_timestamp()
);

alter table icg_side.side_episodes enable row level security;
alter table icg_side.side_publications enable row level security;
alter table icg_side.side_run_logs enable row level security;
revoke all on all tables in schema icg_side from public, anon, authenticated;
grant select, insert, update on icg_side.side_episodes, icg_side.side_publications,
  icg_side.side_run_logs to service_role;
grant usage on all sequences in schema icg_side to service_role;

-- ── Main → side contract views (read-only, versioned) ────────────────────────
create view icg_side.main_feed_episode_v1 as
select e.episode_date::text as episode_date,
       e.episode_no,
       e.event_type,
       e.scenario_type,
       coalesce(e.heroes_json, '[]'::jsonb) as heroes_json,
       coalesce(e.battle_json, '{}'::jsonb) as battle_json,
       jsonb_strip_nulls(jsonb_build_object(
         'title', e.script_json->'title',
         'logline', e.script_json->'logline',
         'panels', e.script_json->'panels',
         'next_hook', e.script_json->'next_hook',
         'unresolved_threads', e.script_json->'unresolved_threads',
         '_continuity', e.script_json->'_continuity'
       )) as script_json
from icg.episode_assets e
where e.status = 'published';

create view icg_side.main_feed_market_v1 as
select s.snapshot_date::text as snapshot_date,
       s.us10y, s.vix, s.oil_wti, s.spy_change, s.nasdaq_change,
       s.dollar_index, s.hy_spread, s.fear_greed
from icg.daily_snapshots s;

create view icg_side.main_feed_arc_v1 as
select a.arc_day, a.arc_tension, a.hero_momentum, a.active_villain,
       a.last_outcome, a.last_episode_date::text as last_episode_date
from icg.arc_state a
where a.id = 1;

revoke all on icg_side.main_feed_episode_v1, icg_side.main_feed_market_v1,
  icg_side.main_feed_arc_v1 from public, anon, authenticated;
grant select on icg_side.main_feed_episode_v1, icg_side.main_feed_market_v1,
  icg_side.main_feed_arc_v1 to service_role;

-- ── Main protection fingerprint (SG-1 / SG-7) ────────────────────────────────
-- Read-only hash of the main rows the side track must never change.
create function icg_side.main_state_fingerprint(p_date date)
returns text language sql stable security definer set search_path = '' as $$
  select encode(pg_catalog.sha256(convert_to(coalesce((
    select jsonb_build_object(
      'arc',  (select to_jsonb(a) from icg.arc_state a where a.id = 1),
      'eps',  (select coalesce(jsonb_agg(to_jsonb(e) order by e.episode_no), '[]'::jsonb)
                 from icg.episode_assets e where e.episode_date = p_date),
      'pub',  (select coalesce(jsonb_agg(to_jsonb(p) order by p.episode_no), '[]'::jsonb)
                 from icg.published_comics p where p.publish_date = p_date),
      'ana',  (select to_jsonb(d) from icg.daily_analysis d where d.analysis_date = p_date)
    )::text), ''), 'UTF8')), 'hex');
$$;
revoke all on function icg_side.main_state_fingerprint(date) from public, anon, authenticated;
grant execute on function icg_side.main_state_fingerprint(date) to service_role;

-- ── Image generation ledger (clone of icg v1 guard, side-only budget) ────────
-- engine/image/generation_guard.py calls these via SUPABASE_SCHEMA=icg_side with
-- ICG_GENERATION_REVISION=1. Budgets are separate from (and smaller than) main.
create table icg_side.image_generation_calls (
 token uuid primary key default gen_random_uuid(), scope text not null,
 panel integer not null check(panel>0), fingerprint text not null,
 state text not null check(state in ('reserved','success','failed','terminal','unknown')),
 cost numeric not null default 0.10 check(cost>=0), output_hash text,
 created_at timestamptz not null default clock_timestamp()
);
create index side_image_generation_scope_idx on icg_side.image_generation_calls(scope,panel);
create index side_image_generation_created_idx on icg_side.image_generation_calls(created_at);
alter table icg_side.image_generation_calls enable row level security;
revoke all on icg_side.image_generation_calls from public,anon,authenticated;
grant select,insert,update on icg_side.image_generation_calls to service_role;

create function icg_side.image_generation_inspect(p_scope text,p_panel integer,p_fingerprint text)
returns jsonb language plpgsql security invoker set search_path='' as $$
declare r record;
begin
 if p_scope is null or p_panel is null or p_fingerprint is null or length(p_scope)>500 or p_scope='' or p_panel<=0 or p_fingerprint !~ '^[0-9a-f]{64}$'
 or p_scope !~ '^output/sidestory/[0-9]{4}-[0-9]{2}-[0-9]{2}/panels$'
 then return jsonb_build_object('hold','invalid identity'); end if;
 if exists(select 1 from icg_side.image_generation_calls where scope=p_scope
 and state in ('reserved','unknown','terminal'))
 then return jsonb_build_object('hold','scope requires reconciliation'); end if;
 if exists(select 1 from icg_side.image_generation_calls where scope=p_scope and panel=p_panel
 and fingerprint<>p_fingerprint)
 then return jsonb_build_object('hold','artifact identity changed'); end if;
 select * into r from icg_side.image_generation_calls where scope=p_scope and panel=p_panel
 and state='success' order by created_at desc limit 1;
 if found then return jsonb_build_object('output_hash',r.output_hash); end if;
 return '{}'::jsonb;
end $$;

create function icg_side.image_generation_reserve(p_scope text,p_panel integer,p_fingerprint text)
returns jsonb language plpgsql security invoker set search_path='' as $$
declare receipt jsonb; t uuid;
begin
 perform pg_catalog.pg_advisory_xact_lock(731093,1);
 receipt:=icg_side.image_generation_inspect(p_scope,p_panel,p_fingerprint);
 if receipt ? 'hold' then return receipt; end if;
 if receipt ? 'output_hash' then return jsonb_build_object('hold','already generated'); end if;
 if (select count(*) from icg_side.image_generation_calls
 where created_at>=date_trunc('day',now() at time zone 'UTC') at time zone 'UTC')>=20
 or (select count(*) from icg_side.image_generation_calls
 where created_at>=date_trunc('month',now() at time zone 'UTC') at time zone 'UTC')>=120
 or (select count(*) from icg_side.image_generation_calls where scope=p_scope and panel=p_panel)>=3
 or (select count(*) from icg_side.image_generation_calls where scope=p_scope)>=20
 or coalesce((select sum(cost) from icg_side.image_generation_calls where scope=p_scope),0)+0.10>2
 or coalesce((select sum(cost) from icg_side.image_generation_calls
 where created_at>=date_trunc('day',now() at time zone 'UTC') at time zone 'UTC'),0)+0.10>2
 or coalesce((select sum(cost) from icg_side.image_generation_calls
 where created_at>=date_trunc('month',now() at time zone 'UTC') at time zone 'UTC'),0)+0.10>12
 then return jsonb_build_object('hold','generation budget exhausted'); end if;
 insert into icg_side.image_generation_calls(scope,panel,fingerprint,state)
 values(p_scope,p_panel,p_fingerprint,'reserved') returning token into t;
 return jsonb_build_object('token',t);
end $$;

create function icg_side.image_generation_finish(p_scope text,p_panel integer,p_fingerprint text,
 p_token uuid,p_state text,p_actual_cost numeric,p_output_hash text)
returns jsonb language plpgsql security invoker set search_path='' as $$
declare final_state text; changed integer;
begin
 perform pg_catalog.pg_advisory_xact_lock(731093,1);
 if p_state is null or p_token is null or p_scope is null or p_panel is null
 or p_fingerprint is null or p_state not in ('success','failed','terminal','unknown')
 or (p_actual_cost is not null and (p_actual_cost<0 or p_actual_cost::text in ('NaN','Infinity','-Infinity')))
 or (p_state='success' and coalesce(p_output_hash,'') !~ '^[0-9a-f]{64}$')
 then return jsonb_build_object('hold','invalid settlement'); end if;
 final_state:=case when p_actual_cost is null then 'unknown' else p_state end;
 if p_actual_cost>0.10 then final_state:='terminal'; end if;
 update icg_side.image_generation_calls set state=final_state,
 cost=coalesce(p_actual_cost,cost),output_hash=p_output_hash
 where token=p_token and scope=p_scope and panel=p_panel and fingerprint=p_fingerprint
 and state='reserved';
 get diagnostics changed=row_count;
 if changed<>1 then return jsonb_build_object('hold','stale settlement token'); end if;
 if final_state in ('unknown','terminal')
 then return jsonb_build_object('hold','provider outcome or cost requires reconciliation'); end if;
 return jsonb_build_object('settled',true);
end $$;
revoke execute on function icg_side.image_generation_inspect(text,integer,text) from public,anon,authenticated;
revoke execute on function icg_side.image_generation_reserve(text,integer,text) from public,anon,authenticated;
revoke execute on function icg_side.image_generation_finish(text,integer,text,uuid,text,numeric,text) from public,anon,authenticated;
grant execute on function icg_side.image_generation_inspect(text,integer,text) to service_role;
grant execute on function icg_side.image_generation_reserve(text,integer,text) to service_role;
grant execute on function icg_side.image_generation_finish(text,integer,text,uuid,text,numeric,text) to service_role;

commit;

notify pgrst, 'reload schema';
