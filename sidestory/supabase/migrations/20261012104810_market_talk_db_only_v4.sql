begin;
create table icg_side.talk_policy (
 page_id text primary key references icg_side.facebook_page_policy,
 enabled boolean not null default false,
 day_limit integer not null default 1 check(day_limit=1),
 week_limit integer not null default 5 check(week_limit between 1 and 5),
 timezone text not null default 'Asia/Seoul' check(timezone='Asia/Seoul'),
 policy_version integer not null default 4 check(policy_version=4),
 effective_from date not null default ((clock_timestamp() at time zone 'Asia/Seoul')::date+1),
 hold_reason text not null default 'not activated',
 updated_at timestamptz not null default clock_timestamp(),updated_by text not null default 'migration'
);
insert into icg_side.talk_policy(page_id) select page_id from icg_side.facebook_page_policy;
alter table icg_side.talk_slots add column policy_version integer not null default 3,
 add column schedule_origin text not null default 'legacy';
create index facebook_talk_state_time on icg_side.facebook_deliveries(page_id,track,state,published_at);
create function icg_side.talk_contract_version_v4() returns integer language sql stable security invoker set search_path='' as $$select 4$$;

create function icg_side.talk_schedule_ensure(p_page text,p_day date,p_due timestamptz)
returns jsonb language plpgsql security invoker set search_path='' as $$
declare s icg_side.talk_slots;
begin
 if p_day is null or p_due is null or p_day<>(clock_timestamp() at time zone 'Asia/Seoul')::date
 or extract(isodow from p_day)>5 or (p_due at time zone 'Asia/Seoul')::date<>p_day
 or (p_due at time zone 'Asia/Seoul')::time not between time '13:00' and time '17:30'
 or date_trunc('minute',p_due)<>p_due then raise exception 'invalid current-day schedule'; end if;
 insert into icg_side.talk_policy(page_id) values(p_page) on conflict do nothing;
 insert into icg_side.talk_slots(page_id,slot_date,due_at,window_end,status,reason_code,policy_version,schedule_origin)
 values(p_page,p_day,p_due,(p_day+time '18:00') at time zone 'Asia/Seoul','WAITING_SLOT','WAITING_SLOT',4,'random_afternoon')
 on conflict(page_id,slot_date) do nothing;
 select * into s from icg_side.talk_slots where page_id=p_page and slot_date=p_day;
 return to_jsonb(s)||jsonb_build_object('db_now',clock_timestamp());
end $$;

create function icg_side.talk_preflight_v4(p_page text,p_day date)
returns jsonb language plpgsql security invoker set search_path='' as $$
declare p icg_side.talk_policy;s icg_side.talk_slots; ts timestamptz; ds timestamptz; ws timestamptz; result text;
begin
 select * into p from icg_side.talk_policy where page_id=p_page for update;
 ts:=clock_timestamp();
 select * into s from icg_side.talk_slots where page_id=p_page and slot_date=p_day;
 ds:=(p_day+time '00:00') at time zone 'Asia/Seoul';
 ws:=date_trunc('week',p_day::timestamp) at time zone 'Asia/Seoul';
 result:=case
 when p.page_id is null or not p.enabled then 'CHANNEL_HOLD'
 when p_day is null or p_day<>(ts at time zone 'Asia/Seoul')::date or extract(isodow from p_day)>5 then 'MISSED_WINDOW'
 when p_day<p.effective_from then 'POLICY_NOT_EFFECTIVE'
 when s.page_id is null then 'SLOT_REQUIRED'
 when s.policy_version<>4 then 'LEGACY_SLOT'
 when exists(select 1 from icg_side.facebook_deliveries where page_id=p_page and track='talk' and state in ('SENDING','UNKNOWN')) then 'UNKNOWN'
 when exists(select 1 from icg_side.facebook_deliveries where page_id=p_page and track='talk' and state='PUBLISHED' and published_at>=ds and published_at<ds+interval '1 day') then 'ALREADY_PUBLISHED'
 when ts>=s.window_end then 'MISSED_WINDOW'
 when ts<s.due_at then 'WAITING_SLOT'
 when (select count(*) from icg_side.facebook_deliveries where page_id=p_page and track='talk' and state='PUBLISHED' and published_at>=ws and published_at<ws+interval '7 days')>=p.week_limit then 'TALK_LIMIT'
 else 'READY' end;
 return jsonb_build_object('status',result,'db_now',ts,'due_at',s.due_at,'window_end',s.window_end,'policy_version',s.policy_version);
