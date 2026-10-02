-- Manual canary evidence for re-enabling dormant generation paths (design DR-04).
-- Records outcomes only; budgets remain enforced by icg.image_generation_calls.
create table if not exists icg.path_canary_runs (
  id uuid primary key default gen_random_uuid(),
  path_key text not null,
  status text not null check (status in ('pass', 'refused', 'error')),
  finish_reason text,
  cost numeric check (cost is null or cost >= 0),
  fingerprint text check (fingerprint is null or fingerprint ~ '^[0-9a-f]{64}$'),
  run_id text,
  created_at timestamptz not null default clock_timestamp()
);
create index if not exists path_canary_runs_lookup_idx
  on icg.path_canary_runs (path_key, status, created_at desc);
alter table icg.path_canary_runs enable row level security;
revoke all on icg.path_canary_runs from public, anon, authenticated;
grant select, insert on icg.path_canary_runs to service_role;
notify pgrst, 'reload schema';
