-- Additive proposal. Apply after the existing retry and recovery contracts.
-- Registers reviewed source-bound alternatives before paid calls, never in a refusal callback.
create function icg.image_generation_register_repair_plans_v2(
 p_expected_script jsonb,p_script jsonb,p_fingerprints jsonb
) returns jsonb language plpgsql security invoker set search_path='' as $$
declare current_script jsonb; bundle jsonb; fps jsonb; item record;
 target_scope text; revision_no integer; required_count integer;
begin
 perform pg_catalog.pg_advisory_xact_lock(731091,1);
 if jsonb_typeof(p_script) is distinct from 'object'
 or jsonb_typeof(p_expected_script) is distinct from 'object'
 or jsonb_typeof(p_fingerprints) is distinct from 'object'
 or jsonb_typeof(p_script->'panels') is distinct from 'array'
 or jsonb_typeof(p_script->'_reviewed_image_retry_plans') is distinct from 'object'
 or (p_script-'_reviewed_image_retry_plans') is distinct from
    (p_expected_script-'_reviewed_image_retry_plans')
 or coalesce(p_script->>'date','') !~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
 or coalesce(p_script->>'_generation_revision','') !~ '^[0-9]{1,3}$'
 then return jsonb_build_object('hold','invalid repair candidate'); end if;
 revision_no:=(p_script->>'_generation_revision')::integer;
 if revision_no not between 1 and 100
 then return jsonb_build_object('hold','invalid repair revision'); end if;
 target_scope:='output/episodes/'||(p_script->>'date')||'/panels';
 if (select count(*) from icg.episode_assets e where e.episode_date::text=p_script->>'date'
     and e.episode_no=1)<>1
 then return jsonb_build_object('hold','ambiguous repair episode'); end if;
 select e.script_json into current_script from icg.episode_assets e
 where e.episode_date::text=p_script->>'date' and e.episode_no=1
 and e.status='narrative_done' for update;
 if not found then return jsonb_build_object('hold','repair episode unavailable'); end if;
 if current_script is distinct from p_expected_script and current_script is distinct from p_script
 then return jsonb_build_object('hold','repair source changed'); end if;
 if exists(select 1 from icg.image_generation_calls c where c.scope=target_scope
 and c.state<>'success')
 then return jsonb_build_object('hold','existing failure requires explicit recovery'); end if;
 select count(*) into required_count from jsonb_array_elements(p_script->'panels') p
 where p->>'panel_type' not in ('TEXT_CARD','DISCLAIMER');
 if required_count=0 or required_count<>(select count(*) from jsonb_object_keys(p_fingerprints))
 or required_count<>(select count(*) from jsonb_object_keys(p_script->'_reviewed_image_retry_plans'))
 then return jsonb_build_object('hold','repair coverage mismatch'); end if;
 -- Validate every row before writing anything.
 for item in select p from jsonb_array_elements(p_script->'panels') p
 where p->>'panel_type' not in ('TEXT_CARD','DISCLAIMER') loop
  bundle:=p_script->'_reviewed_image_retry_plans'->(item.p->>'idx');
  fps:=p_fingerprints->(item.p->>'idx');
  if coalesce(item.p->>'idx','') !~ '^[1-9][0-9]*$'
  or jsonb_typeof(bundle) is distinct from 'object'
  or bundle->>'version' is distinct from 'image-retry-plan-2'
  or coalesce(bundle->>'plan_id','') !~ '^[0-9a-f]{64}$'
  or jsonb_typeof(bundle->'prompts') is distinct from 'array'
  or jsonb_typeof(bundle->'review'->'repairs') is distinct from 'array'
  or jsonb_typeof(fps) is distinct from 'array'
  then return jsonb_build_object('hold','invalid repair plan'); end if;
  if jsonb_array_length(fps) not between 2 and 3
  or jsonb_array_length(bundle->'prompts')<>jsonb_array_length(fps)
  or jsonb_array_length(bundle->'review'->'repairs')<>jsonb_array_length(fps)-1
  or jsonb_array_length(fps)<>(select count(distinct v) from jsonb_array_elements_text(fps) v)
  or exists(select 1 from jsonb_array_elements_text(fps) f where f.value !~ '^[0-9a-f]{64}$')
  or coalesce(length(btrim(bundle->'review'->>'actor')),0)<1
  or coalesce(length(btrim(bundle->'review'->>'review_note')),0)<20
  or bundle->'review'->'source'->'cast' is distinct from item.p->'characters'
  or bundle->'review'->'source'->>'action' is distinct from item.p->>'action'
  or bundle->'review'->'source'->>'setting' is distinct from item.p->>'setting'
  or bundle->'review'->'source'->>'narration' is distinct from item.p->>'narration'
  or exists(select 1 from icg.image_generation_calls c where c.scope=target_scope
            and c.panel=(item.p->>'idx')::integer and c.fingerprint is distinct from fps->>0)
  then return jsonb_build_object('hold','repair review or success identity changed'); end if;
  if exists(select 1 from icg.image_generation_retry_plans rp
   where rp.scope=target_scope and rp.panel=(item.p->>'idx')::integer
   and (rp.plan_id<>bundle->>'plan_id' or rp.script_json<>p_script or rp.fingerprints<>fps))
  then return jsonb_build_object('hold','repair plan is immutable'); end if;
 end loop;
 -- CAS the exact source and register all panel plans in one transaction.
 update icg.episode_assets e set script_json=p_script
 where e.episode_date::text=p_script->>'date' and e.episode_no=1;
 for item in select p from jsonb_array_elements(p_script->'panels') p
 where p->>'panel_type' not in ('TEXT_CARD','DISCLAIMER') loop
  bundle:=p_script->'_reviewed_image_retry_plans'->(item.p->>'idx');
  insert into icg.image_generation_retry_plans(plan_id,scope,panel,revision,fingerprints,script_json,review_evidence)
  values(bundle->>'plan_id',target_scope,(item.p->>'idx')::integer,revision_no,
    p_fingerprints->(item.p->>'idx'),p_script,
    'actor='||(bundle->'review'->>'actor')||'; '||(bundle->'review'->>'review_note'))
  on conflict(plan_id,scope,panel) do nothing;
 end loop;
 return jsonb_build_object('registered',true,'panels',required_count,'revision',revision_no);
end $$;
revoke all on function icg.image_generation_register_repair_plans_v2(jsonb,jsonb,jsonb)
 from public,anon,authenticated;
grant execute on function icg.image_generation_register_repair_plans_v2(jsonb,jsonb,jsonb)
 to service_role;
notify pgrst,'reload schema';
