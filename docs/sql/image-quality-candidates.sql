-- Additive deployment proposal. Apply AFTER outcome-v3 and reviewed recovery SQL.
-- No episode status changes; candidate selection is not publication authorization.
create table icg.image_quality_candidates (
 id uuid primary key, scope text not null, revision integer not null check(revision between 2 and 100),
 bundle jsonb not null, digest text not null, state text not null default 'DRAFT'
 check(state in ('DRAFT','APPROVED','REVIEWED','SELECTED','CANCELLED')),
 approved_by text, approval_note text, review jsonb, reviewed_by text,
 created_at timestamptz not null default clock_timestamp(), unique(scope,revision)
);
create table icg.image_quality_selections (
 scope text primary key, version integer not null default 0,
 manifest jsonb not null, actor text not null, note text not null,
 updated_at timestamptz not null default clock_timestamp()
);
create table icg.image_quality_selection_history (
 scope text not null, version integer not null, manifest jsonb not null,
 actor text not null, note text not null, created_at timestamptz not null default clock_timestamp(),
 primary key(scope,version)
);
alter table icg.image_generation_calls add column quality_candidate_id uuid
 references icg.image_quality_candidates(id);
alter table icg.image_generation_calls add column quality_run_id text;
create unique index image_quality_one_call_per_panel on icg.image_generation_calls(quality_candidate_id,panel)
 where quality_candidate_id is not null;
alter table icg.image_quality_candidates enable row level security;
alter table icg.image_quality_selections enable row level security;
alter table icg.image_quality_selection_history enable row level security;
revoke all on icg.image_quality_candidates,icg.image_quality_selections,
 icg.image_quality_selection_history from public,anon,authenticated;
grant select,insert,update on icg.image_quality_candidates,icg.image_quality_selections to service_role;
grant select,insert on icg.image_quality_selection_history to service_role;

create function icg.image_quality_register(p_bundle jsonb) returns jsonb
language plpgsql security invoker set search_path='' as $$
declare b jsonb:=p_bundle; s text; i uuid; r int; e record; item jsonb; paid int;
 d text; current_version int; prior icg.image_quality_candidates%rowtype;
