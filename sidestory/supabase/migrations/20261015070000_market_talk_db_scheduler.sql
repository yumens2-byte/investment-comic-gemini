-- On-time clock for the Market Talk workflow.
-- GitHub `schedule` events for this repository have fired 5-9 hours late (e.g. the
-- */10 04-8 UTC cron arrived at 14:16 UTC), so every slot ended MISSED_WINDOW.
-- pg_cron dispatches the workflow with scheduler=true; the workflow then behaves
-- exactly like a schedule event (same vars gates, same DB slot arbitration).
-- Requires a Vault secret `github_icg_dispatch_pat`: a fine-grained PAT limited to
-- yumens2-byte/investment-comic-gemini with "Actions: Read and write" only.
-- Without the secret each tick is logged as no_secret and nothing is dispatched.
begin;

create table if not exists private.icg_talk_dispatch_log (
 id bigserial primary key,
 requested_at timestamptz not null default clock_timestamp(),
 status text not null check (status in ('requested','ok','failed','lost','error','no_secret')),
 request_id bigint,
 http_status integer,
 response_excerpt text,
 error text,
 reconciled_at timestamptz
);
revoke all on private.icg_talk_dispatch_log from public, anon, authenticated;

create or replace function private.icg_talk_dispatch_reconcile()
returns integer language plpgsql security definer set search_path='' as $$
declare v_open integer;
begin
 update private.icg_talk_dispatch_log l
    set http_status = r.status_code,
        response_excerpt = left(coalesce(r.content, r.error_msg, ''), 300),
        status = case when r.status_code between 200 and 299 and not coalesce(r.timed_out, false)
                      then 'ok' else 'failed' end,
        error = case when coalesce(r.timed_out, false) then 'timed_out' else left(r.error_msg, 300) end,
        reconciled_at = clock_timestamp()
   from net._http_response r
  where r.id = l.request_id and l.status = 'requested' and l.reconciled_at is null;
 -- pg_net keeps responses for 6 hours; anything older without one is lost.
 update private.icg_talk_dispatch_log
    set status = 'lost', reconciled_at = clock_timestamp()
  where status = 'requested' and reconciled_at is null
    and requested_at < clock_timestamp() - interval '6 hours';
 select count(*) into v_open from private.icg_talk_dispatch_log where status = 'requested';
 return v_open;
end;
$$;

create or replace function private.icg_talk_dispatch()
returns bigint language plpgsql security definer set search_path='' as $$
declare v_pat text; v_req bigint;
begin
 perform private.icg_talk_dispatch_reconcile();
 select ds.decrypted_secret into v_pat
   from vault.decrypted_secrets ds where ds.name = 'github_icg_dispatch_pat' limit 1;
 if v_pat is null or length(trim(v_pat)) = 0 then
  insert into private.icg_talk_dispatch_log(status, error)
  values ('no_secret', 'vault secret github_icg_dispatch_pat missing');
  return null;
 end if;
 v_req := net.http_post(
  url := 'https://api.github.com/repos/yumens2-byte/investment-comic-gemini/actions/workflows/sidestory_market_talk.yml/dispatches',
  body := jsonb_build_object('ref', 'main', 'inputs', jsonb_build_object('scheduler', 'true')),
  headers := jsonb_build_object(
   'Authorization', 'Bearer ' || trim(v_pat),
   'Accept', 'application/vnd.github+json',
   'X-GitHub-Api-Version', '2022-11-28',
   'User-Agent', 'icg-market-talk-scheduler',
   'Content-Type', 'application/json'),
  timeout_milliseconds := 10000);
 insert into private.icg_talk_dispatch_log(status, request_id) values ('requested', v_req);
 return v_req;
exception when others then
 insert into private.icg_talk_dispatch_log(status, error) values ('error', left(sqlerrm, 300));
 return null;
end;
$$;

revoke all on function private.icg_talk_dispatch() from public, anon, authenticated;
revoke all on function private.icg_talk_dispatch_reconcile() from public, anon, authenticated;

-- pg_cron runs in UTC. Same cadence as the workflow's GitHub cron (KST 13:00-17:50
-- every 10 minutes, plus the 18:00 cutoff check), but delivered on time.
select cron.schedule('icg_talk_dispatch', '*/10 4-8 * * 1-5', 'select private.icg_talk_dispatch()');
select cron.schedule('icg_talk_dispatch_cutoff', '0 9 * * 1-5', 'select private.icg_talk_dispatch()');
select cron.schedule('icg_talk_dispatch_reconcile', '15 9 * * 1-5', 'select private.icg_talk_dispatch_reconcile()');

commit;
