-- Apply only after the existing icg_side migration. No main-track writes.
-- SECURITY INVOKER throughout. Only the backend service role receives access.
begin;
create table icg_side.facebook_page_policy (
 page_id text primary key, enabled boolean not null default false,
 page_day_limit integer not null default 2 check(page_day_limit between 1 and 2),
 talk_day_limit integer not null default 1 check(talk_day_limit = 1),
 talk_week_limit integer not null default 5 check(talk_week_limit between 1 and 5),
 min_gap_seconds integer not null default 14400 check(min_gap_seconds >= 14400),
 daily_budget_usd numeric(12,6) not null default 0 check(daily_budget_usd >= 0),
 monthly_budget_usd numeric(12,6) not null default 0 check(monthly_budget_usd >= 0),
 observed_at timestamptz, exclusive_managed boolean not null default false,
 hold_reason text not null default 'not activated'
);
create table icg_side.talk_items (
 revision text primary key check(length(revision)=64), page_id text not null references icg_side.facebook_page_policy,
 semantic_key text not null, body_hash text not null, send_hash text not null, body text not null, creative text not null,
 payload jsonb not null, status text not null default 'DRAFT' check(status in ('DRAFT','APPROVED','PUBLISHED','CONTENT_HOLD')),
 due_at timestamptz not null, expires_at timestamptz not null, created_at timestamptz not null default now(),
 approved_by text, approved_at timestamptz, approval_note text,
 check(due_at < expires_at)
);
create unique index talk_active_claim on icg_side.talk_items(page_id,semantic_key) where status <> 'CONTENT_HOLD';
create unique index talk_active_body on icg_side.talk_items(page_id,body_hash) where status <> 'CONTENT_HOLD';
create index talk_due on icg_side.talk_items(status,due_at);
create table icg_side.facebook_deliveries (
 page_id text not null references icg_side.facebook_page_policy, business_key text not null,
 track text not null check(track in ('talk','sidestory','external')),
 body_hash text not null, state text not null check(state in ('SENDING','UNKNOWN','REJECTED','RETRY_WAIT','PUBLISHED')),
 token uuid not null default gen_random_uuid(), attempt integer not null default 1 check(attempt between 1 and 3),
 started_at timestamptz not null default now(), published_at timestamptz, post_id text,
 reason text not null default '', primary key(page_id,business_key), unique(page_id,post_id)
);
create index facebook_recent on icg_side.facebook_deliveries(page_id,published_at);
create table icg_side.talk_audit (
 id bigint generated always as identity primary key, at timestamptz not null default now(),
 page_id text not null, business_key text, action text not null, actor text not null, detail jsonb not null default '{}'
);
create table icg_side.talk_costs (
 page_id text not null references icg_side.facebook_page_policy, request_key text not null,
 amount numeric(12,6) not null check(amount > 0), created_at timestamptz not null default now(),
 primary key(page_id,request_key)
);
create or replace function icg_side.talk_immutable() returns trigger language plpgsql security invoker set search_path='' as $$
begin
 if (new.revision,new.page_id,new.semantic_key,new.body_hash,new.send_hash,new.body,new.creative,new.payload,new.due_at,new.expires_at)
    is distinct from
    (old.revision,old.page_id,old.semantic_key,old.body_hash,old.send_hash,old.body,old.creative,old.payload,old.due_at,old.expires_at)
 then raise exception 'immutable revision: create a new reviewed item'; end if;
 return new;
end $$;
create trigger talk_revision_immutable before update on icg_side.talk_items for each row execute function icg_side.talk_immutable();

create or replace function icg_side.talk_approve(p_revision text,p_actor text,p_note text)
returns jsonb language plpgsql security invoker set search_path='' as $$
declare r icg_side.talk_items;
begin
 if length(trim(p_actor)) < 1 or length(trim(p_note)) < 10 then raise exception 'reviewer and meaningful evidence/canon review note required'; end if;
 select * into r from icg_side.talk_items where revision=p_revision for update;
 if not found or r.status <> 'DRAFT' or r.expires_at <= now() then raise exception 'draft missing or expired'; end if;
 update icg_side.talk_items set status='APPROVED', approved_by=p_actor, approved_at=now(), approval_note=p_note where revision=p_revision;
 insert into icg_side.talk_audit(page_id,business_key,action,actor,detail) values(r.page_id,p_revision,'approve',p_actor,jsonb_build_object('note',p_note));
 return jsonb_build_object('status','APPROVED');
