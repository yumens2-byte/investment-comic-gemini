-- Additive visual contracts. Apply after image-quality-candidates and recovery-v3.
-- No policy backfill, no provider calls, no publication, no automatic expiry.
alter table icg.episode_assets add column visual_policy_json jsonb;
alter table icg.episode_assets add column visual_policy_sha256 text;
create table icg.visual_quality_inputs (
 scope text not null, revision int not null check(revision between 1 and 100),
 script_snapshot jsonb not null, policy jsonb not null, policy_sha256 text not null,
 actor text not null, note text not null, created_at timestamptz not null default clock_timestamp(),
 primary key(scope,revision)
);
create table icg.visual_quality_reviews (
 id uuid primary key default gen_random_uuid(), scope text not null, version int not null,
 manifest jsonb not null, review jsonb not null, actor text not null,
 created_at timestamptz not null default clock_timestamp(), unique(scope,version)
);
create table icg.visual_quality_revocations (
 review_id uuid primary key references icg.visual_quality_reviews(id), actor text not null, note text not null,
 created_at timestamptz not null default clock_timestamp()
);
create table icg.visual_quality_claims (
 token text primary key, scope text not null, review_id uuid not null references icg.visual_quality_reviews(id),
 manifest jsonb not null, selection_version int not null, created_at timestamptz not null default clock_timestamp()
);
alter table icg.visual_quality_inputs enable row level security;
alter table icg.visual_quality_reviews enable row level security;
alter table icg.visual_quality_revocations enable row level security;
alter table icg.visual_quality_claims enable row level security;
revoke all on icg.visual_quality_inputs,icg.visual_quality_reviews,icg.visual_quality_revocations,
 icg.visual_quality_claims from public,anon,authenticated,service_role;
grant select,insert on icg.visual_quality_inputs,icg.visual_quality_reviews,icg.visual_quality_revocations,
 icg.visual_quality_claims to service_role;

create function icg.visual_quality_capability() returns jsonb language sql security invoker set search_path='' as $$
 select '{"version":"visual-quality-1"}'::jsonb
$$;
create function icg.visual_quality_append_only() returns trigger
language plpgsql security invoker set search_path='' as $$
begin raise exception 'Visual evidence is append-only'; end $$;
create trigger visual_inputs_immutable before update or delete on icg.visual_quality_inputs
 for each row execute function icg.visual_quality_append_only();
create trigger visual_reviews_immutable before update or delete on icg.visual_quality_reviews
 for each row execute function icg.visual_quality_append_only();
create trigger visual_revocations_immutable before update or delete on icg.visual_quality_revocations
 for each row execute function icg.visual_quality_append_only();
create trigger visual_claims_immutable before update or delete on icg.visual_quality_claims
 for each row execute function icg.visual_quality_append_only();

create function icg.visual_quality_require_inputs(p_script jsonb) returns jsonb
language plpgsql security invoker set search_path='' as $$
declare s text; e record; frozen record;
begin
 s:='output/episodes/'||(p_script->>'date')||'/panels';
 select * into e from icg.episode_assets where 'output/episodes/'||episode_date::text||'/panels'=s and episode_no=1;
 if not found or e.visual_policy_json is null then return jsonb_build_object('hold','VISUAL_POLICY_NOT_REGISTERED'); end if;
 if p_script->'_visual_policy' is distinct from e.visual_policy_json
 or p_script->>'_visual_policy_sha256' is distinct from e.visual_policy_sha256
 or coalesce(p_script->>'_generation_revision','') !~ '^[0-9]{1,3}$'
 then return jsonb_build_object('hold','VISUAL_POLICY_MIRROR_CHANGED'); end if;
 if p_script->>'_quality_candidate_id' is not null then
  if exists(select 1 from icg.image_quality_candidates q where q.id::text=p_script->>'_quality_candidate_id'
   and q.scope=s and q.bundle->'candidate_script'=p_script and q.bundle->'source_script'=e.script_json
   and q.state in ('APPROVED','REVIEWED','SELECTED')) then return jsonb_build_object('authorized',true); end if;
  return jsonb_build_object('hold','VISUAL_QUALITY_CANDIDATE_NOT_APPROVED');
 end if;
 select * into frozen from icg.visual_quality_inputs where scope=s and revision=(p_script->>'_generation_revision')::int;
 if not found or frozen.policy is distinct from e.visual_policy_json
 or frozen.policy_sha256 is distinct from e.visual_policy_sha256
 or p_script->'_reviewed_image_inputs' is distinct from frozen.script_snapshot->'_reviewed_image_inputs'
 or p_script->'_scene_performance_v2' is distinct from frozen.script_snapshot->'_scene_performance_v2'
 then return jsonb_build_object('hold','VISUAL_FROZEN_INPUTS_CHANGED'); end if;
 -- Dialogue/captions may be edited and reassembled; visual action/form/cast may not.
 if jsonb_array_length(p_script->'panels')<>jsonb_array_length(frozen.script_snapshot->'panels')
 or exists(select 1 from jsonb_array_elements(p_script->'panels') with ordinality a(p,n)
 join jsonb_array_elements(frozen.script_snapshot->'panels') with ordinality b(p,n) using(n)
 where a.p-'key_text'-'narration'-'market_ref' is distinct from b.p-'key_text'-'narration'-'market_ref')
 then return jsonb_build_object('hold','VISUAL_FROZEN_PANELS_CHANGED'); end if;
 return jsonb_build_object('authorized',true);
