-- Apply after revision, recovery, retry and ordinary diagnostic SQL.
-- Additive proposal: deploy before enabling ICG_IMAGE_OUTCOME_V3_ENABLED.
alter table icg.image_generation_calls add column if not exists provider_reason text;
alter table icg.image_generation_calls add column if not exists result_code text;
alter table icg.image_generation_calls add column if not exists settled_at timestamptz;

create function icg.image_generation_outcome_v3_capability()
returns jsonb language sql security invoker set search_path='' as $$
 select case when
  to_regprocedure('icg.image_generation_finish_outcome_v3(text,integer,text,uuid,text,numeric,text,text,text,integer)') is not null
  and to_regprocedure('icg.image_generation_store_run_status_v3(text,integer,text,text,jsonb)') is not null
  and to_regclass('icg.image_generation_run_status') is not null
 then jsonb_build_object('version','image-outcome-3')
 else jsonb_build_object('hold','incomplete outcome v3 database contract') end;
$$;
revoke all on function icg.image_generation_outcome_v3_capability() from public,anon,authenticated;
grant execute on function icg.image_generation_outcome_v3_capability() to service_role;

create function icg.image_generation_finish_outcome_v3(
 p_scope text,p_panel integer,p_fingerprint text,p_token uuid,p_state text,
 p_actual_cost numeric,p_output_hash text,p_reason text,p_plan_id text,p_revision integer
) returns jsonb language plpgsql security invoker set search_path='' as $$
declare c icg.image_generation_calls%rowtype; final_state text; code text; block text;
begin
 perform pg_catalog.pg_advisory_xact_lock(731091,1);
 if p_state is null or p_state not in ('success','failed','terminal','unknown')
 or (p_actual_cost is not null and (p_actual_cost<0 or p_actual_cost::text in ('NaN','Infinity','-Infinity')))
 or (p_state='success' and coalesce(p_output_hash,'') !~ '^[0-9a-f]{64}$')
 or (p_state<>'success' and p_output_hash is not null)
 or p_revision is null or p_revision not between 1 and 100
 then return jsonb_build_object('hold','invalid settlement'); end if;
 select * into c from icg.image_generation_calls where token=p_token and scope=p_scope
 and panel=p_panel and fingerprint=p_fingerprint and revision=p_revision
 and retry_plan_id is not distinct from p_plan_id for update;
 if not found then return jsonb_build_object('hold','stale settlement token'); end if;
 final_state:=case when p_actual_cost is null then 'unknown'
                  when p_actual_cost>0.10 then 'terminal' else p_state end;
 code:=case when final_state='unknown' then 'PROVIDER_OUTCOME_UNKNOWN'
       when final_state='terminal' and p_reason in ('PROHIBITED_CONTENT','SAFETY','IMAGE_SAFETY',
         'BLOCKLIST','RECITATION','IMAGE_RECITATION','SPII','IMAGE_PROHIBITED_CONTENT','ESCALATION','PUP_LIMITED_DISABLED')
         then 'CONTENT_REVIEW_REQUIRED'
       when final_state='terminal' then 'PROVIDER_TERMINAL'
       when final_state='success' then 'IMAGE_SUCCESS' else 'INVALID_IMAGE' end;
 if c.state<>'reserved' then
  if c.state<>final_state or c.cost is distinct from coalesce(p_actual_cost,c.cost)
  or c.output_hash is distinct from p_output_hash or c.provider_reason is distinct from p_reason
  or c.result_code is distinct from code
  then return jsonb_build_object('hold','conflicting settlement'); end if;
 else
  update icg.image_generation_calls set state=final_state,cost=coalesce(p_actual_cost,cost),
    output_hash=p_output_hash,provider_reason=p_reason,result_code=code,settled_at=clock_timestamp()
  where token=p_token;
 end if;
 block:=case when final_state='unknown' then 'PROVIDER_OUTCOME_UNKNOWN'
        when p_actual_cost>0.10 then 'GENERATION_COST_RECONCILIATION_REQUIRED'
        when code='CONTENT_REVIEW_REQUIRED' then code
        when final_state='terminal' then 'PROVIDER_TERMINAL' else null end;
 return jsonb_build_object('settled',true,'state',final_state,'result_code',code,
   'provider_reason',p_reason,'usage_status',case when p_actual_cost is null then 'MISSING' else 'AVAILABLE' end,
   'cost_usd',p_actual_cost,'hold_code',block,'retry_allowed',false);
end $$;
revoke all on function icg.image_generation_finish_outcome_v3(text,integer,text,uuid,text,numeric,text,text,text,integer)
 from public,anon,authenticated;
grant execute on function icg.image_generation_finish_outcome_v3(text,integer,text,uuid,text,numeric,text,text,text,integer)
 to service_role;

-- Separate execution telemetry preserves narrative/publishing status and the PNG pointer.
create table icg.image_generation_run_status (
 scope text not null, revision integer not null check(revision between 1 and 100),
 run_id text not null, run_attempt text not null,
 summary jsonb not null check(jsonb_typeof(summary)='object' and octet_length(summary::text)<=262144),
 updated_at timestamptz not null default clock_timestamp(),
 primary key(scope,revision,run_id,run_attempt)
);
alter table icg.image_generation_run_status enable row level security;
revoke all on icg.image_generation_run_status from public,anon,authenticated;
grant select,insert,update on icg.image_generation_run_status to service_role;
create function icg.image_generation_store_run_status_v3(p_scope text,p_revision integer,
 p_run_id text,p_run_attempt text,p_summary jsonb)
returns jsonb language plpgsql security invoker set search_path='' as $$
begin
 if p_scope is null or p_scope !~ '^output/episodes/[0-9]{4}-[0-9]{2}-[0-9]{2}/panels$'
 or p_revision is null or p_revision not between 1 and 100
 or coalesce(p_run_id,'') !~ '^[0-9]+$' or coalesce(p_run_attempt,'') !~ '^[1-9][0-9]*$'
 or jsonb_typeof(p_summary) is distinct from 'object' or octet_length(p_summary::text)>262144
 or p_summary->>'run_id' is distinct from p_run_id
 or p_summary->>'run_attempt' is distinct from p_run_attempt
 or exists(select 1 from jsonb_object_keys(p_summary) k where k not in
 ('run_id','run_attempt','expected_images','successful_images','not_attempted_images',
  'held_panel','provider_reason','complete','result_code','observed_usage_cost_usd','cost_complete'))
 then return jsonb_build_object('hold','invalid run summary'); end if;
 insert into icg.image_generation_run_status(scope,revision,run_id,run_attempt,summary)
 values(p_scope,p_revision,p_run_id,p_run_attempt,p_summary)
 on conflict(scope,revision,run_id,run_attempt) do update set summary=excluded.summary,
 updated_at=clock_timestamp();
 return jsonb_build_object('stored',true);
end $$;
revoke all on function icg.image_generation_store_run_status_v3(text,integer,text,text,jsonb)
 from public,anon,authenticated;
grant execute on function icg.image_generation_store_run_status_v3(text,integer,text,text,jsonb) to service_role;
notify pgrst,'reload schema';