end $$;

create or replace function icg_side.talk_hold(p_revision text,p_actor text,p_note text)
returns boolean language plpgsql security invoker set search_path='' as $$
declare r icg_side.talk_items;
begin
 if length(trim(p_actor))<1 or length(trim(p_note))<10 then raise exception 'actor and reason required'; end if;
 select * into r from icg_side.talk_items where revision=p_revision;
 if not found then raise exception 'item missing'; end if;
 perform 1 from icg_side.facebook_page_policy where page_id=r.page_id for update;
 select * into r from icg_side.talk_items where revision=p_revision for update;
 if r.status not in ('DRAFT','APPROVED','CONTENT_HOLD') or exists(select 1 from icg_side.facebook_deliveries
 where page_id=r.page_id and business_key=p_revision and state in ('SENDING','UNKNOWN','PUBLISHED'))
 then raise exception 'cannot edit an in-flight or published item'; end if;
 update icg_side.talk_items set status='CONTENT_HOLD',approved_by=null,approved_at=null,approval_note=null where revision=p_revision;
 insert into icg_side.talk_audit(page_id,business_key,action,actor,detail) values(r.page_id,p_revision,'content_hold',p_actor,jsonb_build_object('reason',p_note));
 return true;
end $$;

create or replace function icg_side.facebook_observe(p_page text,p_posts jsonb)
returns boolean language plpgsql security invoker set search_path='' as $$
declare item jsonb; observed timestamptz;
begin
 perform 1 from icg_side.facebook_page_policy where page_id=p_page for update;
 if not found then raise exception 'unknown Page'; end if;
 if jsonb_typeof(p_posts) is distinct from 'array' then raise exception 'invalid observation'; end if;
 for item in select value from jsonb_array_elements(p_posts) loop
   observed := (item->>'created_time')::timestamptz;
   if item->>'id' is null or observed is null or observed>now()+interval '5 minutes' then raise exception 'invalid post receipt'; end if;
   -- Unknown sending attempts are never resolved by heuristic matching here.
   insert into icg_side.facebook_deliveries(page_id,business_key,track,body_hash,state,post_id,published_at)
   values(p_page,'external:'||(item->>'id'),'external','observed','PUBLISHED',item->>'id',observed)
   on conflict(page_id,post_id) do nothing;
 end loop;
 update icg_side.facebook_page_policy set observed_at=now() where page_id=p_page;
 return true;
end $$;

create or replace function icg_side.facebook_begin(p_page text,p_key text,p_track text,p_body_hash text,p_expires timestamptz)
returns jsonb language plpgsql security invoker set search_path='' as $$
declare p icg_side.facebook_page_policy; d icg_side.facebook_deliveries; t icg_side.talk_items;
 n integer; last_post timestamptz; kst_day timestamptz; kst_week timestamptz;