end $$;

create function icg.visual_quality_freeze_inputs(p_expected_script jsonb,p_script jsonb,p_policy jsonb,p_actor text,p_note text)
returns jsonb language plpgsql security invoker set search_path='' as $$
declare e record; s text; candidate jsonb; h text; item jsonb; paid int;
begin
 perform pg_catalog.pg_advisory_xact_lock(731091,1);
 if jsonb_typeof(p_script) is distinct from 'object' or jsonb_typeof(p_expected_script) is distinct from 'object'
 or p_policy->>'version' is distinct from 'visual-quality-1' or p_policy->>'mode' is distinct from 'enforce'
 or p_policy->>'layout' is distinct from 'mobile-reserved-band-1'
 or coalesce(p_policy->>'layout_sha256','') !~ '^[a-f0-9]{64}$'
 or coalesce(length(trim(p_actor)),0)<2 or coalesce(length(trim(p_note)),0)<20
 or coalesce(p_script->>'date','') !~ '^\d{4}-\d{2}-\d{2}$'
 or p_script->>'episode_id' is distinct from 'ICG-'||(p_script->>'date')||'-001'
 or p_script->'_state_candidate'->>'version' is distinct from 'state-candidate-1'
 or p_script->>'_generation_revision' is distinct from '1'
 or p_script->'_reviewed_image_inputs'->>'origin' is distinct from 'INITIAL_GENERATION'
 or p_script->'_reviewed_image_inputs'->>'version' is distinct from 'reviewed-image-inputs-2'
 or p_script->'_reviewed_image_inputs'->>'aspect_ratio' is distinct from '4:5'
 or p_script->'_reviewed_image_inputs'->>'model' is distinct from 'gemini-2.5-flash-image'
 or p_script->'_reviewed_image_inputs'->>'ref_binding_version' is distinct from 'canon-form-1'
 or jsonb_typeof(p_script->'_scene_performance_v2') is distinct from 'object'
 or jsonb_typeof(p_script->'_reviewed_image_inputs'->'panels') is distinct from 'array'
 or jsonb_typeof(p_script->'panels') is distinct from 'array'
 or p_script ? '_scene_contracts'
 or (p_script-'_reviewed_image_inputs'-'_generation_revision') is distinct from
 (p_expected_script-'_generation_revision')
 then return jsonb_build_object('hold','VISUAL_INITIAL_INPUT_INVALID'); end if;
 s:='output/episodes/'||(p_script->>'date')||'/panels';
 h:=encode(sha256(convert_to(p_policy::text,'UTF8')),'hex');
 candidate:=p_script||jsonb_build_object('_visual_policy',p_policy,'_visual_policy_sha256',h);
 select * into e from icg.episode_assets where episode_date=(p_script->>'date')::date and episode_no=1 for update;
 if found and e.script_json=candidate and exists(select 1 from icg.visual_quality_inputs where scope=s and revision=1
 and script_snapshot=candidate and policy=p_policy)
 then return jsonb_build_object('registered',true,'script',candidate); end if;
 if not found or e.status<>'narrative_done' or e.script_json is distinct from p_expected_script
 or e.visual_policy_json is not null or coalesce(e.error_message,'') like 'PUBLISH_HOLD:%'
 or exists(select 1 from icg.image_generation_calls where scope=s)
 then return jsonb_build_object('hold','VISUAL_INITIAL_SOURCE_CHANGED_OR_STARTED'); end if;
 select count(*) into paid from jsonb_array_elements(p_script->'panels') p where p->>'panel_type' not in ('TEXT_CARD','DISCLAIMER');
 if paid<1 or jsonb_array_length(p_script->'_reviewed_image_inputs'->'panels')<>paid
 or (select count(distinct p->>'idx') from jsonb_array_elements(p_script->'_reviewed_image_inputs'->'panels') p)<>paid
 or (select count(*) from jsonb_object_keys(p_script->'_scene_performance_v2'))<>paid
 then return jsonb_build_object('hold','VISUAL_INITIAL_COVERAGE_REQUIRED'); end if;
 for item in select value from jsonb_array_elements(p_script->'_reviewed_image_inputs'->'panels') loop
  if coalesce(item->>'idx','') !~ '^[1-9][0-9]*$'
  or coalesce(item->>'fingerprint','') !~ '^[a-f0-9]{64}$'
  or coalesce(item->>'scene_sha256','') !~ '^[a-f0-9]{64}$'
  or not (p_script->'_scene_performance_v2') ? (item->>'idx')
  or not exists(select 1 from jsonb_array_elements(p_script->'panels') p where p->>'idx'=item->>'idx'
   and p->>'panel_type' not in ('TEXT_CARD','DISCLAIMER'))
  then return jsonb_build_object('hold','VISUAL_INITIAL_PANEL_INVALID'); end if;
 end loop;
 insert into icg.visual_quality_inputs(scope,revision,script_snapshot,policy,policy_sha256,actor,note)
 values(s,1,candidate,p_policy,h,p_actor,p_note);
 update icg.episode_assets set script_json=candidate,visual_policy_json=p_policy,visual_policy_sha256=h
 where episode_date=(p_script->>'date')::date and episode_no=1;
 return jsonb_build_object('registered',true,'script',candidate);
