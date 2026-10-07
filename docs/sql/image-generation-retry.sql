-- Deployment proposal, NOT applied. Requires revision and recovery SQL first.
-- Registration is an operator-reviewed step, never an automatic provider callback.
alter table icg.image_generation_calls add column retry_plan_id text, add column provider_reason text;
create table icg.image_generation_retry_plans (
 plan_id text not null check(plan_id ~ '^[0-9a-f]{64}$'),
 scope text not null check(scope ~ '^output/episodes/[0-9]{4}-[0-9]{2}-[0-9]{2}/panels$'),
 panel integer not null check(panel>0), revision integer not null check(revision between 1 and 100),
 fingerprints jsonb not null check(jsonb_typeof(fingerprints)='array' and jsonb_array_length(fingerprints) between 1 and 3),
 script_json jsonb not null, review_evidence text not null check(length(btrim(review_evidence))>=20),
 created_at timestamptz not null default clock_timestamp(),
 primary key(plan_id,scope,panel)
);
alter table icg.image_generation_retry_plans enable row level security;
revoke all on icg.image_generation_retry_plans from public,anon,authenticated,service_role;
grant select,insert on icg.image_generation_retry_plans to service_role;

create function icg.image_generation_inspect_retry(p_scope text,p_panel integer,p_fingerprint text,p_plan_id text)
returns jsonb language plpgsql security invoker set search_path='' as $$
declare plan icg.image_generation_retry_plans%rowtype; r record; receipt jsonb;
begin
 select * into plan from icg.image_generation_retry_plans where plan_id=p_plan_id
 and scope=p_scope and panel=p_panel;
 if not found or p_fingerprint is null or p_fingerprint !~ '^[0-9a-f]{64}$'
 or not plan.fingerprints @> jsonb_build_array(p_fingerprint)
 or exists(select 1 from jsonb_array_elements_text(plan.fingerprints) f
           where f.value !~ '^[0-9a-f]{64}$')
 then return jsonb_build_object('hold','reviewed retry plan absent or changed'); end if;
 if not exists(select 1 from icg.episode_assets e
 where 'output/episodes/'||e.episode_date::text||'/panels'=p_scope
 and e.episode_no=1 and e.status='narrative_done' and e.script_json=plan.script_json
 and coalesce(e.script_json->>'_generation_revision','1')=plan.revision::text)
 then return jsonb_build_object('hold','reviewed script changed'); end if;
 if exists(select 1 from icg.image_generation_calls c where c.scope=p_scope
 and (c.state in ('reserved','unknown') or (c.state='terminal' and not (
 c.retry_plan_id is not null and exists(select 1 from icg.image_generation_retry_plans old_plan
 where old_plan.plan_id=c.retry_plan_id and old_plan.scope=c.scope and old_plan.panel=c.panel
 and old_plan.script_json=plan.script_json) and c.provider_reason in ('PROHIBITED_CONTENT','SAFETY','IMAGE_SAFETY')
 and c.cost<=0.10))))
 then
   if plan.revision<2 then return jsonb_build_object('hold','scope requires reconciliation'); end if;
   receipt:=icg.image_generation_recovery_preflight(p_scope,plan.revision);
   if receipt ? 'hold' then return receipt; end if;
 end if;
 -- Even a reviewed plan must not change or regenerate successful paid inputs.
 select * into r from icg.image_generation_calls c where c.scope=p_scope and c.panel=p_panel
 and c.state='success' order by c.created_at desc limit 1;
 if found then
  if r.fingerprint<>p_fingerprint then return jsonb_build_object('hold','successful input changed'); end if;
  return jsonb_build_object('output_hash',r.output_hash);
 end if;
 -- Rejected inputs cannot be sent again, including across runner restarts.
 if exists(select 1 from icg.image_generation_calls c where c.scope=p_scope and c.panel=p_panel
 and c.fingerprint=p_fingerprint and c.state='terminal')
 then return jsonb_build_object('hold','rejected input cannot be repeated'); end if;
 return '{}'::jsonb;
end $$;

