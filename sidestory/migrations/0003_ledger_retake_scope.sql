-- SIDESTORY 0003 — allow one SG-8 retake scope per slot in the side image ledger (2026-10-05)
-- Adds output/sidestory/<date>/v2/panels (v8.9: a panel rejected by the SG-8 picture check is
-- regenerated once there; the original keeps its paid receipt). No other retake scope exists,
-- so at most one retake per panel per slot. Only icg_side.image_generation_inspect changes
-- (reserve calls inspect, so it inherits it). Budgets/caps unchanged. Main schema icg untouched.
-- Idempotent (create or replace). Supersedes the scope regex of 0002 (refs scope kept).

begin;

create or replace function icg_side.image_generation_inspect(p_scope text,p_panel integer,p_fingerprint text)
returns jsonb language plpgsql security invoker set search_path='' as $$
declare r record;
begin
 if p_scope is null or p_panel is null or p_fingerprint is null or length(p_scope)>500 or p_scope='' or p_panel<=0 or p_fingerprint !~ '^[0-9a-f]{64}$'
 or p_scope !~ '^output/sidestory/([0-9]{4}-[0-9]{2}-[0-9]{2}(/v2)?|refs/r[0-9]{1,3})/panels$'
 then return jsonb_build_object('hold','invalid identity'); end if;
 if exists(select 1 from icg_side.image_generation_calls where scope=p_scope
 and state in ('reserved','unknown','terminal'))
 then return jsonb_build_object('hold','scope requires reconciliation'); end if;
 if exists(select 1 from icg_side.image_generation_calls where scope=p_scope and panel=p_panel
 and fingerprint<>p_fingerprint)
 then return jsonb_build_object('hold','artifact identity changed'); end if;
 select * into r from icg_side.image_generation_calls where scope=p_scope and panel=p_panel
 and state='success' order by created_at desc limit 1;
 if found then return jsonb_build_object('output_hash',r.output_hash); end if;
 return '{}'::jsonb;
end $$;

revoke execute on function icg_side.image_generation_inspect(text,integer,text) from public,anon,authenticated;
grant execute on function icg_side.image_generation_inspect(text,integer,text) to service_role;

commit;