end $$;

create function icg.visual_quality_effective_manifest_valid(p_script jsonb) returns boolean
language plpgsql security invoker set search_path='' as $$
declare item jsonb; base_item jsonb; origin_script jsonb; c record; s text; paid int;
begin
 s:='output/episodes/'||(p_script->>'date')||'/panels';
 select count(*) into paid from jsonb_array_elements(p_script->'panels') p where p->>'panel_type' not in ('TEXT_CARD','DISCLAIMER');
 if jsonb_typeof(p_script->'_effective_render_manifest') is distinct from 'array'
 or jsonb_typeof(p_script->'_assembly_manifest') is distinct from 'object'
 or p_script->'_assembly_manifest'->>'version' is distinct from 'assembly-manifest-2'
 or p_script->'_assembly_manifest'->'effective_render_manifest' is distinct from p_script->'_effective_render_manifest'
 or p_script->'_assembly_manifest'->>'policy_sha256' is distinct from p_script->>'_visual_policy_sha256'
 or p_script->'_assembly_manifest'->'visual_contract' is distinct from jsonb_build_object(
  'policy',p_script->'_visual_policy','scene_plan',p_script->'_scene_performance_v2',
  'mobile_layout_report',p_script->'_mobile_layout_report',
  'public_script',(select jsonb_object_agg(key,value) from jsonb_each(p_script) where left(key,1)<>'_'))
 or jsonb_array_length(p_script->'_effective_render_manifest')<>paid
 or (select count(distinct x->>'panel_idx') from jsonb_array_elements(p_script->'_effective_render_manifest') x)<>paid
 then return false; end if;
 for item in select value from jsonb_array_elements(p_script->'_effective_render_manifest') loop
  select * into c from icg.image_generation_calls where token::text=item->>'origin_token' and scope=s
   and panel::text=item->>'panel_idx' and state='success' and output_hash=item->>'output_hash'
   and fingerprint=item->>'fingerprint' and revision::text=item->>'origin_revision';
  if not found then return false; end if;
  origin_script:=p_script;
  if item->>'candidate_id' is not null then
   select bundle->'candidate_script' into origin_script from icg.image_quality_candidates
   where id::text=item->>'candidate_id' and c.quality_candidate_id=id and state='SELECTED';
   if not found then return false; end if;
  elsif c.quality_candidate_id is not null then return false;
  end if;
  select p into base_item from jsonb_array_elements(origin_script->'_reviewed_image_inputs'->'panels') p
   where p->>'idx'=item->>'panel_idx';
  if not found or base_item->>'fingerprint' is distinct from item->>'fingerprint'
   or base_item->>'scene_sha256' is distinct from item->>'scene_sha256'
   or origin_script->'_scene_performance_v2'->(item->>'panel_idx') is distinct from item->'scene'
   or coalesce(base_item->'ref_bindings','[]'::jsonb) is distinct from item->'ref_bindings'
  then return false; end if;
 end loop;
 if (p_script->'_image_quality_selection'->>'version') is not null then
  if not exists(select 1 from icg.image_quality_selections where scope=s
   and version::text=p_script->'_image_quality_selection'->>'version'
   and manifest=p_script->'_image_quality_selection'->'manifest') then return false; end if;
  if exists(select 1 from jsonb_array_elements(p_script->'_effective_render_manifest') p
   where not exists(select 1 from jsonb_array_elements(p_script->'_image_quality_selection'->'manifest') m
    where m->>'panel_idx'=p->>'panel_idx' and m->>'output_hash'=p->>'output_hash')) then return false; end if;
 elsif exists(select 1 from icg.image_quality_selections where scope=s) then return false;
 end if;
 return true;
end $$;

