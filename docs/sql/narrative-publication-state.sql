-- Deployment proposal, not applied to production.
-- Register through the Supabase CLI migration workflow before rollout.
create or replace function icg.publication_state_preflight(p_date date,p_no integer,p_candidate jsonb)
returns jsonb language plpgsql security invoker set search_path='' as $$
declare e icg.episode_assets; a jsonb;
begin
 select * into e from icg.episode_assets where episode_date=p_date and episode_no=p_no;
 if not found or e.status not in ('assembled','image_generated')
 or p_candidate->>'version' is distinct from 'state-candidate-1'
 or p_candidate->>'episode_date' is distinct from p_date::text
 or e.script_json->'_state_candidate' is distinct from p_candidate
 or e.script_json->'_assembly_manifest' is null
 then return jsonb_build_object('ready',false); end if;
 if exists(select 1 from icg.published_comics where publish_date=p_date and episode_no=p_no)
 then return jsonb_build_object('ready',false); end if;
 if p_candidate->'base_arc' <> 'null'::jsonb then
 select to_jsonb(s) into a from icg.arc_state s where id=1;
 if a is distinct from p_candidate->'base_arc' then return jsonb_build_object('ready',false); end if;
 end if;
 return jsonb_build_object('ready',true);
end $$;
create or replace function icg.record_episode_delivery(p_date date,p_no integer,p_token text,p_channel text,p_ids jsonb)
returns jsonb language plpgsql security invoker set search_path='' as $$
declare e icg.episode_assets; receipts jsonb;
begin
 select * into strict e from icg.episode_assets where episode_date=p_date and episode_no=p_no for update;
 if e.error_message is distinct from p_token or p_token not like 'PUBLISH_HOLD:%'
 or e.status not in ('assembled','image_generated')
 or (p_channel<>'x' and p_channel not like 'telegram:%')
 or jsonb_typeof(p_ids) is distinct from 'array' or jsonb_array_length(p_ids)=0
 then raise exception 'invalid delivery claim'; end if;
 if exists(select 1 from jsonb_array_elements_text(p_ids) v where v is null or v='' or v='0')
 then raise exception 'invalid delivery ids'; end if;
 receipts:=coalesce(e.script_json->'_delivery_receipts','{}'::jsonb);
 receipts:=jsonb_set(receipts,array[p_channel],coalesce(receipts->p_channel,'[]'::jsonb)||p_ids,true);
 update icg.episode_assets set script_json=jsonb_set(script_json,'{_delivery_receipts}',receipts,true) where id=e.id;
 return jsonb_build_object('recorded',true);
end $$;
create or replace function icg.finalize_episode_publication(
 p_date date,p_no integer,p_candidate jsonb,p_tweet_ids jsonb,p_telegram jsonb,
 p_slide_count integer,p_cost numeric,p_runtime numeric)
returns jsonb language plpgsql security invoker set search_path='' as $$
declare e icg.episode_assets; current_arc jsonb; r jsonb; pair record; after_arc icg.arc_state;
begin
 perform pg_catalog.pg_advisory_xact_lock(731092,1);
 select * into strict e from icg.episode_assets where episode_date=p_date and episode_no=p_no for update;
 if e.status='published' and e.script_json->'_state_committed'='true'::jsonb
 and e.script_json->'_state_candidate'=p_candidate
 and coalesce(e.script_json->'_delivery_receipts'->'x','[]'::jsonb)=p_tweet_ids
 then return jsonb_build_object('committed',true); end if;
 if (icg.publication_state_preflight(p_date,p_no,p_candidate)->>'ready') is distinct from 'true'
 or e.error_message is null or e.error_message not like 'PUBLISH_HOLD:%'
 or p_slide_count is null or p_slide_count<=0 or p_cost is null or p_cost<0
 or p_runtime is null or p_runtime<0
 or jsonb_typeof(p_tweet_ids) is distinct from 'array'
 or jsonb_typeof(p_telegram) is distinct from 'object'
 then raise exception 'publication state contract failed'; end if;
 r:=coalesce(e.script_json->'_delivery_receipts','{}'::jsonb);
 if coalesce(r->'x','[]'::jsonb) is distinct from p_tweet_ids then raise exception 'X receipt mismatch'; end if;
 for pair in select * from jsonb_each(p_telegram) loop
 if r->('telegram:'||pair.key) is distinct from pair.value
 or jsonb_typeof(pair.value) is distinct from 'array' or jsonb_array_length(pair.value)=0
 then raise exception 'Telegram receipt mismatch'; end if;
 end loop;
 if jsonb_array_length(p_tweet_ids)=0 and p_telegram='{}'::jsonb then raise exception 'no delivery'; end if;
 if p_candidate->'arc_after'<>'null'::jsonb then
 select to_jsonb(s) into current_arc from icg.arc_state s where id=1 for update;
 if current_arc is distinct from p_candidate->'base_arc' then raise exception 'state version conflict'; end if;
 after_arc:=jsonb_populate_record(null::icg.arc_state,p_candidate->'arc_after');
 update icg.arc_state set ("arc_day","open_hook","arc_tension","edt_pressure","last_outcome","pair_tension","hero_momentum","active_villain","crowd_momentum","villain_streak","form2_available","form3_activated","hero_win_streak","season_arc_days","defeated_villains","last_episode_date","last_episode_type","villain_signature","emergence_deficit_days","volatility_fields_active","zero_block_just_appeared","dimensional_rift_progress",updated_at)=
 (select after_arc."arc_day",after_arc."open_hook",after_arc."arc_tension",after_arc."edt_pressure",after_arc."last_outcome",after_arc."pair_tension",after_arc."hero_momentum",after_arc."active_villain",after_arc."crowd_momentum",after_arc."villain_streak",after_arc."form2_available",after_arc."form3_activated",after_arc."hero_win_streak",after_arc."season_arc_days",after_arc."defeated_villains",after_arc."last_episode_date",after_arc."last_episode_type",after_arc."villain_signature",after_arc."emergence_deficit_days",after_arc."volatility_fields_active",after_arc."zero_block_just_appeared",after_arc."dimensional_rift_progress",clock_timestamp()) where id=1;
 end if;
 if p_candidate->'story_after'<>'null'::jsonb then
 update icg.daily_analysis set story_state_json=p_candidate->'story_after' where analysis_date=p_date;
 if not found then raise exception 'analysis row missing'; end if;
 end if;
 insert into icg.published_comics(publish_date,comic_type,episode_no,risk_level,tweet_id,cut_count,cost_usd,status)
 values(p_date,e.event_type,p_no,coalesce(e.script_json->>'risk_level','MEDIUM'),p_tweet_ids->>0,p_slide_count,p_cost,'published');
 update icg.episode_assets set status='published',total_runtime_sec=p_runtime,
 script_json=jsonb_set(script_json,'{_state_committed}','true'::jsonb,true) where id=e.id;
 return jsonb_build_object('committed',true);
end $$;
revoke all on function icg.publication_state_preflight(date,integer,jsonb) from public,anon,authenticated;
revoke all on function icg.record_episode_delivery(date,integer,text,text,jsonb) from public,anon,authenticated;
revoke all on function icg.finalize_episode_publication(date,integer,jsonb,jsonb,jsonb,integer,numeric,numeric) from public,anon,authenticated;
grant execute on function icg.publication_state_preflight(date,integer,jsonb) to service_role;
grant execute on function icg.record_episode_delivery(date,integer,text,text,jsonb) to service_role;
grant execute on function icg.finalize_episode_publication(date,integer,jsonb,jsonb,jsonb,integer,numeric,numeric) to service_role;
notify pgrst,'reload schema';
