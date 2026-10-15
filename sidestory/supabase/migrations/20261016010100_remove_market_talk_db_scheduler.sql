-- Deployment migration only; preserve dispatcher audit and all other cron jobs.
begin;
do $$ declare j record; begin
 if to_regclass('cron.job') is not null then
  for j in execute 'select jobid from cron.job where jobname in (''icg_talk_dispatch'',''icg_talk_dispatch_cutoff'',''icg_talk_dispatch_reconcile'')' loop
   execute 'select cron.unschedule($1)' using j.jobid;
  end loop;
 end if;
end $$;
drop function if exists private.icg_talk_dispatch();
drop function if exists private.icg_talk_dispatch_reconcile();
-- Do not delete logs or revoke a possibly shared token here.
commit;
