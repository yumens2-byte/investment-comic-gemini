-- Reservations are budget estimates, not assertions about provider prices.
create table icg.image_generation_calls (
 token uuid primary key default gen_random_uuid(), scope text not null,
 panel integer not null check(panel>0), fingerprint text not null,
 state text not null check(state in ('reserved','success','failed','terminal','unknown')),
 cost numeric not null default 0.10 check(cost>=0), output_hash text,
 created_at timestamptz not null default clock_timestamp()
);
create index image_generation_scope_idx on icg.image_generation_calls(scope,panel);
create index image_generation_created_idx on icg.image_generation_calls(created_at);
alter table icg.image_generation_calls enable row level security;
revoke all on icg.image_generation_calls from public,anon,authenticated;
grant select,insert,update on icg.image_generation_calls to service_role;

create function icg.image_generation_inspect(p_scope text,p_panel integer,p_fingerprint text)
returns jsonb language plpgsql security invoker set search_path='' as $$
declare r record;
begin
 if p_scope is null or p_panel is null or p_fingerprint is null or length(p_scope)>500 or p_scope='' or p_panel<=0 or p_fingerprint !~ '^[0-9a-f]{64}$'
 then return jsonb_build_object('hold','invalid identity'); end if;
 if exists(select 1 from icg.image_generation_calls where scope=p_scope
 and state in ('reserved','unknown','terminal'))
 then return jsonb_build_object('hold','scope requires reconciliation'); end if;
 if exists(select 1 from icg.image_generation_calls where scope=p_scope and panel=p_panel
 and fingerprint<>p_fingerprint)
 then return jsonb_build_object('hold','artifact identity changed'); end if;
 select * into r from icg.image_generation_calls where scope=p_scope and panel=p_panel
 and state='success' order by created_at desc limit 1;
 if found then return jsonb_build_object('output_hash',r.output_hash); end if;
 return '{}'::jsonb;
end $$;

create function icg.image_generation_reserve(p_scope text,p_panel integer,p_fingerprint text)
returns jsonb language plpgsql security invoker set search_path='' as $$
declare receipt jsonb; t uuid;
begin
 perform pg_catalog.pg_advisory_xact_lock(731091,1);
 receipt:=icg.image_generation_inspect(p_scope,p_panel,p_fingerprint);
 if receipt ? 'hold' then return receipt; end if;
 if receipt ? 'output_hash' then return jsonb_build_object('hold','already generated'); end if;
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
 insert into icg.image_generation_calls(scope,panel,fingerprint,state)
 values(p_scope,p_panel,p_fingerprint,'reserved') returning token into t;
 return jsonb_build_object('token',t);
end $$;

create function icg.image_generation_finish(p_scope text,p_panel integer,p_fingerprint text,
 p_token uuid,p_state text,p_actual_cost numeric,p_output_hash text)
returns jsonb language plpgsql security invoker set search_path='' as $$
declare final_state text; changed integer;
begin
 perform pg_catalog.pg_advisory_xact_lock(731091,1);
 if p_state is null or p_token is null or p_scope is null or p_panel is null
 or p_fingerprint is null or p_state not in ('success','failed','terminal','unknown')
 or (p_actual_cost is not null and (p_actual_cost<0 or p_actual_cost::text in ('NaN','Infinity','-Infinity')))
 or (p_state='success' and coalesce(p_output_hash,'') !~ '^[0-9a-f]{64}$')
 then return jsonb_build_object('hold','invalid settlement'); end if;
 final_state:=case when p_actual_cost is null then 'unknown' else p_state end;
 if p_actual_cost>0.10 then final_state:='terminal'; end if;
 update icg.image_generation_calls set state=final_state,
 cost=coalesce(p_actual_cost,cost),output_hash=p_output_hash
 where token=p_token and scope=p_scope and panel=p_panel and fingerprint=p_fingerprint
 and state='reserved';
 get diagnostics changed=row_count;
 if changed<>1 then return jsonb_build_object('hold','stale settlement token'); end if;
 if final_state in ('unknown','terminal')
 then return jsonb_build_object('hold','provider outcome or cost requires reconciliation'); end if;
 return jsonb_build_object('settled',true);
end $$;
revoke execute on function icg.image_generation_inspect(text,integer,text) from public,anon,authenticated;
revoke execute on function icg.image_generation_reserve(text,integer,text) from public,anon,authenticated;
revoke execute on function icg.image_generation_finish(text,integer,text,uuid,text,numeric,text) from public,anon,authenticated;
grant execute on function icg.image_generation_inspect(text,integer,text) to service_role;
grant execute on function icg.image_generation_reserve(text,integer,text) to service_role;
grant execute on function icg.image_generation_finish(text,integer,text,uuid,text,numeric,text) to service_role;
notify pgrst,'reload schema';
