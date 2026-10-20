-- Additive proposal: apply after outcome-v3 and ordinary attempt diagnostics.
-- Opt-in revision-1 isolation only. Existing recovery/retry RPCs are unchanged.
create function icg.image_generation_inspect_independent_v4(
 p_scope text,p_panel integer,p_fingerprint text,p_revision integer
) returns jsonb language plpgsql security invoker set search_path='' as $$
declare r record;
begin
 if p_scope is null or p_panel is null or p_fingerprint is null or p_revision is distinct from 1
 or p_panel<=0 or p_scope !~ '^output/episodes/[0-9]{4}-[0-9]{2}-[0-9]{2}/panels$'
 or p_fingerprint !~ '^[0-9a-f]{64}$'
 then return jsonb_build_object('hold','invalid independent generation identity'); end if;
 -- A refusal stays terminal. Only a settled, evidenced ordinary refusal on ANOTHER
 -- panel can be isolated. Unknown cost, reservations and legacy terminals block.
 if exists(select 1 from icg.image_generation_calls c where c.scope=p_scope
 and (c.state in ('reserved','unknown') or (c.state='terminal' and (
   c.panel<>p_panel and c.revision=1 and c.retry_plan_id is null
   and c.result_code='CONTENT_REVIEW_REQUIRED' and c.settled_at is not null
   and c.provider_reason in ('PROHIBITED_CONTENT','SAFETY','IMAGE_SAFETY',
     'BLOCKLIST','RECITATION','IMAGE_RECITATION','SPII','IMAGE_PROHIBITED_CONTENT',
     'ESCALATION','PUP_LIMITED_DISABLED')
   and c.cost between 0 and 0.10
   and exists(select 1 from icg.image_generation_attempt_diagnostics d
     where d.token=c.token and d.kind='inputs')
   and exists(select 1 from icg.image_generation_attempt_diagnostics d
     where d.token=c.token and d.kind='refusal'
     and d.payload->>'finish_reason'=c.provider_reason)
 ) is not true)))
 then return jsonb_build_object('hold','scope requires reconciliation'); end if;
 if exists(select 1 from icg.image_generation_calls where scope=p_scope and panel=p_panel
 and fingerprint<>p_fingerprint)
 then return jsonb_build_object('hold','artifact identity changed'); end if;
 select * into r from icg.image_generation_calls where scope=p_scope and panel=p_panel
 and state='success' order by created_at desc limit 1;
 if found then return jsonb_build_object('output_hash',r.output_hash); end if;
 return '{}'::jsonb;
end $$;

create function icg.image_generation_reserve_independent_v4(
 p_scope text,p_panel integer,p_fingerprint text,p_revision integer
) returns jsonb language plpgsql security invoker set search_path='' as $$
declare receipt jsonb; t uuid;
begin
 perform pg_catalog.pg_advisory_xact_lock(731091,1);
 receipt:=icg.image_generation_inspect_independent_v4(p_scope,p_panel,p_fingerprint,p_revision);
 if receipt ? 'hold' then return receipt; end if;
 if receipt ? 'output_hash' then return jsonb_build_object('hold','already generated'); end if;
 -- Same aggregate/per-panel/day/month budgets and lock as every existing path.
 if (select count(*) from icg.image_generation_calls
 where created_at>=date_trunc('day',now() at time zone 'UTC') at time zone 'UTC')>=60
 or (select count(*) from icg.image_generation_calls
 where created_at>=date_trunc('month',now() at time zone 'UTC') at time zone 'UTC')>=300
 or (select count(*) from icg.image_generation_calls where scope=p_scope and panel=p_panel)>=3
 or (select count(*) from icg.image_generation_calls where scope=p_scope)>=30
 or coalesce((select sum(cost) from icg.image_generation_calls where scope=p_scope),0)+0.10>3
 or coalesce((select sum(cost) from icg.image_generation_calls
 where created_at>=date_trunc('day',now() at time zone 'UTC') at time zone 'UTC'),0)+0.10>6
 or coalesce((select sum(cost) from icg.image_generation_calls
 where created_at>=date_trunc('month',now() at time zone 'UTC') at time zone 'UTC'),0)+0.10>30
 then return jsonb_build_object('hold','generation budget exhausted'); end if;
 insert into icg.image_generation_calls(scope,panel,fingerprint,state,revision)
 values(p_scope,p_panel,p_fingerprint,'reserved',1) returning token into t;
 return jsonb_build_object('token',t);
end $$;

create function icg.image_generation_content_isolation_v4_capability()
returns jsonb language sql security invoker set search_path='' as $$
 select case when
 to_regprocedure('icg.image_generation_inspect_independent_v4(text,integer,text,integer)') is not null
 and to_regprocedure('icg.image_generation_reserve_independent_v4(text,integer,text,integer)') is not null
 and to_regprocedure('icg.image_generation_finish_outcome_v3(text,integer,text,uuid,text,numeric,text,text,text,integer)') is not null
 and to_regclass('icg.image_generation_attempt_diagnostics') is not null
 then jsonb_build_object('version','image-content-isolation-4')
 else jsonb_build_object('hold','incomplete content isolation v4 database contract') end;
$$;

revoke all on function icg.image_generation_inspect_independent_v4(text,integer,text,integer) from public,anon,authenticated;
revoke all on function icg.image_generation_reserve_independent_v4(text,integer,text,integer) from public,anon,authenticated;
revoke all on function icg.image_generation_content_isolation_v4_capability() from public,anon,authenticated;
grant execute on function icg.image_generation_inspect_independent_v4(text,integer,text,integer) to service_role;
grant execute on function icg.image_generation_reserve_independent_v4(text,integer,text,integer) to service_role;
grant execute on function icg.image_generation_content_isolation_v4_capability() to service_role;
notify pgrst,'reload schema';
