"""icg_side DB + PostgREST end-to-end contract (local only).

Run: DATABASE_TEST_URL=postgresql://postgres@127.0.0.1:55432/postgres \
     POSTGREST_BIN=/tmp/postgrest python -m sidestory.tests.db_contract

Mirrors scripts/test_publication_postgrest_contract.py conventions: refuses any
non-local URL, builds a mock main ``icg`` schema, applies the side migration,
then drives the real CLI and the real engine image ledger over HTTP.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import psycopg
from psycopg.types.json import Jsonb

REPO = Path(__file__).resolve().parents[2]
SIDE = REPO / "sidestory"
LOCAL = {"localhost", "127.0.0.1"}
SECRET = "local-side-contract-secret-at-least-32-chars"
RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(ok), detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail and not ok else ""))


def jwt(role: str) -> str:
    def b64(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

    head = b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    body = b64(json.dumps({"role": role, "exp": int(time.time()) + 3600}).encode())
    sig = hmac.new(SECRET.encode(), f"{head}.{body}".encode(), hashlib.sha256).digest()
    return f"{head}.{body}.{b64(sig)}"


# ── mock main schema (production-shaped) ─────────────────────────────────────
def bootstrap_main(db) -> None:
    db.execute("drop schema if exists icg_side cascade")
    db.execute("drop schema if exists icg cascade")
    db.execute("create schema icg")
    for role in ("anon", "authenticated", "service_role"):
        db.execute(f"do $$ begin create role {role} nologin; exception when duplicate_object"
                   f" then null; end $$")
    db.execute("do $$ begin create role authenticator login noinherit password 'local';"
               " exception when duplicate_object then null; end $$")
    db.execute("grant anon, authenticated, service_role to authenticator")
    # Supabase's service_role has BYPASSRLS; main icg.image_generation_calls relies on it too.
    db.execute("alter role service_role bypassrls")
    ints = ("arc_day arc_tension edt_pressure hero_momentum crowd_momentum villain_streak "
            "hero_win_streak season_arc_days defeated_villains villain_signature "
            "emergence_deficit_days dimensional_rift_progress").split()
    bools = "form2_available form3_activated volatility_fields_active zero_block_just_appeared"
    cols = [f"{k} integer" for k in ints] + [f"{k} boolean" for k in bools.split()]
    cols += [f"{k} text" for k in "open_hook last_outcome active_villain last_episode_type".split()]
    cols += ["last_episode_date date", "pair_tension jsonb", "updated_at timestamptz"]
    db.execute("create table icg.arc_state(id integer primary key," + ",".join(cols) + ")")
    db.execute(
        "create table icg.episode_assets(id serial primary key, episode_date date,"
        " episode_no integer, event_type text, status text, scenario_type text,"
        " heroes_json jsonb, battle_json jsonb, script_json jsonb, error_message text,"
        " total_runtime_sec numeric, updated_at timestamptz not null default now(),"
        " unique(episode_date, episode_no))")
    db.execute(
        "create table icg.daily_snapshots(snapshot_date date primary key, us10y numeric,"
        " vix numeric, oil_wti numeric, spy_change numeric, nasdaq_change numeric,"
        " dollar_index numeric, hy_spread numeric, fear_greed numeric, news_items jsonb)")
    db.execute("create table icg.daily_analysis(analysis_date date primary key,"
               " story_state_json jsonb)")
    db.execute("create table icg.published_comics(publish_date date, comic_type text,"
               " episode_no integer, risk_level text, tweet_id text, cut_count integer,"
               " cost_usd numeric, status text, created_at timestamptz default now())")
    db.execute((REPO / "docs/sql/narrative-publication-state.sql").read_text())
    db.execute((REPO / "migrations/20261001132931_image_generation_guard.sql").read_text())
    db.execute("grant usage on schema icg to service_role")
    db.execute("grant select, insert, update on all tables in schema icg to service_role")
    seed_main(db)


def seed_main(db) -> None:
    db.execute("insert into icg.arc_state(id, arc_day, arc_tension, hero_momentum,"
               " active_villain, last_outcome, last_episode_date, pair_tension)"
               " values (1, 16, 87, 100, 'CHAR_VILLAIN_001', 'HERO_VICTORY', '2026-10-06',"
               " '{\"PAIR_A\": 10}')")
    script = {
        "title": "첨탑 아래의 방패", "logline": "방패가 버텼다",
        "panels": [{"idx": 7, "panel_type": "AFTERMATH", "narration": "첨탑은 서 있다"},
                   {"idx": 8, "panel_type": "DISCLAIMER", "narration": "면책"}],
        "_continuity": {"next_hook": "30년물이 문을 두드린다",
                        "unresolved_threads": ["첨탑의 균열"]},
        "_state_candidate": {"secret": "must-not-leak"},
        "caption_x_cover": "main only",
    }
    rows = [
        ("2026-10-05", 1, "BATTLE", "published", "ONE_VS_ONE", "DRAW"),
        ("2026-10-06", 1, "BATTLE", "published", "ONE_VS_ONE", "HERO_VICTORY"),
        ("2026-10-07", 1, "INTEL", "assembled", "NO_BATTLE", "OBSERVATION"),
        ("2026-10-08", 1, "INTEL", "published", "NO_BATTLE", "OBSERVATION"),
    ]
    for day, no, event, status, scenario, outcome in rows:
        db.execute(
            "insert into icg.episode_assets(episode_date, episode_no, event_type, status,"
            " scenario_type, heroes_json, battle_json, script_json) values"
            " (%s,%s,%s,%s,%s,%s,%s,%s)",
            (day, no, event, status, scenario, Jsonb(["CHAR_HERO_002"]),
             Jsonb({"outcome": outcome, "villain_id": "CHAR_VILLAIN_001"}), Jsonb(script)))
    for day, ten in (("2026-10-05", 5.29), ("2026-10-06", 5.24), ("2026-10-08", 5.20)):
        db.execute("insert into icg.daily_snapshots(snapshot_date, us10y, vix, oil_wti,"
                   " spy_change, nasdaq_change, dollar_index, hy_spread, fear_greed)"
                   " values (%s,%s,15.3,91.26,0.73,-0.42,101.9,3.24,55)", (day, ten))
    db.execute("insert into icg.daily_analysis values ('2026-10-06', '{\"x\":1}')")
    db.execute("insert into icg.published_comics(publish_date, comic_type, episode_no, status)"
               " values ('2026-10-06','BATTLE',1,'published')")


def main_ddl(url: str) -> str:
    out = subprocess.run(["pg_dump", "--schema-only", "--schema=icg", "--no-owner", url],
                         check=True, capture_output=True, text=True).stdout
    # Recent pg_dump releases emit a random \\restrict token per run; it is not schema content.
    return "\n".join(line for line in out.splitlines()
                     if not line.startswith(("--", "\\restrict", "\\unrestrict")))


def main_data_hash(db) -> str:
    parts = []
    for table in ("arc_state", "episode_assets", "daily_snapshots", "daily_analysis",
                  "published_comics", "image_generation_calls"):
        rows = db.execute(f"select coalesce(jsonb_agg(to_jsonb(t) order by to_jsonb(t)::text),"
                          f" '[]') from icg.{table} t").fetchone()[0]
        parts.append(json.dumps(rows, sort_keys=True, default=str))
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


# ── DB-level checks ──────────────────────────────────────────────────────────
def run_db_checks(url: str) -> None:
    with psycopg.connect(url, autocommit=True) as db:
        bootstrap_main(db)
        rows = db.execute((SIDE / "migrations/0000_precheck.sql").read_text()).fetchall()
        check("D1 precheck: every contract column present", all(r[2] for r in rows),
              str([r[:2] for r in rows if not r[2]]))

        ddl_before, data_before = main_ddl(url), main_data_hash(db)
        db.execute((SIDE / "migrations/0001_icg_side_schema.sql").read_text())
        ddl_after = main_ddl(url)
        if ddl_after != ddl_before:
            import difflib
            print("\n".join(difflib.unified_diff(ddl_before.splitlines(), ddl_after.splitlines(),
                                                  lineterm="", n=1)))
        check("D2 migration leaves main icg DDL byte-identical", ddl_after == ddl_before)
        check("D3 migration leaves main icg data identical", main_data_hash(db) == data_before)

        objects = ("select count(*) from pg_class c join pg_namespace n on n.oid=c.relnamespace"
                   " where n.nspname='icg_side'")
        n_before = db.execute(objects).fetchone()[0]
        try:
            db.execute((SIDE / "migrations/0001_icg_side_schema.sql").read_text())
            check("D4 re-apply refused", False, "second apply succeeded")
        except psycopg.Error:
            db.execute("rollback")  # explicit BEGIN in the file leaves the block aborted
            n_after = db.execute(objects).fetchone()[0]
            check("D4 re-apply refused atomically (no partial objects)", n_before == n_after,
                  f"{n_before}->{n_after}")

        eps = db.execute("select episode_date, script_json from icg_side.main_feed_episode_v1"
                         " order by episode_date").fetchall()
        check("D5 episode view = published only", [r[0] for r in eps]
              == ["2026-10-05", "2026-10-06", "2026-10-08"], str([r[0] for r in eps]))
        keys = set().union(*(set(r[1].keys()) for r in eps))
        check("D6 episode view projects only contract keys", keys <= {
            "title", "logline", "panels", "next_hook", "unresolved_threads", "_continuity"},
            str(keys))
        check("D7 internal main keys not exposed (_state_candidate, captions)",
              not ({"_state_candidate", "caption_x_cover"} & keys))
        m = db.execute("select snapshot_date, us10y from icg_side.main_feed_market_v1"
                       " where snapshot_date <= '2026-10-07' order by snapshot_date desc"
                       " limit 1").fetchone()
        check("D8 market view latest-on-or-before", m[0] == "2026-10-06" and float(m[1]) == 5.24,
              str(m))
        a = db.execute("select arc_tension, last_episode_date from icg_side.main_feed_arc_v1"
                       ).fetchall()
        check("D9 arc view single row", a == [(87, "2026-10-06")], str(a))

        fp = lambda: db.execute(  # noqa: E731
            "select icg_side.main_state_fingerprint('2026-10-06')").fetchone()[0]
        f1, f2 = fp(), fp()
        check("D10 fingerprint deterministic sha256", f1 == f2 and len(f1) == 64)
        db.execute("insert into icg_side.side_episodes(side_episode_id, episode_date,"
                   " anchor_main_episode, outcome_class, echo_pack_json) values"
                   " ('SIDE-2026-10-06-01','2026-10-06','ICG-2026-10-06-001','VICTORY','{}')")
        check("D11 side writes do not move main fingerprint", fp() == f1)
        db.execute("update icg.arc_state set arc_tension = 88 where id = 1")
        f3 = fp()
        check("D12 main change moves fingerprint", f3 != f1)
        db.execute("update icg.arc_state set arc_tension = 87 where id = 1")
        db.execute("update icg.episode_assets set error_message='x'"
                   " where episode_date='2026-10-06'")
        check("D13 fingerprint covers episode_assets of the date", fp() != f1)
        db.execute("update icg.episode_assets set error_message=null"
                   " where episode_date='2026-10-06'")
        # updated_at moved — fingerprint differs from f1 by design (any write is detected)

        bad = {
            "D14 bad side id": "('SIDE-2026-10-06-1','2026-10-06','ICG-2026-10-05-001',"
                               "'DRAW','{}')",
            "D15 bad anchor id": "('SIDE-2026-10-08-01','2026-10-08','ICG-2026-10-08-1',"
                                 "'NO_BATTLE','{}')",
            "D16 duplicate anchor": "('SIDE-2026-10-08-01','2026-10-08','ICG-2026-10-06-001',"
                                    "'VICTORY','{}')",
            "D17 bad outcome class": "('SIDE-2026-10-08-01','2026-10-08','ICG-2026-10-08-001',"
                                     "'WIN','{}')",
        }
        for name, values in bad.items():
            try:
                db.execute("insert into icg_side.side_episodes(side_episode_id, episode_date,"
                           " anchor_main_episode, outcome_class, echo_pack_json) values "
                           + values)
                check(name + " rejected", False, "accepted")
            except psycopg.Error:
                check(name + " rejected", True)

        ins = ("insert into icg_side.side_publications(side_episode_id, channel, dry_run)"
               " values ('SIDE-2026-10-06-01','facebook',%s)")
        db.execute(ins, (True,))
        db.execute(ins, (True,))
        db.execute(ins, (False,))
        try:
            db.execute(ins, (False,))
            check("D18 second live publication rejected", False)
        except psycopg.Error:
            check("D18 second live publication rejected (dry runs repeatable)", True)
        try:
            db.execute("insert into icg_side.side_publications(side_episode_id, channel,"
                       " dry_run) values ('SIDE-2026-10-06-01','x',false)")
            check("D19 non-facebook channel rejected", False)
        except psycopg.Error:
            check("D19 non-facebook channel rejected", True)

        for role, expect in (("anon", False), ("authenticated", False), ("service_role", True)):
            ok_view = _can(db, role, "select 1 from icg_side.main_feed_episode_v1 limit 1")
            ok_fn = _can(db, role, "select icg_side.main_state_fingerprint('2026-10-06')")
            ok_tbl = _can(db, role, "select 1 from icg_side.side_episodes limit 1")
            check(f"D20 privileges {role}", (ok_view, ok_fn, ok_tbl) == (expect,) * 3,
                  f"view={ok_view} fn={ok_fn} table={ok_tbl}")
        no_main_write = not _can(db, "service_role",
                                 "delete from icg_side.main_feed_arc_v1")
        check("D21 contract views not writable", no_main_write)


def _can(db, role: str, sql: str) -> bool:
    try:
        with db.transaction():
            db.execute(f"set local role {role}")
            db.execute(sql)
            raise _Rollback
    except _Rollback:
        return True
    except psycopg.Error:
        return False


class _Rollback(Exception):
    pass


def run_ledger_db_checks(url: str) -> None:
    with psycopg.connect(url, autocommit=True) as db:
        main_before = db.execute("select count(*) from icg.image_generation_calls").fetchone()[0]
        fp = "f" * 64
        r = db.execute("select icg_side.image_generation_reserve("
                       "'output/episodes/2026-10-06/panels',1,%s)", (fp,)).fetchone()[0]
        check("L1 main scope refused by side ledger", r.get("hold") == "invalid identity", str(r))
        scope = "output/sidestory/2026-10-20/panels"
        tokens = []
        for _ in range(3):
            res = db.execute("select icg_side.image_generation_reserve(%s,1,%s)",
                             (scope, fp)).fetchone()[0]
            if "token" in res:
                tokens.append(res["token"])
                db.execute("select icg_side.image_generation_finish(%s,1,%s,%s,'failed',0.1,null)",
                           (scope, fp, res["token"]))
        res4 = db.execute("select icg_side.image_generation_reserve(%s,1,%s)",
                          (scope, fp)).fetchone()[0]
        check("L2 per-panel attempt cap = 3", len(tokens) == 3 and "hold" in res4, str(res4))
        db.execute("delete from icg_side.image_generation_calls")
        holds = None
        for i in range(25):
            res = db.execute("select icg_side.image_generation_reserve(%s,%s,%s)",
                             (f"output/sidestory/2026-11-{(i % 20) + 1:02d}/panels", 1 + i // 20,
                              fp)).fetchone()[0]
            if "token" in res:
                db.execute("select icg_side.image_generation_finish(%s,%s,%s,%s,'success',0.05,%s)",
                           (f"output/sidestory/2026-11-{(i % 20) + 1:02d}/panels", 1 + i // 20,
                            fp, res["token"], "a" * 64))
            elif holds is None:
                holds = (i, res)
        check("L3 side daily cap (20 calls) enforced", holds is not None and holds[0] == 20,
              str(holds))
        main_after = db.execute("select count(*) from icg.image_generation_calls").fetchone()[0]
        check("L4 side ledger never touches main ledger", main_before == main_after == 0)
        db.execute("delete from icg_side.image_generation_calls")


# ── PostgREST end-to-end ─────────────────────────────────────────────────────
def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start_postgrest(binary: str, db_url: str, port: int) -> subprocess.Popen:
    conf = Path(tempfile.mkdtemp()) / "pgrst.conf"
    parsed = urlparse(db_url)
    uri = f"postgresql://authenticator:local@{parsed.hostname}:{parsed.port}{parsed.path}"
    conf.write_text(f'db-uri = "{uri}"\ndb-schemas = "icg,icg_side"\ndb-anon-role = "anon"\n'
                    f'jwt-secret = "{SECRET}"\nserver-port = {port}\n')
    log = open("/tmp/sidestory_postgrest.log", "w")
    return subprocess.Popen([binary, str(conf)], stdout=log, stderr=subprocess.STDOUT)


def start_proxy(upstream_port: int) -> tuple[ThreadingHTTPServer, int]:
    """Emulates the Supabase gateway prefix /rest/v1 in front of PostgREST."""

    class Proxy(BaseHTTPRequestHandler):
        def _forward(self):
            path = self.path.removeprefix("/rest/v1")
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else None
            req = urllib.request.Request(f"http://127.0.0.1:{upstream_port}{path}", data=body,
                                         method=self.command)
            for key, value in self.headers.items():
                if key.lower() not in {"host", "content-length", "accept-encoding"}:
                    req.add_header(key, value)
            try:
                with urllib.request.urlopen(req) as resp:
                    status, headers, payload = resp.status, resp.headers, resp.read()
            except urllib.error.HTTPError as err:
                status, headers, payload = err.code, err.headers, err.read()
            self.send_response(status)
            for key, value in headers.items():
                if key.lower() not in {"transfer-encoding", "connection", "content-length"}:
                    self.send_header(key, value)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        do_GET = do_POST = do_PATCH = do_DELETE = do_HEAD = _forward

        def log_message(self, *args):
            pass

    port = free_port()
    server = ThreadingHTTPServer(("127.0.0.1", port), Proxy)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, port


def cli(env: dict, *args: str) -> tuple[int, dict]:
    proc = subprocess.run([sys.executable, "-m", "sidestory", *args], cwd=REPO, env=env,
                          capture_output=True, text=True, timeout=120)
    try:
        return proc.returncode, json.loads(proc.stdout)
    except json.JSONDecodeError:
        return proc.returncode, {"stdout": proc.stdout, "stderr": proc.stderr[-800:]}


def run_e2e(url: str, binary: str) -> None:
    with psycopg.connect(url, autocommit=True) as db:
        db.execute("delete from icg_side.side_publications")
        db.execute("delete from icg_side.side_episodes")
        main_before = main_data_hash(db)
    port = free_port()
    server = start_postgrest(binary, url, port)
    proxy, proxy_port = start_proxy(port)
    try:
        for _ in range(60):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=1)
                break
            except urllib.error.HTTPError:
                break
            except OSError:
                time.sleep(0.25)
        env = {**os.environ, "PYTHONPATH": str(REPO), "SUPABASE_SCHEMA": "icg_side",
               "SUPABASE_URL": f"http://127.0.0.1:{proxy_port}", "SUPABASE_KEY": jwt("service_role"),
               "DRY_RUN": "true"}

        code, out = cli(env, "--stage", "gate", "--date", "2026-10-06")
        check("E1 CLI gate on Tue anchors same-day main",
              code == 0 and out.get("gates", [{}])[0].get("reason") == "ICG-2026-10-06-001"
              and not out.get("persisted"), str(out)[:400])

        code, out = cli(env, "--stage", "echo", "--date", "2026-10-06", "--no-persist")
        echo = out.get("echo") or {}
        check("E2 CLI echo read-only builds pack from views",
              code == 0 and echo.get("title") == "첨탑 아래의 방패"
              and echo.get("outcome_class") == "VICTORY" and echo.get("market", {}).get("us10y")
              == 5.24 and not out.get("persisted"), str(out)[:400])
        with psycopg.connect(url, autocommit=True) as db:
            n = db.execute("select count(*) from icg_side.side_episodes").fetchone()[0]
        check("E3 --no-persist wrote nothing", n == 0, f"rows={n}")

        code, out = cli(env, "--stage", "echo", "--date", "2026-10-06")
        gates = {g["gate"]: g["passed"] for g in out.get("gates", [])}
        check("E4 CLI echo persists draft, SG-0/1/7 pass",
              code == 0 and out.get("persisted") and gates == {"SG-0": True, "SG-1": True,
                                                                 "SG-7": True}, str(out)[:400])
        code, out = cli(env, "--stage", "echo", "--date", "2026-10-06")
        check("E5 same anchor not echoed twice (SKIP)", code == 0 and out.get("skipped"),
              str(out)[:300])
        code, out = cli(env, "--stage", "echo", "--date", "2026-10-08")
        check("E6 Thu echoes NO_BATTLE main episode",
              code == 0 and (out.get("echo") or {}).get("outcome_class") == "NO_BATTLE",
              str(out)[:300])
        code, out = cli(env, "--stage", "gate", "--date", "2026-10-07")
        check("E7 Wednesday is SKIP", code == 0 and out.get("skipped"), str(out)[:300])
        bad_env = {**env, "SUPABASE_SCHEMA": "icg"}
        code, out = cli(bad_env, "--stage", "gate", "--date", "2026-10-06")
        check("E8 CLI refuses main schema", code != 0, str(out)[:200])

        # Real engine image ledger through icg_side (P1 path), no provider call.
        os.environ.update({k: env[k] for k in ("SUPABASE_URL", "SUPABASE_KEY", "SUPABASE_SCHEMA")})
        os.environ["ICG_GENERATION_REVISION"] = "1"
        sys.path.insert(0, str(REPO))
        from engine.image.generation_guard import GenerationHold, ProductionGenerationGuard

        out_dir = Path(tempfile.mkdtemp()) / "output/sidestory/2026-10-06/panels"
        out_dir.mkdir(parents=True)
        guard = ProductionGenerationGuard(scope=out_dir.as_posix(), panel=1, prompt="p", refs=[])
        reused = guard.reuse(out_dir / "P1.png")
        token = guard.reserve()
        png = b"\x89PNG-side-test"
        (out_dir / "P1.png").write_bytes(png)
        guard.finish(token, state="success", actual_cost=0.04,
                     output_hash=hashlib.sha256(png).hexdigest())
        check("E9 engine guard reserve/finish via icg_side",
              reused is False and guard.reuse(out_dir / "P1.png") is True)
        main_guard = ProductionGenerationGuard(
            scope="output/episodes/2026-10-06/panels", panel=1, prompt="p", refs=[])
        try:
            main_guard.reserve()
            check("E10 main scope refused when schema=icg_side", False)
        except GenerationHold as exc:
            check("E10 main scope refused when schema=icg_side", "invalid identity" in str(exc))

        with psycopg.connect(url, autocommit=True) as db:
            check("E11 main icg data unchanged after full E2E", main_data_hash(db) == main_before)
    finally:
        proxy.shutdown()
        server.terminate()
        server.wait(timeout=10)


def main() -> int:
    url = os.environ.get("DATABASE_TEST_URL", "")
    if urlparse(url).hostname not in LOCAL:
        print("refusing non-local DATABASE_TEST_URL")
        return 2
    binary = os.environ.get("POSTGREST_BIN", "/tmp/postgrest")
    run_db_checks(url)
    run_ledger_db_checks(url)
    if Path(binary).exists():
        run_e2e(url, binary)
    else:
        check("E* PostgREST binary present", False, binary)
    failed = [r for r in RESULTS if not r[1]]
    print(f"\nSUMMARY: {len(RESULTS) - len(failed)}/{len(RESULTS)} PASS")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
