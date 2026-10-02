-- Deployment proposal. Apply after image-generation-revision.sql.
-- This adds receipts; it never rewrites/deletes a provider call or resets a budget.
create table icg.image_generation_recovery_receipts (
 terminal_token uuid not null references icg.image_generation_calls(token),
 target_revision integer not null check(target_revision between 2 and 100),
 scope text not null, actual_cost numeric not null check(actual_cost>=0),
 script_json jsonb not null, fingerprints jsonb not null, evidence text not null,
 created_at timestamptz not null default clock_timestamp(),
 primary key(terminal_token,target_revision)
);
alter table icg.image_generation_recovery_receipts enable row level security;
revoke all on icg.image_generation_recovery_receipts from public,anon,authenticated,service_role;
grant select,insert on icg.image_generation_recovery_receipts to service_role;

create function icg.image_generation_recovery_preflight(p_scope text,p_revision integer)
returns jsonb language plpgsql security invoker set search_path='' as $$
declare current_script jsonb;
begin
 if p_scope is null or p_revision is null or p_revision not between 2 and 100
 or p_scope !~ '^output/episodes/[0-9]{4}-[0-9]{2}-[0-9]{2}/panels$'
 then return jsonb_build_object('hold','invalid recovery identity'); end if;
 select e.script_json into current_script from icg.episode_assets e
 where 'output/episodes/'||e.episode_date::text||'/panels'=p_scope and e.episode_no=1
 and e.status='narrative_done' and e.script_json->>'_generation_revision'=p_revision::text
 and e.script_json->'_state_candidate'->>'version'='state-candidate-1';
 if not found then return jsonb_build_object('hold','revision not authorized by current narrative'); end if;
 if exists(select 1 from icg.image_generation_calls c where c.scope=p_scope
 and (c.state in ('reserved','unknown') or (c.state='terminal' and not exists(
 select 1 from icg.image_generation_recovery_receipts r where r.terminal_token=c.token
 and r.scope=c.scope and r.actual_cost=c.cost and r.target_revision=p_revision
 and r.script_json=current_script and p_revision>c.revision))))
 then return jsonb_build_object('hold','scope requires reconciliation'); end if;
 return jsonb_build_object('authorized',true);
end $$;

create function icg.image_generation_acknowledge_terminal(
 p_token uuid,p_revision integer,p_actual_cost numeric,p_script jsonb,
 p_fingerprints jsonb,p_evidence text)
returns jsonb language plpgsql security invoker set search_path='' as $$
declare c icg.image_generation_calls%rowtype; existing record; current_script jsonb;
 expected_panels jsonb;
begin
 perform pg_catalog.pg_advisory_xact_lock(731091,1);
 select * into c from icg.image_generation_calls where token=p_token for update;
 if not found or c.state<>'terminal' or p_actual_cost is null
 or p_actual_cost::text in ('NaN','Infinity','-Infinity') or c.cost<>p_actual_cost
 or p_revision is null or p_revision<=c.revision or p_revision>100
 or p_evidence is null or length(btrim(p_evidence))<20
 then return jsonb_build_object('hold','terminal settlement evidence invalid'); end if;
 if exists(select 1 from icg.image_generation_calls where scope=c.scope
 and state in ('reserved','unknown'))
 then return jsonb_build_object('hold','unsettled calls remain'); end if;
 select e.script_json into current_script from icg.episode_assets e
 where 'output/episodes/'||e.episode_date::text||'/panels'=c.scope and e.episode_no=1
 and e.status='narrative_done' and e.script_json->>'_generation_revision'=p_revision::text
 and e.script_json->'_state_candidate'->>'version'='state-candidate-1' for update;
 if not found or p_script is null or p_script<>current_script
 then return jsonb_build_object('hold','reviewed script differs from persisted narrative'); end if;
 if jsonb_typeof(p_fingerprints) is distinct from 'object'
 or jsonb_typeof(p_script->'panels') is distinct from 'array'
 then return jsonb_build_object('hold','invalid recovery fingerprints'); end if;
 select coalesce(jsonb_object_agg(p->>'idx',true),'{}'::jsonb) into expected_panels
 from jsonb_array_elements(p_script->'panels') p
 where coalesce(p->>'panel_type','') not in ('TEXT_CARD','DISCLAIMER');
 if expected_panels='{}'::jsonb
 or (select count(*) from jsonb_each(expected_panels))<>
    (select count(*) from jsonb_each(p_fingerprints))
 or exists(select 1 from jsonb_each_text(p_fingerprints) f
 where f.key !~ '^[1-9][0-9]*$' or coalesce(f.value,'') !~ '^[0-9a-f]{64}$'
 or jsonb_typeof(p_fingerprints->f.key)<>'string'
 or not expected_panels ? f.key)
 or coalesce(p_fingerprints->>c.panel::text,'') !~ '^[0-9a-f]{64}$'
 or p_fingerprints->>c.panel::text=c.fingerprint
 then return jsonb_build_object('hold','recovery must bind every scene and change rejected input'); end if;
 select * into existing from icg.image_generation_recovery_receipts
 where terminal_token=p_token and target_revision=p_revision;
 if found then
 if existing.scope<>c.scope or existing.actual_cost<>p_actual_cost
 or existing.script_json<>p_script or existing.fingerprints<>p_fingerprints
 or existing.evidence<>p_evidence
 then return jsonb_build_object('hold','recovery receipt is immutable'); end if;
 else
 insert into icg.image_generation_recovery_receipts
 (terminal_token,target_revision,scope,actual_cost,script_json,fingerprints,evidence)
 values(p_token,p_revision,c.scope,p_actual_cost,p_script,p_fingerprints,p_evidence);
 end if;
 return jsonb_build_object('acknowledged',true,'terminal_token',p_token,'revision',p_revision);
