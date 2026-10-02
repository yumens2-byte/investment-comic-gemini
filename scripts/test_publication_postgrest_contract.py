"""PR-03: publication path through a real PostgREST against an isolated local Postgres.

Runs the production claim / receipt / finalize / release code over HTTP so request
serialization, URL limits and RPC contracts are exercised exactly as in production.
Refuses every non-local database or PostgREST URL; never uses production credentials.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse

import psycopg
import psycopg.sql
from psycopg.types.json import Jsonb

LOCAL = {"localhost", "127.0.0.1"}
ROW_DATE = "2026-10-03"


def _jwt(secret: str, role: str) -> str:
    def b64(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

    header = b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    payload = b64(json.dumps({"role": role, "exp": int(time.time()) + 3600}).encode())
    signature = hmac.new(secret.encode(), f"{header}.{payload}".encode(), hashlib.sha256)
    return f"{header}.{payload}.{b64(signature.digest())}"


def bootstrap(db) -> None:
    db.execute("drop schema if exists icg cascade")  # isolated local database only
    db.execute("create schema icg")
    for role in ("anon", "authenticated", "service_role"):
        db.execute(f"do $$ begin create role {role} nologin; exception when duplicate_object"
                   f" then null; end $$")
    password = os.environ.get("AUTHENTICATOR_TEST_PASSWORD", "local-authenticator")
    db.execute("do $$ begin create role authenticator login noinherit;"
               " exception when duplicate_object then null; end $$")
    db.execute(psycopg.sql.SQL("alter role authenticator password {}").format(
        psycopg.sql.Literal(password)))
    db.execute("grant anon, authenticated, service_role to authenticator")
    ints = ("arc_day arc_tension edt_pressure hero_momentum crowd_momentum villain_streak "
            "hero_win_streak season_arc_days defeated_villains villain_signature "
            "emergence_deficit_days dimensional_rift_progress").split()
    bools = ("form2_available form3_activated volatility_fields_active "
             "zero_block_just_appeared").split()
    texts = "open_hook last_outcome active_villain last_episode_type".split()
    columns = [f"{k} integer" for k in ints] + [f"{k} boolean" for k in bools]
    columns += [f"{k} text" for k in texts]
    columns += ["last_episode_date date", "pair_tension jsonb", "updated_at timestamptz"]
    db.execute("create table icg.arc_state(id integer primary key," + ",".join(columns) + ")")
    db.execute(
        "create table icg.episode_assets(id integer primary key, episode_date date,"
        " episode_no integer, event_type text, status text, script_json jsonb,"
        " error_message text, total_runtime_sec numeric,"
        " updated_at timestamptz not null default now(), unique(episode_date, episode_no))")
    # Same trigger body as production icg.touch_updated_at (verified 2026-10-03).
    db.execute("create function icg.touch_updated_at() returns trigger language plpgsql as $$"
               " begin NEW.updated_at = now(); return NEW; end; $$")
    db.execute("create trigger trg_icg_episode_assets_updated_at before update on"
               " icg.episode_assets for each row execute function icg.touch_updated_at()")
    db.execute("create table icg.daily_analysis(analysis_date date primary key,"
               " story_state_json jsonb)")
    db.execute("create table icg.published_comics(publish_date date, comic_type text,"
               " episode_no integer, risk_level text, tweet_id text, cut_count integer,"
               " cost_usd numeric, status text, created_at timestamptz default now())")
    db.execute(Path("docs/sql/narrative-publication-state.sql").read_text())
    db.execute(Path("migrations/2026_10_03_published_comics_code_sha.sql").read_text())
    db.execute("grant usage on schema icg to service_role")
    db.execute("grant select, insert, update on all tables in schema icg to service_role")
    db.execute("notify pgrst, 'reload schema'")


def seed(db, script_padding: int) -> dict:
    db.execute("delete from icg.episode_assets")
    db.execute("delete from icg.published_comics")
    db.execute("delete from icg.daily_analysis")
    db.execute("delete from icg.arc_state")
    db.execute("insert into icg.arc_state(id, arc_day, arc_tension, hero_win_streak)"
               " values(1, 63, 0, 61)")
    arc = db.execute("select to_jsonb(a) from icg.arc_state a").fetchone()[0]
    candidate = {"version": "state-candidate-1", "episode_date": ROW_DATE, "base_arc": arc,
                 "arc_after": dict(arc, arc_day=64, hero_win_streak=0),
                 "story_after": {"arc_episode": 62}}
    script = {"_state_candidate": candidate, "_assembly_manifest": {"version": "test"},
              "_reviewed_image_inputs": {"panels": [{"prompt_text": "x" * script_padding}]},
              "panels": [{"idx": 1, "action": "방패 " * 400}]}
    db.execute("insert into icg.episode_assets(id, episode_date, episode_no, event_type,"
               " status, script_json) values(1, %s, 1, 'BATTLE', 'assembled', %s)",
               [ROW_DATE, Jsonb(script)])
    db.execute("insert into icg.daily_analysis values(%s, null)", [ROW_DATE])
    return candidate


def start_postgrest(binary: str, api_url: str, secret: str) -> subprocess.Popen:
    """Start PostgREST only after bootstrap: the authenticator role must already exist
    (v12 exits on a failed login) and the first schema cache load sees every table and RPC."""
    port = urlparse(api_url).port
    password = os.environ.get("AUTHENTICATOR_TEST_PASSWORD", "local-authenticator")
    conf = Path(os.environ.get("POSTGREST_TEST_CONF", "/tmp/pgrst.conf"))
    conf.write_text(
        f'db-uri = "postgres://authenticator:{password}@localhost:5432/postgres"\n'
        'db-schemas = "icg"\ndb-anon-role = "anon"\n'
        f'jwt-secret = "{secret}"\nserver-port = {port}\n')
    log = open(os.environ.get("POSTGREST_TEST_LOG", "/tmp/postgrest.log"), "w")
    return subprocess.Popen([binary, str(conf)], stdout=log, stderr=subprocess.STDOUT)


def wait_until_ready(api_url: str, secret: str, timeout: float = 60.0) -> None:
    """Ready only when both a table and a publication RPC are in the schema cache."""
    import httpx

    headers = {"Authorization": f"Bearer {_jwt(secret, 'service_role')}",
               "Accept-Profile": "icg", "Content-Profile": "icg"}
    # Read-only probe: no row has this date, so the RPC only answers ready=false.
    probe = {"p_date": "1900-01-01", "p_no": 1, "p_candidate": {}}
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            table = httpx.get(f"{api_url}/episode_assets?limit=1", headers=headers, timeout=5)
            rpc = httpx.post(f"{api_url}/rpc/publication_state_preflight", headers=headers,
                             json=probe, timeout=5)
            if table.status_code == 200 and rpc.status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(1)
    raise TimeoutError("PostgREST did not serve the icg schema in time")


def read_row(db) -> dict:
    return db.execute("select to_jsonb(e) from icg.episode_assets e where id=1").fetchone()[0]


def main() -> None:
    db_url = os.environ["DATABASE_TEST_URL"]
    api_url = os.environ["POSTGREST_TEST_URL"]
    secret = os.environ["POSTGREST_TEST_JWT_SECRET"]
    if urlparse(db_url).hostname not in LOCAL or urlparse(api_url).hostname not in LOCAL:
        raise ValueError("isolated localhost database and PostgREST required")

    from postgrest import SyncPostgrestClient

    from engine.common import supabase_client

    api = SyncPostgrestClient(api_url, schema="icg", headers={
        "Authorization": f"Bearer {_jwt(secret, 'service_role')}",
        "Accept": "application/json", "Content-Type": "application/json"})

    class Client:
        def schema(self, _name):
            return api

    supabase_client.get_client = lambda: Client()
    supabase_client.icg_table = lambda name: api.table(name)

    from engine.publish.claim_guard import (
        claim_publication,
        finish_publication,
        rehearse_publication_requests,
    )
    from engine.publish.history_writer import record_publish
    from engine.publish.state_commit import record_delivery, require_state_ready
    from engine.quality.contracts import QualityHold

    os.environ["GITHUB_SHA"] = "f" * 40
    binary = os.environ.get("POSTGREST_BIN")
    server = None
    try:
        with psycopg.connect(db_url, autocommit=True) as db:
            bootstrap(db)
            if binary:
                server = start_postgrest(binary, api_url, secret)
            wait_until_ready(api_url, secret)
            run_checks(db, claim_publication, finish_publication,
                       rehearse_publication_requests, record_publish, record_delivery,
                       require_state_ready, QualityHold)
    finally:
        if server is not None:
            server.terminate()
            server.wait(timeout=10)


def run_checks(db, claim_publication, finish_publication, rehearse_publication_requests,
               record_publish, record_delivery, require_state_ready, QualityHold) -> None:
    checks = []

    # 1) Full publication over HTTP with a ~68 KB script (incident size).
    candidate = seed(db, 66000)
    row = read_row(db)
    assert len(json.dumps(row["script_json"], ensure_ascii=False)) > 60000
    assert rehearse_publication_requests(row, ROW_DATE, 1) == []
    require_state_ready(ROW_DATE, 1, candidate)
    token = claim_publication(row, ROW_DATE, 1)
    record_delivery(ROW_DATE, 1, token, "x", ["2105757754312851782"])
    record_delivery(ROW_DATE, 1, token, "telegram:@chan", [123])
    record_publish(episode_date=ROW_DATE, episode_id=f"ICG-{ROW_DATE}-001",
                   event_type="BATTLE", tweet_ids=["2105757754312851782"],
                   telegram_sent=True, slide_count=8, gemini_cost_usd=0.2375,
                   claude_cost_usd=0.0, runtime_sec=12.0, state_candidate=candidate,
                   telegram_receipts={"@chan": [123]})
    finish_publication(ROW_DATE, 1, token)
    done = read_row(db)
    assert done["status"] == "published" and done["error_message"] is None
    arc = db.execute("select arc_day, hero_win_streak from icg.arc_state").fetchone()
    assert arc == (64, 0)
    history = db.execute("select count(*), max(code_sha) from icg.published_comics"
                         ).fetchone()
    assert history == (1, "f" * 40)
    checks.append("full_publication_large_script")

    # 2) Concurrent claims: exactly one wins.
    seed(db, 100)
    row = read_row(db)

    def attempt(_):
        try:
            return claim_publication(row, ROW_DATE, 1)
        except QualityHold:
            return None

    with ThreadPoolExecutor(max_workers=6) as pool:
        winners = [t for t in pool.map(attempt, range(6)) if t]
    assert len(winners) == 1
    checks.append("single_claim_under_concurrency")

    # 3) Row changed after inspection (version moved): claim refused, row untouched.
    seed(db, 100)
    stale = read_row(db)
    db.execute("update icg.episode_assets set script_json = script_json ||"
               " '{\"title\": \"changed\"}'::jsonb where id=1")
    try:
        claim_publication(stale, ROW_DATE, 1)
        raise AssertionError("stale claim acquired")
    except QualityHold:
        pass
    assert read_row(db)["error_message"] is None
    checks.append("stale_version_refused")

    # 4) Arc moved since generation: finalize refuses, state unchanged.
    candidate = seed(db, 100)
    token = claim_publication(read_row(db), ROW_DATE, 1)
    record_delivery(ROW_DATE, 1, token, "x", ["1"])
    db.execute("update icg.arc_state set arc_day = 99")
    try:
        record_publish(episode_date=ROW_DATE, episode_id=f"ICG-{ROW_DATE}-001",
                       event_type="BATTLE", tweet_ids=["1"], telegram_sent=False,
                       slide_count=8, gemini_cost_usd=0.1, claude_cost_usd=0.0,
                       runtime_sec=1.0, state_candidate=candidate, telegram_receipts={})
        raise AssertionError("finalize accepted a stale base arc")
    except AssertionError:
        raise
    except Exception:
        pass
    assert read_row(db)["status"] == "assembled"
    assert db.execute("select count(*) from icg.published_comics").fetchone()[0] == 0
    checks.append("stale_arc_finalize_refused")

    print(json.dumps({"status": "pass", "checks": checks}))


if __name__ == "__main__":
    main()
