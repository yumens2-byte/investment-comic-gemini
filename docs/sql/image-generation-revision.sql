-- Deployment proposal; existing date/panel/global budget totals are preserved.
alter table icg.image_generation_calls add column revision integer not null default 1 check(revision between 1 and 100);
create function icg.image_generation_inspect_v2(p_scope text,p_panel integer,p_fingerprint text,p_revision integer)
returns jsonb language plpgsql security invoker set search_path='' as $$
declare r record;
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
 if exists(select 1 from icg.image_generation_calls where scope=p_scope
 and state in ('reserved','unknown','terminal'))
 then return jsonb_build_object('hold','scope requires reconciliation'); end if;
 if exists(select 1 from icg.image_generation_calls where scope=p_scope and panel=p_panel
 and revision=p_revision and fingerprint<>p_fingerprint)
 then return jsonb_build_object('hold','revision identity changed'); end if;
 select * into r from icg.image_generation_calls where scope=p_scope and panel=p_panel
 and fingerprint=p_fingerprint and state='success' order by created_at desc limit 1;
 if found then return jsonb_build_object('output_hash',r.output_hash); end if;
 return jsonb_build_object('prior_hashes',coalesce((select jsonb_agg(output_hash) from icg.image_generation_calls where scope=p_scope and panel=p_panel and state='success'),'[]'::jsonb));
end $$;
create function icg.image_generation_reserve_v2(p_scope text,p_panel integer,p_fingerprint text,p_revision integer)
returns jsonb language plpgsql security invoker set search_path='' as $$
declare receipt jsonb; t uuid;
begin
 perform pg_catalog.pg_advisory_xact_lock(731091,1);
 receipt:=icg.image_generation_inspect_v2(p_scope,p_panel,p_fingerprint,p_revision);
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
 insert into icg.image_generation_calls(scope,panel,fingerprint,state,revision)
 values(p_scope,p_panel,p_fingerprint,'reserved',p_revision) returning token into t;
 return jsonb_build_object('token',t);
end $$;

revoke all on function icg.image_generation_inspect_v2(text,integer,text,integer) from public,anon,authenticated;
revoke all on function icg.image_generation_reserve_v2(text,integer,text,integer) from public,anon,authenticated;
grant execute on function icg.image_generation_inspect_v2(text,integer,text,integer) to service_role;
grant execute on function icg.image_generation_reserve_v2(text,integer,text,integer) to service_role;
notify pgrst,'reload schema';