begin
 perform pg_catalog.pg_advisory_xact_lock(731091,1);
 if jsonb_typeof(b) is distinct from 'object' or octet_length(b::text)>1048576
 or b->>'version' is distinct from 'image-quality-candidate-1'
 or b->>'purpose' is distinct from 'QUALITY_RETAKE'
 or coalesce(b->>'id','') !~ '^[a-f0-9-]{36}$'
 or coalesce(b->>'date','') !~ '^\d{4}-\d{2}-\d{2}$'
 or coalesce(b->>'revision','') !~ '^[0-9]+$'
 or coalesce(b->>'base_selection_version','') !~ '^[0-9]+$'
 or jsonb_typeof(b->'panels') is distinct from 'array'
 or jsonb_array_length(b->'panels') not between 1 and 6
 or jsonb_typeof(b->'base_manifest') is distinct from 'array'
 or jsonb_typeof(b->'source_script') is distinct from 'object'
 or jsonb_typeof(b->'candidate_script') is distinct from 'object'
 or coalesce(b->>'max_calls','') !~ '^[1-6]$'
 or coalesce(b->>'max_cost_usd','') !~ '^(0[.][0-9]+|1([.]0+)?)$'
 then return jsonb_build_object('hold','invalid quality bundle'); end if;
 i:=(b->>'id')::uuid; r:=(b->>'revision')::int;
 s:='output/episodes/'||(b->>'date')||'/panels';
 d:=encode(sha256(convert_to(b::text,'UTF8')),'hex');
 select * into prior from icg.image_quality_candidates where id=i;
 if found then
  if prior.bundle=b then return jsonb_build_object('registered',true,'id',i,'digest',prior.digest); end if;
  return jsonb_build_object('hold','candidate identity changed');
 end if;
 if r not between 2 and 100 or (b->>'max_calls')::int<>jsonb_array_length(b->'panels')
 or (b->>'max_cost_usd')::numeric<(b->>'max_calls')::int*0.10
 then return jsonb_build_object('hold','invalid candidate budget'); end if;
 select * into e from icg.episode_assets where episode_date=(b->>'date')::date and episode_no=1 for update;
 if not found or e.status not in ('image_generated','assembled') or e.script_json<>b->'source_script'
 or e.artifact_run_id::text is distinct from b->>'base_artifact_run_id'
 then return jsonb_build_object('hold','quality source changed or unavailable'); end if;
 if ((b->'candidate_script') - '_scene_contracts' - '_reviewed_image_inputs' - '_scene_performance_v2'
       - '_generation_revision' - 'panels') <>
    ((b->'source_script') - '_scene_contracts' - '_reviewed_image_inputs' - '_scene_performance_v2'
       - '_generation_revision' - 'panels')
 or b->'candidate_script'->>'_generation_revision' is distinct from r::text
 or b->'candidate_script'->'_reviewed_image_inputs'->>'version' is distinct from 'reviewed-image-inputs-2'
 or b->'candidate_script'->'_reviewed_image_inputs'->>'aspect_ratio' is distinct from '4:5'
 or jsonb_array_length(b->'candidate_script'->'panels')<>jsonb_array_length(b->'source_script'->'panels')
 then return jsonb_build_object('hold','quality narrative changed'); end if;
 for item in select value from jsonb_array_elements(b->'source_script'->'panels') loop
  if not exists(select 1 from jsonb_array_elements(b->'candidate_script'->'panels') p
    where p->>'idx'=item->>'idx' and (p-'action'-'setting')=(item-'action'-'setting'))
  then return jsonb_build_object('hold','quality story or cast changed'); end if;
 end loop;
 select coalesce((select version from icg.image_quality_selections where scope=s),0) into current_version;
 if current_version<>(b->>'base_selection_version')::int then return jsonb_build_object('hold','selection changed'); end if;
 if current_version>0 and (select manifest from icg.image_quality_selections where scope=s)<>b->'base_manifest'
 then return jsonb_build_object('hold','base manifest changed'); end if;
 select count(*) into paid from jsonb_array_elements(b->'source_script'->'panels') p
 where p->>'panel_type' not in ('TEXT_CARD','DISCLAIMER');
 if jsonb_array_length(b->'base_manifest')<>paid
 or (select count(distinct x->>'panel_idx') from jsonb_array_elements(b->'base_manifest') x)<>paid
 then return jsonb_build_object('hold','base manifest coverage'); end if;
 for item in select value from jsonb_array_elements(b->'base_manifest') loop
  if coalesce(item->>'panel_idx','') !~ '^[1-9][0-9]*$'
  or not exists(select 1 from jsonb_array_elements(b->'source_script'->'panels') p
   where p->>'idx'=item->>'panel_idx' and p->>'panel_type' not in ('TEXT_CARD','DISCLAIMER'))
  or not exists(select 1 from icg.image_generation_calls c where c.scope=s
   and c.panel=(item->>'panel_idx')::int and c.state='success' and c.output_hash=item->>'output_hash'
   and (current_version>0 or exists(select 1 from icg.image_generation_attempt_diagnostics d
    where d.token=c.token and d.kind='inputs' and d.payload->>'run_id'=b->>'base_artifact_run_id')))
  or (current_version=0 and (item->>'artifact_run_id' is distinct from b->>'base_artifact_run_id'
   or item->>'artifact_name' is distinct from 'episode-'||(b->>'base_artifact_run_id')
   or item->>'artifact_path' is distinct from (b->>'date')||'/panels/P'||(item->>'panel_idx')||'.png'))
  then return jsonb_build_object('hold','base image not receipted'); end if;
 end loop;
 if exists(select 1 from icg.image_quality_candidates where scope=s and revision=r)
 or exists(select 1 from icg.image_generation_calls where scope=s and revision>=r)
 then return jsonb_build_object('hold','revision already used'); end if;
 if (select count(distinct x->>'panel_idx') from jsonb_array_elements(b->'panels') x)<>jsonb_array_length(b->'panels')
 then return jsonb_build_object('hold','duplicate quality panels'); end if;
 for item in select value from jsonb_array_elements(b->'panels') loop
  if coalesce(item->>'panel_idx','') !~ '^[1-9][0-9]*$'
  or coalesce(item->>'fingerprint','') !~ '^[a-f0-9]{64}$'
  or not exists(select 1 from jsonb_array_elements(b->'base_manifest') p where p->>'panel_idx'=item->>'panel_idx')
  or not exists(select 1 from jsonb_array_elements(b->'candidate_script'->'_reviewed_image_inputs'->'panels') p
     where p->>'idx'=item->>'panel_idx' and p->>'fingerprint'=item->>'fingerprint')
  then return jsonb_build_object('hold','invalid quality panel identity'); end if;
 end loop;
 insert into icg.image_quality_candidates(id,scope,revision,bundle,digest) values(i,s,r,b,d);
 return jsonb_build_object('registered',true,'id',i,'digest',d);