create function icg.visual_quality_record_review(p_script jsonb,p_review jsonb,p_actor text) returns jsonb
language plpgsql security invoker set search_path='' as $$
declare e record; s text; v int; rid uuid; item jsonb; kind text; m jsonb;
begin
 perform pg_catalog.pg_advisory_xact_lock(731091,1);
 s:='output/episodes/'||(p_script->>'date')||'/panels';
 select * into e from icg.episode_assets where 'output/episodes/'||episode_date::text||'/panels'=s and episode_no=1 for update;
 if not found or e.status<>'assembled' or e.script_json is distinct from p_script
 or coalesce(e.error_message,'') like 'PUBLISH_HOLD:%'
 or (icg.visual_quality_require_inputs(p_script))?'hold'
 or not icg.visual_quality_effective_manifest_valid(p_script)
 then return jsonb_build_object('hold','VISUAL_REVIEW_SOURCE_CHANGED_OR_BUSY'); end if;
 if jsonb_typeof(p_review->'panels') is distinct from 'array' or coalesce(length(trim(p_actor)),0)<2
 or p_review->>'episode_continuity' is distinct from 'PASS' or coalesce(length(trim(p_review->>'evidence')),0)<20
 or jsonb_array_length(p_review->'panels')<>jsonb_array_length(p_script->'_effective_render_manifest')
 or (select count(distinct x->>'panel_idx') from jsonb_array_elements(p_review->'panels') x)<>jsonb_array_length(p_review->'panels')
 then return jsonb_build_object('hold','VISUAL_COMPLETE_HUMAN_REVIEW_REQUIRED'); end if;
 for item in select value from jsonb_array_elements(p_review->'panels') loop
  select x into m from jsonb_array_elements(p_script->'_effective_render_manifest') x where x->>'panel_idx'=item->>'panel_idx';
  if not found or item->>'output_hash' is distinct from m->>'output_hash'
   or item->>'slide_hash' is distinct from p_script->'_assembly_manifest'->'slides'->>((item->>'panel_idx')::int-1)
  then return jsonb_build_object('hold','VISUAL_REVIEW_BYTES_CHANGED'); end if;
  foreach kind in array array['motion','rhythm','canon','story','typography','mobile'] loop
   if item->'checks'->kind->>'status' is distinct from 'PASS'
    or coalesce(length(trim(item->'checks'->kind->>'evidence')),0)<20
   then return jsonb_build_object('hold','VISUAL_REVIEW_CHECK_REQUIRED'); end if;
  end loop;
 end loop;
 select coalesce(max(version),0)+1 into v from icg.visual_quality_reviews where scope=s;
 insert into icg.visual_quality_reviews(scope,version,manifest,review,actor)
 values(s,v,p_script->'_assembly_manifest',p_review,p_actor) returning id into rid;
 return jsonb_build_object('reviewed',true,'id',rid,'version',v);
end $$;

create function icg.visual_quality_revoke(p_review_id uuid,p_actor text,p_note text) returns jsonb
language plpgsql security invoker set search_path='' as $$
declare s text;
begin
 perform pg_catalog.pg_advisory_xact_lock(731091,1);
 select scope into s from icg.visual_quality_reviews where id=p_review_id;
 if not found or coalesce(length(trim(p_actor)),0)<2 or coalesce(length(trim(p_note)),0)<20
 then return jsonb_build_object('hold','VISUAL_REVOCATION_EVIDENCE_REQUIRED'); end if;
 perform 1 from icg.episode_assets where 'output/episodes/'||episode_date::text||'/panels'=s and episode_no=1 for update;
 if exists(select 1 from icg.episode_assets where 'output/episodes/'||episode_date::text||'/panels'=s
 and episode_no=1 and (coalesce(error_message,'') like 'PUBLISH_HOLD:%' or status='published'))
 then return jsonb_build_object('hold','PUBLICATION_BUSY_OR_PUBLISHED'); end if;
 insert into icg.visual_quality_revocations(review_id,actor,note) values(p_review_id,p_actor,p_note)
 on conflict(review_id) do nothing;
 return jsonb_build_object('revoked',true);
end $$;

create function icg.visual_quality_publication_ready(p_script jsonb) returns jsonb
language plpgsql security invoker set search_path='' as $$
declare s text; e record; r record;
begin
 s:='output/episodes/'||(p_script->>'date')||'/panels';
 select * into e from icg.episode_assets where 'output/episodes/'||episode_date::text||'/panels'=s and episode_no=1;
 if not found or e.status<>'assembled' or e.script_json is distinct from p_script
 or (icg.visual_quality_require_inputs(p_script))?'hold'
 or not icg.visual_quality_effective_manifest_valid(p_script)
 then return jsonb_build_object('hold','VISUAL_ASSEMBLY_NOT_CURRENT'); end if;
 select * into r from icg.visual_quality_reviews where scope=s order by version desc limit 1;
 if not found or r.manifest is distinct from p_script->'_assembly_manifest'
 or exists(select 1 from icg.visual_quality_revocations where review_id=r.id)
 then return jsonb_build_object('hold','VISUAL_REVIEW_REQUIRED'); end if;
 return jsonb_build_object('ready',true,'review_id',r.id);
end $$;

create function icg.claim_visual_publication(p_date date,p_episode_no int,p_expected_version timestamptz,p_script jsonb)
returns jsonb language plpgsql security invoker set search_path='' as $$
declare e record; r jsonb; s text; t text;
begin
 perform pg_catalog.pg_advisory_xact_lock(731091,1);
 select * into e from icg.episode_assets where episode_date=p_date and episode_no=p_episode_no for update;
 if not found or p_episode_no<>1 or p_expected_version is null or e.updated_at is distinct from p_expected_version
 or coalesce(e.error_message,'') like 'PUBLISH_HOLD:%' or e.script_json is distinct from p_script
 then return jsonb_build_object('hold','VISUAL_CLAIM_VERSION_CHANGED_OR_BUSY'); end if;
 r:=icg.visual_quality_publication_ready(p_script);
 if r?'hold' then return r; end if;
 s:='output/episodes/'||p_date::text||'/panels'; t:='PUBLISH_HOLD:'||gen_random_uuid()::text;
 insert into icg.visual_quality_claims(token,scope,review_id,manifest,selection_version)
 values(t,s,(r->>'review_id')::uuid,p_script->'_assembly_manifest',
 coalesce((select version from icg.image_quality_selections where scope=s),0));
 update icg.episode_assets set error_message=t where episode_date=p_date and episode_no=1;
 return jsonb_build_object('token',t);
