-- Generated with Supabase CLI. Side compatibility for the shared ordinary-image client.
-- Preserves input evidence without changing budgets, holds, scopes or retry behavior.
begin;
-- Apply before deploying the ordinary-attempt diagnostic client.
-- Does not change generation budgets, terminal holds, retry plans or existing calls.
create table icg_side.image_generation_attempt_diagnostics (
 token uuid not null references icg_side.image_generation_calls(token),
 kind text not null check(kind in ('inputs','refusal')),
 payload jsonb not null check(jsonb_typeof(payload)='object' and octet_length(payload::text)<=262144),
 created_at timestamptz not null default clock_timestamp(),
 primary key(token,kind)
);
alter table icg_side.image_generation_attempt_diagnostics enable row level security;
revoke all on icg_side.image_generation_attempt_diagnostics from public,anon,authenticated,service_role;
grant select,insert on icg_side.image_generation_attempt_diagnostics to service_role;

create function icg_side.image_generation_store_attempt_diagnostic(
 p_scope text,p_panel integer,p_fingerprint text,p_token uuid,p_kind text,p_payload jsonb
) returns jsonb language plpgsql security invoker set search_path='' as $$
declare c icg_side.image_generation_calls%rowtype; old_payload jsonb;
begin
 if p_kind is null or p_kind not in ('inputs','refusal') or p_payload is null
 or jsonb_typeof(p_payload)<>'object' or octet_length(p_payload::text)>262144
 then return jsonb_build_object('hold','invalid attempt diagnostic'); end if;
 select * into c from icg_side.image_generation_calls
 where token=p_token and scope=p_scope and panel=p_panel and fingerprint=p_fingerprint for update;
 if not found then return jsonb_build_object('hold','stale attempt diagnostic token'); end if;
 select payload into old_payload from icg_side.image_generation_attempt_diagnostics
 where token=p_token and kind=p_kind;
 if found then
  if old_payload is distinct from p_payload
  then return jsonb_build_object('hold','attempt diagnostic cannot change'); end if;
  return jsonb_build_object('stored',true);
 end if;
 if p_kind='inputs' and c.state<>'reserved'
 then return jsonb_build_object('hold','inputs must precede provider call'); end if;
 insert into icg_side.image_generation_attempt_diagnostics(token,kind,payload)
 values(p_token,p_kind,p_payload);
 return jsonb_build_object('stored',true);
end $$;
revoke all on function icg_side.image_generation_store_attempt_diagnostic(text,integer,text,uuid,text,jsonb)
 from public,anon,authenticated;
grant execute on function icg_side.image_generation_store_attempt_diagnostic(text,integer,text,uuid,text,jsonb)
 to service_role;
notify pgrst,'reload schema';

commit;