end $$;

create function icg.image_quality_approve(p_id uuid,p_digest text,p_actor text,p_note text)
returns jsonb language plpgsql security invoker set search_path='' as $$
begin
 perform pg_catalog.pg_advisory_xact_lock(731091,1);
 if length(trim(coalesce(p_actor,'')))<2 or length(trim(coalesce(p_note,'')))<20
 then return jsonb_build_object('hold','reviewer and evidence required'); end if;
 update icg.image_quality_candidates set state='APPROVED',approved_by=p_actor,approval_note=p_note
 where id=p_id and digest=p_digest and state='DRAFT';
 if not found then return jsonb_build_object('hold','stale or already approved candidate'); end if;
 return jsonb_build_object('approved',true);
end $$;

create function icg.image_quality_inspect(p_id uuid,p_panel int,p_fingerprint text)
returns jsonb language plpgsql security invoker set search_path='' as $$
declare q icg.image_quality_candidates%rowtype; existing_call record;
begin
 select * into q from icg.image_quality_candidates where id=p_id;
 if not found or q.state not in ('APPROVED','REVIEWED')
 or not exists(select 1 from jsonb_array_elements(q.bundle->'panels') p
  where p->>'panel_idx'=p_panel::text and p->>'fingerprint'=p_fingerprint)
 then return jsonb_build_object('hold','quality generation not approved'); end if;
 if not exists(select 1 from icg.episode_assets e where 'output/episodes/'||e.episode_date::text||'/panels'=q.scope
  and e.episode_no=1 and e.status in ('image_generated','assembled')
  and e.script_json=q.bundle->'source_script' and e.artifact_run_id::text=q.bundle->>'base_artifact_run_id')
 or coalesce((select version from icg.image_quality_selections where scope=q.scope),0)<>
  (q.bundle->>'base_selection_version')::int
 then return jsonb_build_object('hold','quality source changed'); end if;
 select * into existing_call from icg.image_generation_calls where quality_candidate_id=p_id and panel=p_panel;
 if found then
  if existing_call.fingerprint<>p_fingerprint or existing_call.state<>'success' then return jsonb_build_object('hold','quality attempt requires review'); end if;
  return jsonb_build_object('output_hash',existing_call.output_hash);
 end if;
 if exists(select 1 from icg.image_generation_calls c where c.scope=q.scope
  and (c.state in ('reserved','unknown') or (c.state='terminal' and not exists(
   select 1 from icg.image_generation_recovery_receipts r where r.terminal_token=c.token))))
 then return jsonb_build_object('hold','scope requires reconciliation'); end if;
 return '{}'::jsonb;
end $$;

create function icg.image_quality_reserve(p_id uuid,p_panel int,p_fingerprint text,p_run_id text)
returns jsonb language plpgsql security invoker set search_path='' as $$
declare q icg.image_quality_candidates%rowtype; receipt jsonb; t uuid;
begin
 perform pg_catalog.pg_advisory_xact_lock(731091,1);
 receipt:=icg.image_quality_inspect(p_id,p_panel,p_fingerprint);
 if receipt?'hold' then return receipt; end if;
 if receipt?'output_hash' then return jsonb_build_object('hold','already generated'); end if;
 if coalesce(p_run_id,'') !~ '^[0-9]+$' then return jsonb_build_object('hold','artifact run required'); end if;
 select * into q from icg.image_quality_candidates where id=p_id;
 if (select count(*) from icg.image_generation_calls where quality_candidate_id=p_id)>=(q.bundle->>'max_calls')::int
 or coalesce((select sum(cost) from icg.image_generation_calls where quality_candidate_id=p_id),0)+0.10>(q.bundle->>'max_cost_usd')::numeric
 or (select count(*) from icg.image_generation_calls where scope=q.scope and panel=p_panel)>=3
 or (select count(*) from icg.image_generation_calls where scope=q.scope)>=30
 or (select count(*) from icg.image_generation_calls where created_at>=date_trunc('day',now() at time zone 'UTC') at time zone 'UTC')>=60
 or (select count(*) from icg.image_generation_calls where created_at>=date_trunc('month',now() at time zone 'UTC') at time zone 'UTC')>=300
 or coalesce((select sum(cost) from icg.image_generation_calls where scope=q.scope),0)+0.10>3
 or coalesce((select sum(cost) from icg.image_generation_calls where created_at>=date_trunc('day',now() at time zone 'UTC') at time zone 'UTC'),0)+0.10>6
 or coalesce((select sum(cost) from icg.image_generation_calls where created_at>=date_trunc('month',now() at time zone 'UTC') at time zone 'UTC'),0)+0.10>30
 then return jsonb_build_object('hold','generation budget exhausted'); end if;
 insert into icg.image_generation_calls(scope,panel,fingerprint,state,revision,quality_candidate_id,quality_run_id)
 values(q.scope,p_panel,p_fingerprint,'reserved',q.revision,p_id,p_run_id) returning token into t;
 -- Exact candidate output artifact identity is recorded before the paid call.
 return jsonb_build_object('token',t);
