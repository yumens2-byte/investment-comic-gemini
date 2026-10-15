-- Additive v5 contract. No policy activation or historical-slot rewriting.
begin;
alter table icg_side.talk_policy drop constraint talk_policy_policy_version_check;
alter table icg_side.talk_policy add check (policy_version in (4,5));
alter table icg_side.talk_slots add column normal_end timestamptz;
create table icg_side.talk_recovery (
 page_id text not null references icg_side.talk_policy,
 slot_date date not null,
 execution_count integer not null default 0 check (execution_count between 0 and 3),
 verification_retry_count integer not null default 0 check (verification_retry_count between 0 and 3),
 next_retry_at timestamptz,
 lease_owner uuid,
 lease_expires_at timestamptz,
 mode text check(mode in ('normal','recovery','verify')),
 last_status text,
 last_reason text,
 last_run_id text,
 primary key(page_id,slot_date)
);
alter table icg_side.talk_recovery enable row level security;
revoke all on icg_side.talk_recovery from public,anon,authenticated;
grant select,insert,update on icg_side.talk_recovery to service_role;
create function icg_side.talk_contract_version_v5() returns integer
language sql stable security invoker set search_path='' as $$select 5$$;

create function icg_side.talk_snapshot_v5(p_page text,p_day date)
returns jsonb language sql security invoker set search_path='' as $$
select jsonb_build_object(
 'db_now',clock_timestamp(),'slot_date',p_day,
 'policy',(select to_jsonb(p) from icg_side.talk_policy p where p.page_id=p_page),
 'slot',(select to_jsonb(s) from icg_side.talk_slots s where s.page_id=p_page and s.slot_date=p_day),
 'recovery',(select to_jsonb(r) from icg_side.talk_recovery r where r.page_id=p_page and r.slot_date=p_day),
 'unresolved',(select count(*) from icg_side.facebook_deliveries d where d.page_id=p_page and d.track='talk' and d.state in ('SENDING','UNKNOWN')),
 'deliveries',coalesce((select jsonb_agg(jsonb_build_object('revision',d.business_key,'state',d.state,'post_id',d.post_id,
   'verified',exists(select 1 from icg_side.talk_run_events e where e.page_id=p_page and e.slot_date=p_day and e.revision=d.business_key and e.status='PUBLISHED' and e.reason_code='PUBLISHED_VERIFIED')))
   from icg_side.facebook_deliveries d where d.page_id=p_page and d.track='talk' and (d.started_at at time zone 'Asia/Seoul')::date=p_day),'[]'::jsonb),
 'drafts',coalesce((select jsonb_agg(jsonb_build_object('revision',t.revision,'status',t.status)) from icg_side.talk_items t where t.page_id=p_page and (t.due_at at time zone 'Asia/Seoul')::date=p_day),'[]'::jsonb),
 'models',coalesce((select jsonb_agg(jsonb_build_object('phase',m.phase,'state',m.state)) from icg_side.talk_model_attempts m where m.page_id=p_page and (m.updated_at at time zone 'Asia/Seoul')::date=p_day),'[]'::jsonb),
 'cost_count',(select count(*) from icg_side.talk_costs c where c.page_id=p_page and (c.created_at at time zone 'Asia/Seoul')::date=p_day)
)
$$;

create function icg_side.talk_schedule_ensure_v5(p_page text,p_day date,p_due timestamptz)
returns jsonb language plpgsql security invoker set search_path='' as $$
declare p icg_side.talk_policy; s icg_side.talk_slots;
begin
 select * into p from icg_side.talk_policy where page_id=p_page for update;
 if p.page_id is null or p.policy_version<>5 then raise exception 'v5 policy required'; end if;
 if p_day is null or p_due is null or p_day<>(clock_timestamp() at time zone 'Asia/Seoul')::date
 or p_day<p.effective_from or extract(isodow from p_day)>5
 or (p_due at time zone 'Asia/Seoul')::date<>p_day
 or (p_due at time zone 'Asia/Seoul')::time not between time '13:00' and time '17:30'
 or date_trunc('minute',p_due)<>p_due then raise exception 'invalid current-day schedule'; end if;
 insert into icg_side.talk_slots(page_id,slot_date,due_at,window_end,normal_end,status,reason_code,policy_version,schedule_origin)
 values(p_page,p_day,p_due,(p_day+time '23:30') at time zone 'Asia/Seoul',
 (p_day+time '18:00') at time zone 'Asia/Seoul','WAITING_SLOT','WAITING_SLOT',5,'actions_watchdog')
 on conflict(page_id,slot_date) do nothing;
 select * into s from icg_side.talk_slots where page_id=p_page and slot_date=p_day;
 return to_jsonb(s)||jsonb_build_object('db_now',clock_timestamp());