begin
 select * into p from icg_side.facebook_page_policy where page_id=p_page for update;
 if not found then raise exception 'missing Page policy'; end if;
 if p_track not in ('talk','sidestory') or length(p_key)<1 or length(p_body_hash)<>64 then raise exception 'invalid identity'; end if;
 select * into d from icg_side.facebook_deliveries where page_id=p_page and business_key=p_key for update;
 if found then
   if d.body_hash<>p_body_hash or d.track<>p_track then raise exception 'publication payload changed'; end if;
   if d.state='PUBLISHED' then return jsonb_build_object('status',d.state,'post_id',d.post_id); end if;
   if d.state in ('SENDING','UNKNOWN') then return jsonb_build_object('status','UNKNOWN'); end if;
   if d.state<>'RETRY_WAIT' or d.attempt>=3 then return jsonb_build_object('status','REJECTED'); end if;
 end if;
 if not p.enabled or not p.exclusive_managed then return jsonb_build_object('status','CHANNEL_HOLD'); end if;
 if p.observed_at is null or p.observed_at<now()-interval '2 minutes' then return jsonb_build_object('status','OBSERVATION_REQUIRED'); end if;
 if p_expires is null or p_expires<=now() then return jsonb_build_object('status','EXPIRED'); end if;
 if exists(select 1 from icg_side.facebook_deliveries where page_id=p_page and state in ('SENDING','UNKNOWN')) then return jsonb_build_object('status','UNKNOWN'); end if;
 if p_track='talk' then
   select * into t from icg_side.talk_items where revision=p_key and page_id=p_page for update;
   if not found or t.status<>'APPROVED' or t.send_hash<>p_body_hash or t.approved_at is null or t.expires_at<=now() or t.due_at>now() or (t.due_at at time zone 'Asia/Seoul')::date < (now() at time zone 'Asia/Seoul')::date then
     return jsonb_build_object('status','APPROVAL_OR_TIME_REQUIRED'); end if;
 end if;
 select count(*), max(published_at) into n,last_post from icg_side.facebook_deliveries
   where page_id=p_page and state='PUBLISHED' and published_at>now()-interval '24 hours';
 if n>=p.page_day_limit or last_post>now()-make_interval(secs=>p.min_gap_seconds) then return jsonb_build_object('status','PAGE_LIMIT'); end if;
 kst_day := date_trunc('day',now() at time zone 'Asia/Seoul') at time zone 'Asia/Seoul';
 kst_week := date_trunc('week',now() at time zone 'Asia/Seoul') at time zone 'Asia/Seoul';
 if p_track='talk' and (
 (select count(*) from icg_side.facebook_deliveries where page_id=p_page and track='talk' and state='PUBLISHED' and published_at>=kst_day)>=p.talk_day_limit or
 (select count(*) from icg_side.facebook_deliveries where page_id=p_page and track='talk' and state='PUBLISHED' and published_at>=kst_week)>=p.talk_week_limit)
 then return jsonb_build_object('status','TALK_LIMIT'); end if;
 insert into icg_side.facebook_deliveries(page_id,business_key,track,body_hash,state)
 values(p_page,p_key,p_track,p_body_hash,'SENDING')
 on conflict(page_id,business_key) do update set state='SENDING',token=gen_random_uuid(),attempt=icg_side.facebook_deliveries.attempt+1,started_at=now()
 returning * into d;
 insert into icg_side.talk_audit(page_id,business_key,action,actor,detail)
 values(p_page,p_key,'send_started','worker',jsonb_build_object('token',d.token,'attempt',d.attempt));
 return jsonb_build_object('status','SENDING','token',d.token);
end $$;

create or replace function icg_side.facebook_finish(p_page text,p_key text,p_token uuid,p_state text,p_post_id text,p_reason text)
returns boolean language plpgsql security invoker set search_path='' as $$
declare d icg_side.facebook_deliveries;
begin
 perform 1 from icg_side.facebook_page_policy where page_id=p_page for update;
 select * into d from icg_side.facebook_deliveries where page_id=p_page and business_key=p_key for update;
 if not found or d.state<>'SENDING' or d.token is distinct from p_token then raise exception 'claim lost'; end if;
 if p_state not in ('PUBLISHED','UNKNOWN','REJECTED') or (p_state='PUBLISHED' and coalesce(p_post_id,'')='') then raise exception 'invalid outcome'; end if;
 if p_state='PUBLISHED' then delete from icg_side.facebook_deliveries where page_id=p_page and track='external' and post_id=p_post_id; end if;
 update icg_side.facebook_deliveries set state=p_state,post_id=p_post_id,reason=p_reason,
 published_at=case when p_state='PUBLISHED' then now() else null end where page_id=p_page and business_key=p_key;
 if p_state='PUBLISHED' and d.track='talk' then update icg_side.talk_items set status='PUBLISHED' where revision=p_key; end if;
 if p_state in ('UNKNOWN','REJECTED') then update icg_side.facebook_page_policy set enabled=false,hold_reason=p_state where page_id=p_page; end if;
 insert into icg_side.talk_audit(page_id,business_key,action,actor,detail)
 values(p_page,p_key,p_state,'worker',jsonb_build_object('post_id',p_post_id,'reason',p_reason));
 return true;
end $$;

create or replace function icg_side.facebook_set_hold(p_page text,p_actor text,p_reason text,p_enabled boolean)
returns boolean language plpgsql security invoker set search_path='' as $$
begin
 if length(trim(p_actor))<1 or length(trim(p_reason))<10 then raise exception 'actor and reason required'; end if;
 perform 1 from icg_side.facebook_page_policy where page_id=p_page for update;
 if not found then raise exception 'Page missing'; end if;
 if p_enabled and exists(select 1 from icg_side.facebook_deliveries where page_id=p_page and state in ('SENDING','UNKNOWN')) then raise exception 'unresolved publication'; end if;
 update icg_side.facebook_page_policy set enabled=p_enabled,hold_reason=p_reason where page_id=p_page;
 insert into icg_side.talk_audit(page_id,action,actor,detail) values(p_page,'channel_state',p_actor,jsonb_build_object('enabled',p_enabled,'reason',p_reason));
 return true;