end $$;

create function icg.image_quality_review(p_id uuid,p_digest text,p_actor text,p_review jsonb)
returns jsonb language plpgsql security invoker set search_path='' as $$
declare q icg.image_quality_candidates%rowtype; item jsonb;
begin
 perform pg_catalog.pg_advisory_xact_lock(731091,1);
 select * into q from icg.image_quality_candidates where id=p_id and digest=p_digest for update;
 if not found or q.state<>'APPROVED' or length(trim(coalesce(p_actor,'')))<2
 or jsonb_typeof(p_review) is distinct from 'object' or octet_length(p_review::text)>65536
 or jsonb_typeof(p_review->'panels') is distinct from 'array'
 or jsonb_array_length(p_review->'panels')<>jsonb_array_length(q.bundle->'panels')
 or (select count(distinct p->>'panel_idx') from jsonb_array_elements(p_review->'panels') p)<>jsonb_array_length(q.bundle->'panels')
 or p_review->>'episode_continuity' is distinct from 'PASS'
 or length(trim(coalesce(p_review->>'evidence','')))<20
 then return jsonb_build_object('hold','complete human review required'); end if;
 for item in select value from jsonb_array_elements(p_review->'panels') loop
  if not exists(select 1 from jsonb_array_elements(q.bundle->'panels') p where p->>'panel_idx'=item->>'panel_idx')
  or not exists(select 1 from icg.image_generation_calls c where c.quality_candidate_id=p_id
   and c.panel::text=item->>'panel_idx' and c.state='success' and c.output_hash=item->>'output_hash')
  or item->>'safety' is distinct from 'PASS' or item->>'canon' is distinct from 'PASS'
  or item->>'quality' not in ('PASS','REVIEW') or item->>'quality' is null
  or item->>'assembly' is distinct from 'PASS'
  or length(trim(coalesce(item->>'evidence','')))<20
  then return jsonb_build_object('hold','review does not match successful images'); end if;
 end loop;
 update icg.image_quality_candidates set state='REVIEWED',review=p_review,reviewed_by=p_actor where id=p_id;
 return jsonb_build_object('reviewed',true);
end $$;

create function icg.image_quality_select(p_id uuid,p_digest text,p_expected_version int,p_actor text,p_note text)
returns jsonb language plpgsql security invoker set search_path='' as $$
declare q icg.image_quality_candidates%rowtype; v int; manifest jsonb; item jsonb; call record;
begin
 perform pg_catalog.pg_advisory_xact_lock(731091,1);
 select * into q from icg.image_quality_candidates where id=p_id and digest=p_digest;
 if not found or q.state<>'REVIEWED' or length(trim(coalesce(p_actor,'')))<2
 or length(trim(coalesce(p_note,'')))<20 then return jsonb_build_object('hold','selection not approved'); end if;
 v:=coalesce((select version from icg.image_quality_selections where scope=q.scope),0);
 if p_expected_version is distinct from v or v<>(q.bundle->>'base_selection_version')::int
 then return jsonb_build_object('hold','selection version conflict'); end if;
 if not exists(select 1 from icg.episode_assets e where 'output/episodes/'||e.episode_date::text||'/panels'=q.scope
  and e.episode_no=1 and e.status in ('image_generated','assembled') and e.script_json=q.bundle->'source_script'
  and e.artifact_run_id::text=q.bundle->>'base_artifact_run_id')
 then return jsonb_build_object('hold','quality source changed'); end if;
 manifest:='[]'::jsonb;
 for item in select value from jsonb_array_elements(q.bundle->'base_manifest') loop
  select c.output_hash,c.quality_run_id as run_id into call
  from icg.image_generation_calls c
  where c.quality_candidate_id=p_id and c.panel::text=item->>'panel_idx' and c.state='success';
  if found then
   item:=jsonb_build_object('panel_idx',(item->>'panel_idx')::int,'output_hash',call.output_hash,
    'artifact_run_id',call.run_id,'artifact_name','image-quality-'||p_id::text,
    'artifact_path','P'||(item->>'panel_idx')||'.png');
  end if;
  manifest:=manifest||jsonb_build_array(item);
 end loop;
 if v=0 then insert into icg.image_quality_selection_history(scope,version,manifest,actor,note)
  values(q.scope,0,q.bundle->'base_manifest',p_actor,'Original successful images'); end if;
 insert into icg.image_quality_selections(scope,version,manifest,actor,note)
 values(q.scope,v+1,manifest,p_actor,p_note) on conflict(scope) do update
 set version=excluded.version,manifest=excluded.manifest,actor=excluded.actor,note=excluded.note,updated_at=clock_timestamp();
 insert into icg.image_quality_selection_history(scope,version,manifest,actor,note)
 values(q.scope,v+1,manifest,p_actor,p_note);
 update icg.image_quality_candidates set state='SELECTED' where id=p_id;
 return jsonb_build_object('selected',true,'version',v+1,'manifest',manifest,'publication_authorized',false);