end $$;

create function icg_side.talk_begin_v4(p_page text,p_key text,p_track text,p_body_hash text,p_expires timestamptz)
returns jsonb language plpgsql security invoker set search_path='' as $$
declare d icg_side.facebook_deliveries;t icg_side.talk_items;s icg_side.talk_slots; r jsonb;ts timestamptz;
begin
 perform 1 from icg_side.talk_policy where page_id=p_page for update;
 if not found then raise exception 'missing talk policy'; end if;
 if p_track is distinct from 'talk' or p_key is null or p_key !~ '^[a-f0-9]{64}$' or p_body_hash is null or p_body_hash !~ '^[a-f0-9]{64}$' then raise exception 'invalid talk identity'; end if;
 select * into d from icg_side.facebook_deliveries where page_id=p_page and business_key=p_key for update;
 if found then
 if d.track<>'talk' or d.body_hash<>p_body_hash then raise exception 'publication payload changed'; end if;
 if d.state='PUBLISHED' then return jsonb_build_object('status','PUBLISHED','post_id',d.post_id); end if;
 if d.state in ('SENDING','UNKNOWN') then return jsonb_build_object('status','UNKNOWN'); end if;
 if d.state<>'RETRY_WAIT' or d.attempt>=3 then return jsonb_build_object('status','REJECTED'); end if;
 end if;
 ts:=clock_timestamp();
 r:=icg_side.talk_preflight_v4(p_page,(ts at time zone 'Asia/Seoul')::date);
 if r->>'status'<>'READY' then return r; end if;
 select * into t from icg_side.talk_items where revision=p_key and page_id=p_page for update;
 select * into s from icg_side.talk_slots where page_id=p_page and slot_date=(ts at time zone 'Asia/Seoul')::date;
 if t.revision is null or t.status<>'APPROVED' or t.approved_at is null or t.send_hash<>p_body_hash
 or t.due_at<>s.due_at or t.expires_at<>s.window_end or p_expires is distinct from t.expires_at
 or clock_timestamp()>=t.expires_at then return jsonb_build_object('status','APPROVAL_OR_TIME_REQUIRED'); end if;
 insert into icg_side.facebook_deliveries(page_id,business_key,track,body_hash,state,started_at)
 values(p_page,p_key,'talk',p_body_hash,'SENDING',clock_timestamp())
 on conflict(page_id,business_key) do update set state='SENDING',token=gen_random_uuid(),attempt=icg_side.facebook_deliveries.attempt+1,started_at=clock_timestamp()
 returning * into d;
 insert into icg_side.talk_audit(page_id,business_key,action,actor,detail)
 values(p_page,p_key,'talk_send_started','worker',jsonb_build_object('token',d.token,'attempt',d.attempt));
 return jsonb_build_object('status','SENDING','token',d.token);
end $$;

create function icg_side.talk_finish_v4(p_page text,p_key text,p_token uuid,p_state text,p_post_id text,p_reason text)
returns boolean language plpgsql security invoker set search_path='' as $$
declare d icg_side.facebook_deliveries;
begin
 perform 1 from icg_side.talk_policy where page_id=p_page for update;
 select * into d from icg_side.facebook_deliveries where page_id=p_page and business_key=p_key and track='talk' for update;
 if not found or d.state<>'SENDING' or d.token is distinct from p_token then raise exception 'claim lost'; end if;
 if p_state is null or p_state not in ('PUBLISHED','UNKNOWN','REJECTED') or (p_state='PUBLISHED' and coalesce(p_post_id,'')='') then raise exception 'invalid outcome'; end if;
 if p_state='PUBLISHED' then delete from icg_side.facebook_deliveries where page_id=p_page and track='external' and post_id=p_post_id; end if;
 update icg_side.facebook_deliveries set state=p_state,post_id=p_post_id,reason=p_reason,
 published_at=case when p_state='PUBLISHED' then clock_timestamp() else null end where page_id=p_page and business_key=p_key and track='talk';
 if p_state='PUBLISHED' and d.track='talk' then update icg_side.talk_items set status='PUBLISHED' where revision=p_key; end if;
 if p_state in ('UNKNOWN','REJECTED') then update icg_side.talk_policy set enabled=false,hold_reason=p_state,updated_at=clock_timestamp(),updated_by='worker' where page_id=p_page; end if;
 insert into icg_side.talk_audit(page_id,business_key,action,actor,detail)
 values(p_page,p_key,p_state,'worker',jsonb_build_object('post_id',p_post_id,'reason',p_reason));
 return true;