end $$;

-- Only the operator invokes this after verifying an exact Page post or non-delivery.
create or replace function icg_side.facebook_resolve(p_page text,p_key text,p_post_id text,p_published_at timestamptz,p_actor text,p_note text)
returns boolean language plpgsql security invoker set search_path='' as $$
declare d icg_side.facebook_deliveries;
begin
 if length(trim(p_actor))<1 or length(trim(p_note))<20 then raise exception 'documented operator verification required'; end if;
 perform 1 from icg_side.facebook_page_policy where page_id=p_page for update;
 select * into d from icg_side.facebook_deliveries where page_id=p_page and business_key=p_key for update;
 if not found or d.state not in ('SENDING','UNKNOWN','REJECTED') then raise exception 'not unresolved'; end if;
 if p_post_id is not null then
   if length(trim(p_post_id))=0 or p_published_at is null or p_published_at<d.started_at-interval '5 minutes' or p_published_at>now()+interval '5 minutes' then raise exception 'verified time required'; end if;
   delete from icg_side.facebook_deliveries where page_id=p_page and track='external' and post_id=p_post_id;
   update icg_side.facebook_deliveries set state='PUBLISHED',post_id=p_post_id,published_at=p_published_at,reason=p_note
    where page_id=p_page and business_key=p_key;
   if d.track='talk' then update icg_side.talk_items set status='PUBLISHED' where revision=p_key; end if;
 else
   if d.attempt>=3 then raise exception 'attempts exhausted'; end if;
   update icg_side.facebook_deliveries set state='RETRY_WAIT',reason=p_note where page_id=p_page and business_key=p_key;
 end if;
 insert into icg_side.talk_audit(page_id,business_key,action,actor,detail)
 values(p_page,p_key,'resolve',p_actor,jsonb_build_object('post_id',p_post_id,'note',p_note));
 -- Does not reactivate the Page automatically.
 return true;
end $$;

create or replace function icg_side.talk_cost_reserve(p_page text,p_key text,p_amount numeric)
returns boolean language plpgsql security invoker set search_path='' as $$
declare p icg_side.facebook_page_policy; day_start timestamptz; month_start timestamptz;
begin
 select * into p from icg_side.facebook_page_policy where page_id=p_page for update;
 if not found or p_amount is null or p_amount<=0 or p_amount::text in ('NaN','Infinity','-Infinity') then raise exception 'invalid cost reservation'; end if;
 day_start := date_trunc('day',now() at time zone 'Asia/Seoul') at time zone 'Asia/Seoul';
 month_start := date_trunc('month',now() at time zone 'Asia/Seoul') at time zone 'Asia/Seoul';
 if p_amount+(select coalesce(sum(amount),0) from icg_side.talk_costs where page_id=p_page and created_at>=day_start)>p.daily_budget_usd
 or p_amount+(select coalesce(sum(amount),0) from icg_side.talk_costs where page_id=p_page and created_at>=month_start)>p.monthly_budget_usd then raise exception 'cost limit'; end if;
 insert into icg_side.talk_costs(page_id,request_key,amount) values(p_page,p_key,p_amount);
 return true;
end $$;

do $$
declare t text; f record;
begin
 foreach t in array array['facebook_page_policy','talk_items','facebook_deliveries','talk_audit','talk_costs'] loop
 execute format('alter table icg_side.%I enable row level security',t);
 execute format('revoke all on icg_side.%I from public,anon,authenticated',t);
 execute format('grant select,insert,update on icg_side.%I to service_role',t);
 end loop;
 -- Required for merging an externally observed receipt during explicit reconciliation.
 grant delete on icg_side.facebook_deliveries to service_role;
 grant usage on sequence icg_side.talk_audit_id_seq to service_role;
 for f in select p.oid::regprocedure as signature from pg_proc p join pg_namespace n on n.oid=p.pronamespace
  where n.nspname='icg_side' and (p.proname like 'facebook_%' or p.proname like 'talk_%') loop
 execute format('revoke all on function %s from public,anon,authenticated',f.signature);
 execute format('grant execute on function %s to service_role',f.signature);
 end loop;
end $$;
notify pgrst,'reload schema';
commit;