end $$;

create function icg.image_quality_rollback(p_scope text,p_expected_version int,p_target_version int,p_actor text,p_note text)
returns jsonb language plpgsql security invoker set search_path='' as $$
declare v int; m jsonb;
begin
 perform pg_catalog.pg_advisory_xact_lock(731091,1);
 select version into v from icg.image_quality_selections where scope=p_scope;
 select manifest into m from icg.image_quality_selection_history where scope=p_scope and version=p_target_version;
 if p_expected_version is distinct from v or m is null or length(trim(coalesce(p_actor,'')))<2
 or length(trim(coalesce(p_note,'')))<20 then return jsonb_build_object('hold','rollback conflict or evidence missing'); end if;
 if not exists(select 1 from icg.episode_assets e where 'output/episodes/'||e.episode_date::text||'/panels'=p_scope
 and e.episode_no=1 and e.status in ('image_generated','assembled'))
 then return jsonb_build_object('hold','rollback unavailable for published episode'); end if;
 update icg.image_quality_selections set version=v+1,manifest=m,actor=p_actor,note=p_note,updated_at=clock_timestamp() where scope=p_scope;
 insert into icg.image_quality_selection_history values(p_scope,v+1,m,p_actor,p_note,clock_timestamp());
 return jsonb_build_object('rolled_back',true,'version',v+1,'manifest',m,'publication_authorized',false);
end $$;

create function icg.image_quality_cancel(p_id uuid,p_digest text,p_actor text,p_note text)
returns jsonb language plpgsql security invoker set search_path='' as $$
begin
 perform pg_catalog.pg_advisory_xact_lock(731091,1);
 if length(trim(coalesce(p_actor,'')))<2 or length(trim(coalesce(p_note,'')))<20
 then return jsonb_build_object('hold','reviewer and evidence required'); end if;
 if exists(select 1 from icg.image_generation_calls where quality_candidate_id=p_id and state in ('reserved','unknown'))
 then return jsonb_build_object('hold','in-flight or unknown call requires reconciliation'); end if;
 update icg.image_quality_candidates set state='CANCELLED',approval_note=coalesce(approval_note,'')|| E'\nCANCELLED: '||p_actor||' '||p_note
 where id=p_id and digest=p_digest and state in ('DRAFT','APPROVED','REVIEWED','SELECTED');
 if not found then return jsonb_build_object('hold','stale candidate'); end if;
 return jsonb_build_object('cancelled',true);
end $$;

revoke all on function icg.image_quality_register(jsonb),icg.image_quality_approve(uuid,text,text,text),
 icg.image_quality_inspect(uuid,int,text),icg.image_quality_reserve(uuid,int,text,text),
 icg.image_quality_review(uuid,text,text,jsonb),icg.image_quality_select(uuid,text,int,text,text),
 icg.image_quality_rollback(text,int,int,text,text),icg.image_quality_cancel(uuid,text,text,text) from public,anon,authenticated;
grant execute on function icg.image_quality_register(jsonb),icg.image_quality_approve(uuid,text,text,text),
 icg.image_quality_inspect(uuid,int,text),icg.image_quality_reserve(uuid,int,text,text),
 icg.image_quality_review(uuid,text,text,jsonb),icg.image_quality_select(uuid,text,int,text,text),
 icg.image_quality_rollback(text,int,int,text,text),icg.image_quality_cancel(uuid,text,text,text) to service_role;
notify pgrst,'reload schema';