create function icg.image_generation_reserve_retry(p_scope text,p_panel integer,p_fingerprint text,p_plan_id text)
returns jsonb language plpgsql security invoker set search_path='' as $$
declare receipt jsonb; t uuid; rev integer;
begin
 perform pg_catalog.pg_advisory_xact_lock(731091,1);
 receipt:=icg.image_generation_inspect_retry(p_scope,p_panel,p_fingerprint,p_plan_id);
 if receipt ? 'hold' then return receipt; end if;
 if receipt ? 'output_hash' then return jsonb_build_object('hold','already generated'); end if;
 if (select count(*) from icg.image_generation_calls where scope=p_scope and panel=p_panel)>=3
 or (select count(*) from icg.image_generation_calls where scope=p_scope)>=30
 or (select count(*) from icg.image_generation_calls where created_at>=date_trunc('day',now() at time zone 'UTC') at time zone 'UTC')>=60
 or (select count(*) from icg.image_generation_calls where created_at>=date_trunc('month',now() at time zone 'UTC') at time zone 'UTC')>=300
 or coalesce((select sum(cost) from icg.image_generation_calls where scope=p_scope),0)+0.10>3
 or coalesce((select sum(cost) from icg.image_generation_calls where created_at>=date_trunc('day',now() at time zone 'UTC') at time zone 'UTC'),0)+0.10>6
 or coalesce((select sum(cost) from icg.image_generation_calls where created_at>=date_trunc('month',now() at time zone 'UTC') at time zone 'UTC'),0)+0.10>30
 then return jsonb_build_object('hold','generation budget exhausted'); end if;
 select revision into rev from icg.image_generation_retry_plans
 where plan_id=p_plan_id and scope=p_scope and panel=p_panel;
 insert into icg.image_generation_calls(scope,panel,fingerprint,state,revision,retry_plan_id)
 values(p_scope,p_panel,p_fingerprint,'reserved',rev,p_plan_id) returning token into t;
 return jsonb_build_object('token',t);
end $$;

create function icg.image_generation_finish_retry(p_scope text,p_panel integer,p_fingerprint text,p_plan_id text,
 p_token uuid,p_state text,p_actual_cost numeric,p_output_hash text,p_reason text)
returns jsonb language plpgsql security invoker set search_path='' as $$
declare c icg.image_generation_calls%rowtype; final_state text;
begin
 perform pg_catalog.pg_advisory_xact_lock(731091,1);
 if p_state is null or p_state not in ('success','failed','terminal','unknown')
 or (p_actual_cost is not null and (p_actual_cost<0 or p_actual_cost::text in ('NaN','Infinity','-Infinity')))
 or (p_state='success' and coalesce(p_output_hash,'') !~ '^[0-9a-f]{64}$')
 then return jsonb_build_object('hold','invalid settlement'); end if;
 select * into c from icg.image_generation_calls where token=p_token and scope=p_scope
 and panel=p_panel and fingerprint=p_fingerprint and retry_plan_id=p_plan_id for update;
 if not found then return jsonb_build_object('hold','stale settlement token'); end if;
 final_state:=case when p_actual_cost is null then 'unknown' when p_actual_cost>0.10 then 'terminal' else p_state end;
 if c.state<>'reserved' then
  if c.state<>final_state or c.cost is distinct from coalesce(p_actual_cost,c.cost)
  or c.output_hash is distinct from p_output_hash or c.provider_reason is distinct from p_reason
  then return jsonb_build_object('hold','conflicting settlement'); end if;
 else
  update icg.image_generation_calls set state=final_state,cost=coalesce(p_actual_cost,cost),
  output_hash=p_output_hash,provider_reason=p_reason where token=p_token;
 end if;
 if final_state='unknown' or (final_state='terminal' and not (
 p_reason is not null and p_reason in ('PROHIBITED_CONTENT','SAFETY','IMAGE_SAFETY') and c.retry_plan_id=p_plan_id and p_actual_cost<=0.10))
 then return jsonb_build_object('hold','provider outcome or cost requires reconciliation'); end if;
 return jsonb_build_object('settled',true,'state',final_state);