end $$;

create function icg_side.talk_set_hold_v4(p_page text,p_actor text,p_reason text,p_enabled boolean)
returns boolean language plpgsql security invoker set search_path='' as $$
begin
 if p_actor is null or p_reason is null or length(trim(p_actor))<1 or length(trim(p_reason))<10 then raise exception 'actor and reason required'; end if;
 perform 1 from icg_side.talk_policy where page_id=p_page for update;
 if not found then raise exception 'Page missing'; end if;
 if p_enabled is null then raise exception 'enabled required'; end if;
 if p_enabled and exists(select 1 from icg_side.facebook_deliveries where page_id=p_page and track='talk' and state in ('SENDING','UNKNOWN')) then raise exception 'unresolved publication'; end if;
 update icg_side.talk_policy set enabled=p_enabled,hold_reason=p_reason,updated_at=clock_timestamp(),updated_by=p_actor where page_id=p_page;
 insert into icg_side.talk_audit(page_id,action,actor,detail) values(p_page,'talk_channel_state',p_actor,jsonb_build_object('enabled',p_enabled,'reason',p_reason));
 return true;
end $$;

create function icg_side.talk_resolve_v4(p_page text,p_key text,p_post_id text,p_published_at timestamptz,p_actor text,p_note text)
returns boolean language plpgsql security invoker set search_path='' as $$
declare d icg_side.facebook_deliveries;
begin
 if p_actor is null or p_note is null or length(trim(p_actor))<1 or length(trim(p_note))<20 then raise exception 'documented operator verification required'; end if;
 perform 1 from icg_side.talk_policy where page_id=p_page for update;
 select * into d from icg_side.facebook_deliveries where page_id=p_page and business_key=p_key and track='talk' for update;
 if not found or d.state not in ('SENDING','UNKNOWN','REJECTED') then raise exception 'not unresolved'; end if;
 if p_post_id is not null then
   if length(trim(p_post_id))=0 or p_published_at is null or p_published_at<d.started_at-interval '5 minutes' or p_published_at>clock_timestamp()+interval '5 minutes' then raise exception 'verified time required'; end if;
   delete from icg_side.facebook_deliveries where page_id=p_page and track='external' and post_id=p_post_id;
   update icg_side.facebook_deliveries set state='PUBLISHED',post_id=p_post_id,published_at=p_published_at,reason=p_note
    where page_id=p_page and business_key=p_key and track='talk';
   if d.track='talk' then update icg_side.talk_items set status='PUBLISHED' where revision=p_key; end if;
 else
   if d.attempt>=3 then raise exception 'attempts exhausted'; end if;
   update icg_side.facebook_deliveries set state='RETRY_WAIT',reason=p_note where page_id=p_page and business_key=p_key and track='talk';
 end if;
 insert into icg_side.talk_audit(page_id,business_key,action,actor,detail)
 values(p_page,p_key,'talk_resolve',p_actor,jsonb_build_object('post_id',p_post_id,'note',p_note));
 -- Does not reactivate the Page automatically.
 return true;
end $$;