end $$;

create function icg_side.talk_preflight_v5(p_page text,p_day date,p_mode text,p_owner uuid default null)
returns jsonb language plpgsql security invoker set search_path='' as $$
declare p icg_side.talk_policy;s icg_side.talk_slots;r icg_side.talk_recovery;ts timestamptz;
 ds timestamptz;ws timestamptz; code text;
begin
 select * into p from icg_side.talk_policy where page_id=p_page for update;
 ts:=clock_timestamp();
 select * into s from icg_side.talk_slots where page_id=p_page and slot_date=p_day;
 select * into r from icg_side.talk_recovery where page_id=p_page and slot_date=p_day;
 ds:=(p_day+time '00:00') at time zone 'Asia/Seoul';
 ws:=date_trunc('week',p_day::timestamp) at time zone 'Asia/Seoul';
 code:=case
 when p_mode is null or p_mode not in ('normal','recovery') then 'INVALID_MODE'
 when p.page_id is null or not p.enabled then 'CHANNEL_HOLD'
 when p.policy_version<>5 or p_day<p.effective_from then 'POLICY_NOT_EFFECTIVE'
 when p_day is null or p_day<>(ts at time zone 'Asia/Seoul')::date or extract(isodow from p_day)>5 then 'OUTSIDE_RECOVERY_DAY'
 when s.page_id is null then 'SLOT_REQUIRED'
 when s.policy_version<>5 then 'LEGACY_SLOT'
 when exists(select 1 from icg_side.facebook_deliveries where page_id=p_page and track='talk' and state in ('SENDING','UNKNOWN')) then 'RECONCILE_REQUIRED'
 when exists(select 1 from icg_side.facebook_deliveries where page_id=p_page and track='talk' and state='PUBLISHED' and published_at>=ds and published_at<ds+interval '1 day') then 'ALREADY_PUBLISHED'
 when ts>=s.window_end then 'MISSED_FINAL'
 when p_mode='normal' and ts>=s.normal_end then 'PENDING_RECOVERY'
 when ts<s.due_at then 'WAITING_SLOT'
 when (select count(*) from icg_side.facebook_deliveries where page_id=p_page and track='talk' and state='PUBLISHED' and published_at>=ws and published_at<ws+interval '7 days')>=p.week_limit then 'TALK_LIMIT'
 when p_owner is not null and (r.lease_owner is distinct from p_owner or r.lease_expires_at is null or r.lease_expires_at<=ts or r.mode is distinct from p_mode) then 'CLAIM_LOST'
 else 'READY' end;
 return jsonb_build_object('status',code,'db_now',ts,'due_at',s.due_at,'window_end',s.window_end,'normal_end',s.normal_end,'policy_version',s.policy_version);
end $$;

create function icg_side.talk_execution_claim_v5(p_page text,p_day date,p_mode text,p_owner uuid,p_run text)
returns jsonb language plpgsql security invoker set search_path='' as $$
declare r icg_side.talk_recovery; snap jsonb; gate jsonb; ts timestamptz; n integer;
begin
 if p_owner is null or p_run is null or p_run !~ '^[A-Za-z0-9:_-]{1,120}$'
 or p_mode is null or p_mode not in ('normal','recovery','verify') then raise exception 'invalid claim'; end if;
 perform 1 from icg_side.talk_policy where page_id=p_page for update;
 if not found then return jsonb_build_object('status','CHANNEL_HOLD'); end if;
 ts:=clock_timestamp();
 insert into icg_side.talk_recovery(page_id,slot_date) values(p_page,p_day) on conflict do nothing;
 select * into r from icg_side.talk_recovery where page_id=p_page and slot_date=p_day for update;
 if r.lease_expires_at>ts then return jsonb_build_object('status','IN_PROGRESS'); end if;
 if r.next_retry_at>ts then return jsonb_build_object('status','RETRY_WAIT'); end if;
 snap:=icg_side.talk_snapshot_v5(p_page,p_day);
 if (snap->>'unresolved')::integer>0 then return jsonb_build_object('status','RECONCILE_REQUIRED'); end if;
 if p_mode='verify' then
   select count(*) into n from jsonb_array_elements(snap->'deliveries') d where d->>'state'='PUBLISHED' and coalesce(d->>'post_id','')<>'';
   if n<>1 or r.verification_retry_count>=3 then return jsonb_build_object('status','VERIFY_BLOCKED'); end if;
   if exists(select 1 from jsonb_array_elements(snap->'deliveries') d where (d->>'verified')::boolean) then return jsonb_build_object('status','WATCH_OK'); end if;
 else
   gate:=icg_side.talk_preflight_v5(p_page,p_day,p_mode);
   if gate->>'status'<>'READY' then return gate; end if;
   if r.execution_count>=3 then return jsonb_build_object('status','RETRY_EXHAUSTED'); end if;
   if r.last_status='HOLD' then return jsonb_build_object('status','HOLD'); end if;
   if exists(select 1 from jsonb_array_elements(snap->'deliveries') d where d->>'state' not in ('RETRY_WAIT'))
    or jsonb_array_length(snap->'drafts')>1
    or exists(select 1 from jsonb_array_elements(snap->'drafts') t where t->>'status'='CONTENT_HOLD')
    or exists(select 1 from jsonb_array_elements(snap->'models') m where m->>'state'<>'COMPLETE')
    or ((snap->>'cost_count')::integer>jsonb_array_length(snap->'models'))
    or (jsonb_array_length(snap->'drafts')=0 and jsonb_array_length(snap->'models')>0)
    or (exists(select 1 from jsonb_array_elements(snap->'drafts') t where t->>'status'='DRAFT')
        and exists(select 1 from jsonb_array_elements(snap->'models') m where m->>'phase'='review'))
   then return jsonb_build_object('status','RESULT_REVIEW_REQUIRED'); end if;
 end if;
 update icg_side.talk_recovery set
 execution_count=execution_count+case when p_mode='verify' then 0 else 1 end,
 verification_retry_count=verification_retry_count+case when p_mode='verify' then 1 else 0 end,
 lease_owner=p_owner,lease_expires_at=ts+interval '15 minutes',mode=p_mode,last_run_id=p_run
 where page_id=p_page and slot_date=p_day returning * into r;
 return to_jsonb(r)||jsonb_build_object('status','CLAIMED','db_now',ts);