end $$;
revoke all on function icg.image_generation_inspect_retry(text,integer,text,text) from public,anon,authenticated;
revoke all on function icg.image_generation_reserve_retry(text,integer,text,text) from public,anon,authenticated;
revoke all on function icg.image_generation_finish_retry(text,integer,text,text,uuid,text,numeric,text,text) from public,anon,authenticated;
grant execute on function icg.image_generation_inspect_retry(text,integer,text,text) to service_role;
grant execute on function icg.image_generation_reserve_retry(text,integer,text,text) to service_role;
grant execute on function icg.image_generation_finish_retry(text,integer,text,text,uuid,text,numeric,text,text) to service_role;
notify pgrst,'reload schema';

create function icg.image_generation_retry_cursor(p_scope text,p_panel integer,p_plan_id text)
returns jsonb language plpgsql security invoker set search_path='' as $$
declare plan icg.image_generation_retry_plans%rowtype; fp text; receipt jsonb;
begin
 select * into plan from icg.image_generation_retry_plans where plan_id=p_plan_id
 and scope=p_scope and panel=p_panel;
 if not found then return jsonb_build_object('hold','reviewed retry plan absent'); end if;
 select c.fingerprint into fp from icg.image_generation_calls c
 where c.scope=p_scope and c.panel=p_panel and c.state='success' order by c.created_at desc limit 1;
 if found then
  receipt:=icg.image_generation_inspect_retry(p_scope,p_panel,fp,p_plan_id);
  if receipt ? 'hold' then return receipt; end if;
  return jsonb_build_object('fingerprint',fp,'attempts_used',
    (select count(*) from icg.image_generation_calls where scope=p_scope and panel=p_panel));
 end if;
 for fp in select value from jsonb_array_elements_text(plan.fingerprints) loop
  receipt:=icg.image_generation_inspect_retry(p_scope,p_panel,fp,p_plan_id);
  if receipt->>'hold'='rejected input cannot be repeated' then continue; end if;
  if receipt ? 'hold' then return receipt; end if;
  return jsonb_build_object('fingerprint',fp,'attempts_used',
    (select count(*) from icg.image_generation_calls where scope=p_scope and panel=p_panel));
 end loop;
 return jsonb_build_object('hold','reviewed retry variants exhausted');
end $$;
revoke all on function icg.image_generation_retry_cursor(text,integer,text) from public,anon,authenticated;
grant execute on function icg.image_generation_retry_cursor(text,integer,text) to service_role;
notify pgrst,'reload schema';

-- Provider evidence survives runner shutdown; readable only by the server role.
create table icg.image_generation_diagnostics (
 id uuid primary key default gen_random_uuid(), scope text not null, panel integer not null,
 plan_id text not null, kind text not null check(kind in ('inputs','refusal')),
 payload jsonb not null check(jsonb_typeof(payload)='object' and octet_length(payload::text)<=262144),
 created_at timestamptz not null default clock_timestamp(),
 foreign key(plan_id,scope,panel) references icg.image_generation_retry_plans(plan_id,scope,panel)
);
alter table icg.image_generation_diagnostics enable row level security;
revoke all on icg.image_generation_diagnostics from public,anon,authenticated,service_role;
grant select,insert on icg.image_generation_diagnostics to service_role;
create function icg.image_generation_store_diagnostic(p_scope text,p_panel integer,p_plan_id text,p_kind text,p_payload jsonb)
returns jsonb language plpgsql security invoker set search_path='' as $$
begin
 if p_kind is null or p_kind not in ('inputs','refusal') or p_payload is null
 or jsonb_typeof(p_payload)<>'object' or octet_length(p_payload::text)>262144
 or not exists(select 1 from icg.image_generation_retry_plans plan
 join icg.episode_assets e on 'output/episodes/'||e.episode_date::text||'/panels'=plan.scope
 and e.episode_no=1 and e.status='narrative_done' and e.script_json=plan.script_json
 where plan.plan_id=p_plan_id and plan.scope=p_scope and plan.panel=p_panel)
 then return jsonb_build_object('hold','invalid or stale diagnostic identity'); end if;
 insert into icg.image_generation_diagnostics(scope,panel,plan_id,kind,payload)
 values(p_scope,p_panel,p_plan_id,p_kind,p_payload);
 return jsonb_build_object('stored',true);
end $$;
revoke all on function icg.image_generation_store_diagnostic(text,integer,text,text,jsonb) from public,anon,authenticated;
grant execute on function icg.image_generation_store_diagnostic(text,integer,text,text,jsonb) to service_role;
notify pgrst,'reload schema';