end $$;

create function icg.visual_quality_require_snapshot(p_date date,p_token text) returns jsonb
language plpgsql security invoker set search_path='' as $$
declare e record; c record; s text; r jsonb;
begin
 s:='output/episodes/'||p_date::text||'/panels';
 select * into e from icg.episode_assets where episode_date=p_date and episode_no=1;
 select * into c from icg.visual_quality_claims where token=p_token and scope=s;
 if not found or e.error_message is distinct from p_token
 or c.manifest is distinct from e.script_json->'_assembly_manifest'
 or c.selection_version<>coalesce((select version from icg.image_quality_selections where scope=s),0)
 or exists(select 1 from icg.visual_quality_revocations where review_id=c.review_id)
 then return jsonb_build_object('hold','VISUAL_CLAIM_SNAPSHOT_CHANGED'); end if;
 r:=icg.visual_quality_publication_ready(e.script_json);
 if r?'hold' or r->>'review_id' is distinct from c.review_id::text then return jsonb_build_object('hold','VISUAL_CLAIM_REVIEW_CHANGED'); end if;
 return jsonb_build_object('authorized',true);
end $$;

create function icg.visual_quality_guard_episode() returns trigger
language plpgsql security invoker set search_path='' as $$
declare s text; receipt jsonb;
begin
 s:='output/episodes/'||new.episode_date::text||'/panels';
 if old.visual_policy_json is null and new.visual_policy_json is null then
  if old.script_json ? '_visual_policy_intent'
   and new.script_json->'_visual_policy_intent' is distinct from old.script_json->'_visual_policy_intent'
  then raise exception 'VISUAL_PENDING_POLICY_IMMUTABLE'; end if;
  if new.script_json ? '_visual_policy_intent' and
   (new.status in ('image_generated','assembled','published') or coalesce(new.error_message,'') like 'PUBLISH_HOLD:%')
  then raise exception 'VISUAL_POLICY_REGISTRATION_REQUIRED'; end if;
  return new;
 end if;
 if old.visual_policy_json is not null and (new.visual_policy_json is distinct from old.visual_policy_json
 or new.visual_policy_sha256 is distinct from old.visual_policy_sha256)
 then raise exception 'VISUAL_POLICY_IMMUTABLE'; end if;
 if new.script_json->'_visual_policy' is distinct from new.visual_policy_json
 or new.script_json->>'_visual_policy_sha256' is distinct from new.visual_policy_sha256
 or not exists(select 1 from icg.visual_quality_inputs v where v.scope=s
 and v.revision::text=new.script_json->>'_generation_revision' and v.policy=new.visual_policy_json
 and v.policy_sha256=new.visual_policy_sha256
 and v.script_snapshot->'_reviewed_image_inputs'=new.script_json->'_reviewed_image_inputs'
 and v.script_snapshot->'_scene_performance_v2'=new.script_json->'_scene_performance_v2')
 then raise exception 'VISUAL_POLICY_OR_FROZEN_INPUTS_CHANGED'; end if;
 if coalesce(old.error_message,'') like 'PUBLISH_HOLD:%' and
 (new.script_json is distinct from old.script_json or new.visual_policy_json is distinct from old.visual_policy_json)
 then raise exception 'PUBLICATION_BUSY'; end if;
 if new.status='assembled' and not icg.visual_quality_effective_manifest_valid(new.script_json)
 then raise exception 'VISUAL_ASSEMBLY_CAPABILITY_REQUIRED'; end if;
 if coalesce(new.error_message,'') like 'PUBLISH_HOLD:%' and new.error_message is distinct from old.error_message then
  if not exists(select 1 from icg.visual_quality_claims where token=new.error_message and scope=s
   and manifest=new.script_json->'_assembly_manifest') then raise exception 'VISUAL_CLAIM_CAPABILITY_REQUIRED'; end if;
 end if;
 if new.status='published' and old.status<>'published' then
  receipt:=icg.visual_quality_require_snapshot(old.episode_date,old.error_message);
  if receipt?'hold' then raise exception 'VISUAL_FINALIZE_SNAPSHOT_CHANGED'; end if;
 end if;
 return new;
end $$;
create trigger visual_policy_guard before update on icg.episode_assets
 for each row execute function icg.visual_quality_guard_episode();

create function icg.visual_quality_guard_generation() returns trigger
language plpgsql security invoker set search_path='' as $$
declare e record;
begin
 select * into e from icg.episode_assets where 'output/episodes/'||episode_date::text||'/panels'=new.scope and episode_no=1 for update;
 if not found then return new; end if;
 if e.visual_policy_json is null then
  if e.script_json ? '_visual_policy_intent' then raise exception 'VISUAL_POLICY_REGISTRATION_REQUIRED'; end if;
  return new;
 end if;
 if new.quality_candidate_id is not null then return new; end if; -- Existing candidate RPC owns its approval/budget.
 if not exists(select 1 from icg.visual_quality_inputs v,
 jsonb_array_elements(v.script_snapshot->'_reviewed_image_inputs'->'panels') p
 where v.scope=new.scope and v.revision=new.revision and p->>'idx'=new.panel::text
 and p->>'fingerprint'=new.fingerprint and coalesce(p->>'reuse_only','false')<>'true')
 then raise exception 'VISUAL_UNFROZEN_GENERATION_FORBIDDEN'; end if;
 return new;
