-- Optional coexistence with other Page writers. Does not assert exclusive management.
begin;
alter table icg_side.facebook_page_policy add column coexistence_allowed boolean not null default false;
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
 if not p.enabled or not (p.exclusive_managed or p.coexistence_allowed) then return jsonb_build_object('status','CHANNEL_HOLD'); end if;
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

commit;