create function icg_side.talk_hold_v4(p_revision text,p_actor text,p_note text)
returns boolean language plpgsql security invoker set search_path='' as $$
declare r icg_side.talk_items;
begin
 if p_actor is null or p_note is null or length(trim(p_actor))<1 or length(trim(p_note))<10 then raise exception 'actor and reason required'; end if;
 select * into r from icg_side.talk_items where revision=p_revision;
 if not found then raise exception 'item missing'; end if;
 perform 1 from icg_side.talk_policy where page_id=r.page_id for update;
 select * into r from icg_side.talk_items where revision=p_revision for update;
 if r.status not in ('DRAFT','APPROVED','CONTENT_HOLD') or exists(select 1 from icg_side.facebook_deliveries
 where page_id=r.page_id and business_key=p_revision and track='talk' and state in ('SENDING','UNKNOWN','PUBLISHED'))
 then raise exception 'cannot edit an in-flight or published item'; end if;
 update icg_side.talk_items set status='CONTENT_HOLD',approved_by=null,approved_at=null,approval_note=null where revision=p_revision;
 insert into icg_side.talk_audit(page_id,business_key,action,actor,detail) values(r.page_id,p_revision,'content_hold',p_actor,jsonb_build_object('reason',p_note));
 return true;
end $$;

create function icg_side.talk_record_outcome_v4(p_page text,p_day date,p_run text,p_stage text,p_status text,p_code text,p_revision text)
returns boolean language plpgsql security invoker set search_path='' as $$
begin
 if p_day is null or p_run is null or p_run !~ '^[A-Za-z0-9:_-]{1,120}$'
 or p_stage is null or p_stage not in ('automate','approve','publish','pause','resume','reconcile','hold','verify')
 or p_status is null or p_status !~ '^[A-Z_]{2,60}$'
 or p_code is null or p_code !~ '^[A-Z0-9_]{2,100}$'
 or (p_revision is not null and p_revision !~ '^[a-f0-9]{64}$')
 then raise exception 'invalid safe outcome'; end if;
 if p_status='PUBLISHED' and not exists(select 1 from icg_side.facebook_deliveries where page_id=p_page and business_key=p_revision and track='talk' and state='PUBLISHED' and (started_at at time zone 'Asia/Seoul')::date=p_day)
 then raise exception 'published delivery required'; end if;
 insert into icg_side.talk_run_events(page_id,slot_date,run_id,stage,status,reason_code,revision)
 values(p_page,p_day,p_run,p_stage,p_status,p_code,p_revision);
 -- Operational stages do not overwrite the normal publishing slot summary.
 if p_stage in ('automate','publish','verify') then
 update icg_side.talk_slots set status=p_status,reason_code=p_code,
 revision=coalesce(p_revision,revision),updated_at=clock_timestamp()
 where page_id=p_page and slot_date=p_day
 and (status<>'PUBLISHED' or p_status='PUBLISHED')
 and (p_status not in ('WAITING_SLOT','SOURCE_NOT_READY','DB_READ_FAILED')
      or status in ('WAITING_SLOT','SOURCE_NOT_READY','DB_READ_FAILED','SOURCE_INVALID'));

 end if;
 return true;
end $$;

-- Recheck admission after token-count/network work, immediately at paid reservation.
create function icg_side.talk_cost_reserve_v4(p_page text,p_key text,p_amount numeric)
returns boolean language plpgsql security invoker set search_path='' as $$
declare r jsonb;
begin
 r:=icg_side.talk_preflight_v4(p_page,(clock_timestamp() at time zone 'Asia/Seoul')::date);
 if r->>'status'<>'READY' then raise exception 'talk paid admission denied: %',r->>'status'; end if;
 return icg_side.talk_cost_reserve(p_page,p_key,p_amount);
end $$;

alter table icg_side.talk_policy enable row level security;
revoke all on icg_side.talk_policy from public,anon,authenticated;
grant select,insert,update on icg_side.talk_policy to service_role;
do $$ declare f record; begin
 for f in select p.oid::regprocedure as signature from pg_proc p join pg_namespace n on n.oid=p.pronamespace
 where n.nspname='icg_side' and (p.proname like '%_v4' or p.proname='talk_schedule_ensure') loop
 execute format('revoke all on function %s from public,anon,authenticated',f.signature);
 execute format('grant execute on function %s to service_role',f.signature);
 end loop;
end $$;
notify pgrst,'reload schema';
commit;