end $$;

create or replace function icg.image_generation_inspect_v2(p_scope text,p_panel integer,p_fingerprint text,p_revision integer)
returns jsonb language plpgsql security invoker set search_path='' as $$
declare r record; receipt jsonb;
begin
 if p_scope is null or p_panel is null or p_fingerprint is null or p_revision is null
 or p_revision<2 or p_revision>100 or p_panel<=0
 or p_scope !~ '^output/episodes/[0-9]{4}-[0-9]{2}-[0-9]{2}/panels$'
 or p_fingerprint !~ '^[0-9a-f]{64}$' then return jsonb_build_object('hold','invalid identity'); end if;
 if not exists(select 1 from icg.episode_assets e
 where 'output/episodes/'||e.episode_date::text||'/panels'=p_scope
 and e.episode_no=1 and e.status='narrative_done'
 and e.script_json->>'_generation_revision'=p_revision::text
 and e.script_json->'_state_candidate'->>'version'='state-candidate-1')
 then return jsonb_build_object('hold','revision not authorized by current narrative'); end if;
 receipt:=icg.image_generation_recovery_preflight(p_scope,p_revision);
 if receipt ? 'hold' then return receipt; end if;
 if exists(select 1 from icg.image_generation_calls c
 join icg.image_generation_recovery_receipts a on a.terminal_token=c.token
 where c.scope=p_scope and c.state='terminal' and a.target_revision=p_revision
 and a.fingerprints->>p_panel::text is distinct from p_fingerprint)
 then return jsonb_build_object('hold','reviewed recovery fingerprint changed'); end if;
 if exists(select 1 from icg.image_generation_calls where scope=p_scope and panel=p_panel
 and revision=p_revision and fingerprint<>p_fingerprint)
 then return jsonb_build_object('hold','revision identity changed'); end if;
 select * into r from icg.image_generation_calls where scope=p_scope and panel=p_panel
 and fingerprint=p_fingerprint and state='success' order by created_at desc limit 1;
 if found then return jsonb_build_object('output_hash',r.output_hash); end if;
 return jsonb_build_object('prior_hashes',coalesce((select jsonb_agg(c.output_hash)
 from icg.image_generation_calls c where c.scope=p_scope and c.panel=p_panel
 and c.output_hash ~ '^[0-9a-f]{64}$' and (c.state='success' or (c.state='terminal'
 and exists(select 1 from icg.image_generation_recovery_receipts a
 where a.terminal_token=c.token and a.target_revision=p_revision)))), '[]'::jsonb));
end $$;

revoke all on function icg.image_generation_recovery_preflight(text,integer) from public,anon,authenticated;
revoke all on function icg.image_generation_acknowledge_terminal(uuid,integer,numeric,jsonb,jsonb,text) from public,anon,authenticated;
grant execute on function icg.image_generation_recovery_preflight(text,integer) to service_role;
grant execute on function icg.image_generation_acknowledge_terminal(uuid,integer,numeric,jsonb,jsonb,text) to service_role;
notify pgrst,'reload schema';