end $$;
create trigger visual_generation_guard before insert on icg.image_generation_calls
 for each row execute function icg.visual_quality_guard_generation();

create function icg.visual_quality_guard_selection() returns trigger
language plpgsql security invoker set search_path='' as $$
declare e record;
begin
 perform pg_catalog.pg_advisory_xact_lock(731091,1);
 select * into e from icg.episode_assets where 'output/episodes/'||episode_date::text||'/panels'=new.scope
 and episode_no=1 for update;
 if not found or e.status='published' or coalesce(e.error_message,'') like 'PUBLISH_HOLD:%'
 then raise exception 'PUBLICATION_BUSY_OR_PUBLISHED'; end if;
 return new;
end $$;
create trigger quality_selection_publication_fence before insert or update on icg.image_quality_selections
 for each row execute function icg.visual_quality_guard_selection();
create trigger visual_review_publication_fence before insert on icg.visual_quality_reviews
 for each row execute function icg.visual_quality_guard_selection();
revoke all on function icg.visual_quality_guard_selection() from public,anon,authenticated;
grant execute on function icg.visual_quality_guard_selection() to service_role;

-- Explicit grants for new RPCs; no API exposure to anon/authenticated.
revoke all on function icg.visual_quality_capability(),icg.visual_quality_require_inputs(jsonb),
 icg.visual_quality_freeze_inputs(jsonb,jsonb,jsonb,text,text),icg.visual_quality_effective_manifest_valid(jsonb),
 icg.visual_quality_record_review(jsonb,jsonb,text),icg.visual_quality_revoke(uuid,text,text),
 icg.visual_quality_publication_ready(jsonb),icg.claim_visual_publication(date,int,timestamptz,jsonb),
 icg.visual_quality_require_snapshot(date,text),icg.visual_quality_guard_episode(),
 icg.visual_quality_guard_generation(),icg.visual_quality_append_only() from public,anon,authenticated;
grant execute on function icg.visual_quality_capability(),icg.visual_quality_require_inputs(jsonb),
 icg.visual_quality_freeze_inputs(jsonb,jsonb,jsonb,text,text),icg.visual_quality_effective_manifest_valid(jsonb),
 icg.visual_quality_record_review(jsonb,jsonb,text),icg.visual_quality_revoke(uuid,text,text),
 icg.visual_quality_publication_ready(jsonb),icg.claim_visual_publication(date,int,timestamptz,jsonb),
 icg.visual_quality_require_snapshot(date,text),icg.visual_quality_guard_episode(),
 icg.visual_quality_guard_generation(),icg.visual_quality_append_only() to service_role;
notify pgrst,'reload schema';

-- Mixed-run provenance: container artifact and the immutable generation origin differ.
create or replace function icg.image_quality_register(p_bundle jsonb) returns jsonb
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
       - '_generation_revision' - '_quality_candidate_id' - 'panels') <>
    ((b->'source_script') - '_scene_contracts' - '_reviewed_image_inputs' - '_scene_performance_v2'
       - '_generation_revision' - '_quality_candidate_id' - 'panels')
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
    where d.token=c.token and d.kind='inputs'
    and d.payload->>'run_id'=coalesce(item->>'origin_run_id',b->>'base_artifact_run_id')
    and (not item ? 'origin_run_id' or
      (c.token::text=item->>'origin_token' and c.fingerprint=item->>'origin_fingerprint')))))
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

-- General v2 selective recovery: successful panels keep their exact source inputs.
create function icg.visual_quality_register_recovery(
 p_expected_script jsonb,p_script jsonb,p_token uuid,p_revision int,p_actual_cost numeric,
 p_fingerprints jsonb,p_actor text,p_note text) returns jsonb