end $$;

create function icg_side.talk_execution_finish_v5(p_page text,p_day date,p_owner uuid,p_status text,p_reason text,p_retryable boolean)
returns boolean language plpgsql security invoker set search_path='' as $$
declare r icg_side.talk_recovery; delay_seconds integer;
begin
 select * into r from icg_side.talk_recovery where page_id=p_page and slot_date=p_day for update;
 if not found or r.lease_owner is distinct from p_owner then raise exception 'claim lost'; end if;
 if p_status is null or p_status !~ '^[A-Z_]{2,60}$' or p_reason is null or p_reason !~ '^[A-Z0-9_]{2,100}$'
 or p_retryable is null then raise exception 'invalid safe outcome'; end if;
 delay_seconds:=case when r.mode='verify' then
   case r.verification_retry_count when 1 then 300 else 900 end
   when p_status='POSTED_UNVERIFIED' then 60
   when r.execution_count=1 then 600 else 1800 end;
 update icg_side.talk_recovery set last_status=case when p_retryable or p_status='PUBLISHED' then p_status else 'HOLD' end,
 last_reason=p_reason,lease_owner=null,lease_expires_at=null,
 next_retry_at=case when p_retryable then clock_timestamp()+make_interval(secs=>delay_seconds) else null end
 where page_id=p_page and slot_date=p_day;
 return true;
end $$;

create function icg_side.talk_begin_v5(p_page text,p_key text,p_track text,p_body_hash text,p_expires timestamptz,p_owner uuid,p_mode text)
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
 if p_owner is null then raise exception 'claim required'; end if;
 ts:=clock_timestamp();
 r:=icg_side.talk_preflight_v5(p_page,(ts at time zone 'Asia/Seoul')::date,p_mode,p_owner);
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


create function icg_side.talk_cost_reserve_v5(p_page text,p_key text,p_amount numeric,p_owner uuid,p_mode text)
returns boolean language plpgsql security invoker set search_path='' as $$
declare r jsonb;
begin
 if p_owner is null then raise exception 'claim required'; end if;
 r:=icg_side.talk_preflight_v5(p_page,(clock_timestamp() at time zone 'Asia/Seoul')::date,p_mode,p_owner);
 if r->>'status'<>'READY' then raise exception 'paid admission denied'; end if;
 if not icg_side.talk_cost_reserve(p_page,p_key,p_amount) then raise exception 'duplicate cost reservation'; end if;
 return true;
end $$;
do $$ declare f record; begin
 for f in select p.oid::regprocedure as signature from pg_proc p join pg_namespace n on n.oid=p.pronamespace
 where n.nspname='icg_side' and p.proname like '%_v5' loop
 execute format('revoke all on function %s from public,anon,authenticated',f.signature);
 execute format('grant execute on function %s to service_role',f.signature);
 end loop;
end $$;
notify pgrst,'reload schema';
commit;
