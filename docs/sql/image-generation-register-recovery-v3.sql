-- After revision/recovery/retry SQL. Atomic compare-and-set registration only.
-- No provider call, no deletion/reset, no change to publication status.
create function icg.image_generation_register_recovery_v3(
 p_expected_script jsonb,p_script jsonb,p_token uuid,p_revision integer,
 p_actual_cost numeric,p_fingerprints jsonb,p_actor text,p_note text
) returns jsonb language plpgsql security invoker set search_path='' as $$
declare c icg.image_generation_calls%rowtype; current_script jsonb; receipt jsonb; pair record;
begin
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
revoke all on function icg.image_generation_register_recovery_v3(jsonb,jsonb,uuid,integer,numeric,jsonb,text,text)
 from public,anon,authenticated;
grant execute on function icg.image_generation_register_recovery_v3(jsonb,jsonb,uuid,integer,numeric,jsonb,text,text)
 to service_role;
notify pgrst,'reload schema';