language plpgsql security invoker set search_path='' as $$
declare c record; e record; a jsonb; b jsonb; item jsonb; olditem jsonb; success record; receipt jsonb;
begin
 perform pg_catalog.pg_advisory_xact_lock(731091,1);
 select * into c from icg.image_generation_calls where token=p_token for update;
 if not found or c.state<>'terminal' or c.cost is distinct from p_actual_cost
 or c.provider_reason not in ('PROHIBITED_CONTENT','SAFETY','IMAGE_SAFETY')
 or c.result_code is distinct from 'CONTENT_REVIEW_REQUIRED' or c.settled_at is null
 or p_revision is null or p_revision not between 2 and 100 or p_revision<=c.revision
 or coalesce(length(trim(p_actor)),0)<2 or coalesce(length(trim(p_note)),0)<20
 or p_script->'_state_candidate' is distinct from p_expected_script->'_state_candidate'
 or p_script->'_state_candidate'->>'version' is distinct from 'state-candidate-1'
 or p_script->>'_generation_revision' is distinct from p_revision::text
 or p_script->'_reviewed_image_inputs'->>'version' is distinct from 'reviewed-image-inputs-2'
 or p_expected_script->'_reviewed_image_inputs'->>'version' is distinct from 'reviewed-image-inputs-2'
 or p_script->'_reviewed_image_inputs'->>'origin' is distinct from 'RECOVERY'
 or p_script->'_reviewed_image_inputs'->>'aspect_ratio' is distinct from '4:5'
 or p_script->'_reviewed_image_inputs'->>'model' is distinct from 'gemini-2.5-flash-image'
 or jsonb_typeof(p_script->'_scene_performance_v2') is distinct from 'object'
 or p_script ? '_scene_contracts'
 then return jsonb_build_object('hold','VISUAL_RECOVERY_INVALID'); end if;
 select * into e from icg.episode_assets where 'output/episodes/'||episode_date::text||'/panels'=c.scope and episode_no=1 for update;
 if found and e.script_json=p_script and exists(select 1 from icg.image_generation_recovery_receipts
 where terminal_token=p_token and target_revision=p_revision and script_json=p_script and fingerprints=p_fingerprints
 and evidence='actor='||p_actor||'; '||p_note and actual_cost=p_actual_cost)
 then return jsonb_build_object('registered',true,'revision',p_revision); end if;
 if not found or e.status<>'narrative_done' or e.script_json is distinct from p_expected_script
 or coalesce(e.error_message,'') like 'PUBLISH_HOLD:%'
 or p_revision<=coalesce((p_expected_script->>'_generation_revision')::int,1)
 or p_script->'_visual_policy' is distinct from p_expected_script->'_visual_policy'
 or p_script->'_visual_policy_sha256' is distinct from p_expected_script->'_visual_policy_sha256'
 or exists(select 1 from icg.image_generation_calls where scope=c.scope and (state in ('reserved','unknown') or revision>=p_revision))
 then return jsonb_build_object('hold','VISUAL_RECOVERY_SOURCE_CHANGED_OR_UNSETTLED'); end if;
 if (select jsonb_object_agg(key,value) from jsonb_each(p_script) where key not like '\_%' escape '\' and key<>'panels')
 is distinct from (select jsonb_object_agg(key,value) from jsonb_each(p_expected_script) where key not like '\_%' escape '\' and key<>'panels')
 or jsonb_array_length(p_script->'panels')<>jsonb_array_length(p_expected_script->'panels')
 then return jsonb_build_object('hold','VISUAL_RECOVERY_NARRATIVE_CHANGED'); end if;
 for a,b in select x.p,y.p from jsonb_array_elements(p_script->'panels') with ordinality x(p,n)
 join jsonb_array_elements(p_expected_script->'panels') with ordinality y(p,n) using(n) loop
  if a-'action'-'setting' is distinct from b-'action'-'setting'
   or (b->>'panel_type' in ('TEXT_CARD','DISCLAIMER') and a<>b)
   or p_script->'_scene_performance_v2'->(a->>'idx')->'required_story_facts'
    is distinct from p_expected_script->'_scene_performance_v2'->(b->>'idx')->'required_story_facts'
  then return jsonb_build_object('hold','VISUAL_RECOVERY_STORY_OR_CAST_CHANGED'); end if;
  select * into success from icg.image_generation_calls where scope=c.scope and panel::text=b->>'idx' and state='success';
  if found then
   select x into item from jsonb_array_elements(p_script->'_reviewed_image_inputs'->'panels') x where x->>'idx'=a->>'idx';
   select x into olditem from jsonb_array_elements(p_expected_script->'_reviewed_image_inputs'->'panels') x where x->>'idx'=b->>'idx';
   if a is distinct from b or item->>'reuse_only' is distinct from 'true'
    or item->>'output_hash' is distinct from success.output_hash
    or item->>'fingerprint' is distinct from success.fingerprint
    or (item-'reuse_only'-'output_hash') is distinct from (olditem-'reuse_only'-'output_hash')
    or p_script->'_scene_performance_v2'->(a->>'idx') is distinct from p_expected_script->'_scene_performance_v2'->(b->>'idx')
   then return jsonb_build_object('hold','VISUAL_SUCCESS_REGENERATION_FORBIDDEN'); end if;
  end if;
 end loop;
 if e.visual_policy_json is not null then
  insert into icg.visual_quality_inputs(scope,revision,script_snapshot,policy,policy_sha256,actor,note)
  values(c.scope,p_revision,p_script,e.visual_policy_json,e.visual_policy_sha256,p_actor,p_note);
 end if;
 update icg.episode_assets set script_json=p_script where episode_date=e.episode_date and episode_no=1;
 receipt:=icg.image_generation_acknowledge_terminal(p_token,p_revision,p_actual_cost,p_script,p_fingerprints,'actor='||p_actor||'; '||p_note);
 if receipt?'hold' then raise exception 'Visual recovery acknowledgement failed; transaction rolled back'; end if;
 return jsonb_build_object('registered',true,'revision',p_revision);
end $$;
revoke all on function icg.visual_quality_register_recovery(jsonb,jsonb,uuid,int,numeric,jsonb,text,text) from public,anon,authenticated;
grant execute on function icg.visual_quality_register_recovery(jsonb,jsonb,uuid,int,numeric,jsonb,text,text) to service_role;

create or replace function icg.image_generation_register_recovery_v3(
 p_expected_script jsonb,p_script jsonb,p_token uuid,p_revision integer,
 p_actual_cost numeric,p_fingerprints jsonb,p_actor text,p_note text
) returns jsonb language plpgsql security invoker set search_path='' as $$
declare c icg.image_generation_calls%rowtype; current_script jsonb; receipt jsonb; pair record;
begin
 if p_script->'_reviewed_image_inputs'->>'version'='reviewed-image-inputs-2' then
  return icg.visual_quality_register_recovery(p_expected_script,p_script,p_token,p_revision,p_actual_cost,p_fingerprints,p_actor,p_note);
 end if;
 perform pg_catalog.pg_advisory_xact_lock(731091,1);
 select * into c from icg.image_generation_calls where token=p_token for update;
 if not found or c.state<>'terminal' or p_revision is null or p_revision<=c.revision
 or p_revision>100 or p_actual_cost is null or p_actual_cost<>c.cost
 or coalesce(length(btrim(p_actor)),0)<1 or coalesce(length(btrim(p_note)),0)<20
 or jsonb_typeof(p_script) is distinct from 'object'
 or jsonb_typeof(p_expected_script) is distinct from 'object'
 or p_script->'_state_candidate'->>'version' is distinct from 'state-candidate-1'
 or p_script->'_state_candidate' is distinct from p_expected_script->'_state_candidate'
 or p_script->>'_generation_revision' is distinct from p_revision::text
 or p_script->'_reviewed_image_inputs'->>'version' is distinct from 'reviewed-image-inputs-1'
 or jsonb_typeof(p_script->'_scene_contracts') is distinct from 'object'
 or p_script->'_reviewed_image_inputs'->>'model' is distinct from 'gemini-2.5-flash-image'
 or p_script->'_reviewed_image_inputs'->'aspect_ratio' is distinct from 'null'::jsonb
 or jsonb_typeof(p_script->'panels') is distinct from 'array'
 or jsonb_typeof(p_expected_script->'panels') is distinct from 'array'
 then return jsonb_build_object('hold','invalid reviewed recovery'); end if;
 if (select count(*) from icg.episode_assets e where
  'output/episodes/'||e.episode_date::text||'/panels'=c.scope and e.episode_no=1)<>1
 then return jsonb_build_object('hold','ambiguous recovery episode'); end if;
 select e.script_json into current_script from icg.episode_assets e
 where 'output/episodes/'||e.episode_date::text||'/panels'=c.scope
 and e.episode_no=1 and e.status='narrative_done' for update;
 if found and current_script=p_script and exists(
  select 1 from icg.image_generation_recovery_receipts r where r.terminal_token=p_token
  and r.target_revision=p_revision and r.scope=c.scope and r.actual_cost=p_actual_cost
  and r.script_json=p_script and r.fingerprints=p_fingerprints
  and r.evidence='actor='||p_actor||'; '||p_note)
 then return jsonb_build_object('registered',true,'revision',p_revision,'terminal_token',p_token); end if;
 if not found or current_script is distinct from p_expected_script
 then return jsonb_build_object('hold','recovery source changed'); end if;
 if coalesce(current_script->>'_generation_revision','1') !~ '^[0-9]{1,3}$'
 then return jsonb_build_object('hold','invalid source revision'); end if;
 if p_revision<=coalesce(current_script->>'_generation_revision','1')::integer
 then return jsonb_build_object('hold','recovery revision must advance'); end if;
 if exists(select 1 from icg.image_generation_calls where scope=c.scope
   and (state in ('reserved','unknown') or revision>=p_revision))
 then return jsonb_build_object('hold','recovery revision already started or unsettled'); end if;
 -- Keep public narrative and its thread evidence; only action/setting can change.
 if (select jsonb_object_agg(key,value) from jsonb_each(p_script)
     where key not like '\_%' escape '\' and key<>'panels') is distinct from
    (select jsonb_object_agg(key,value) from jsonb_each(p_expected_script)
     where key not like '\_%' escape '\' and key<>'panels')
 or jsonb_array_length(p_script->'panels')<>jsonb_array_length(p_expected_script->'panels')
 then return jsonb_build_object('hold','public narrative changed'); end if;
 for pair in select a.value as new_panel,b.value as old_panel
 from jsonb_array_elements(p_script->'panels') with ordinality a(value,n)
 join jsonb_array_elements(p_expected_script->'panels') with ordinality b(value,n) using(n) loop
  if pair.new_panel-'action'-'setting' is distinct from pair.old_panel-'action'-'setting'
  or (pair.old_panel->>'panel_type' in ('TEXT_CARD','DISCLAIMER') and pair.new_panel<>pair.old_panel)
  then return jsonb_build_object('hold','panel narrative or cast changed'); end if;
 end loop;
 update icg.episode_assets set script_json=p_script where
 'output/episodes/'||episode_date::text||'/panels'=c.scope and episode_no=1;
 receipt:=icg.image_generation_acknowledge_terminal(p_token,p_revision,p_actual_cost,p_script,
   p_fingerprints,'actor='||p_actor||'; '||p_note);
 if receipt ? 'hold' then
  -- Raise, not return, so the script update rolls back with failed authorization.
  raise exception 'Recovery receipt rejected; registration rolled back';
 end if;
 return jsonb_build_object('registered',true,'revision',p_revision,'terminal_token',p_token);
end $$;
