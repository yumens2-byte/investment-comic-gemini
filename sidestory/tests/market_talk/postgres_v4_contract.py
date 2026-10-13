"""Independent PostgreSQL connections; only an explicit disposable loopback DB.

Uses a deterministic SQL clock in this test schema, never production connections.
Run with MARKET_TALK_TEST_DATABASE_URL pointing to an empty local test database.
"""

import os
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import psycopg
from psycopg.conninfo import conninfo_to_dict


def main():
    url = os.environ.get("MARKET_TALK_TEST_DATABASE_URL", "")
    if not url or conninfo_to_dict(url).get("host") not in {"localhost", "127.0.0.1", "::1"}:
        raise SystemExit("Only an explicit disposable loopback test DB is permitted")
    directory = Path(__file__).resolve().parents[2] / "supabase/migrations"
    with psycopg.connect(url, autocommit=True) as db:
        db.execute("create schema icg_side")  # Existing schema is an error, never dropped.
        for role in ["anon", "authenticated", "service_role"]:
            if not db.execute("select 1 from pg_roles where rolname=%s", (role,)).fetchone():
                db.execute("create role " + role + (" bypassrls" if role == "service_role" else ""))
        db.execute("grant usage on schema icg_side to service_role")
        db.execute("create schema icg; grant usage on schema icg to service_role")
        db.execute(
            "create table icg.daily_snapshots(snapshot_date date,us10y float,vix float,oil_wti float,spy_change float,nasdaq_change float,dollar_index float,hy_spread float,fear_greed float,created_at timestamptz,data_quality jsonb)"
        )
        db.execute("grant select on icg.daily_snapshots to service_role")
        db.execute(
            "create table icg_side.test_clock(t timestamptz); insert into icg_side.test_clock values('2026-10-12T05:00:00Z')"
        )
        db.execute("grant select,update on icg_side.test_clock to service_role")
        db.execute(
            "create function icg_side.test_now() returns timestamptz language sql as $$select t from icg_side.test_clock$$"
        )
        for suffix in [
            "_market_talk.sql",
            "_market_talk_automatic.sql",
            "_market_talk_hardening.sql",
            "_market_talk_db_only_v4.sql",
        ]:
            sql = next(directory.glob("*" + suffix)).read_text()
            if suffix == "_market_talk_db_only_v4.sql":
                sql = sql.replace("clock_timestamp()", "icg_side.test_now()")
            db.execute(sql)
        db.execute("insert into icg_side.facebook_page_policy(page_id) values('race')")
    barrier = threading.Barrier(2)

    def schedule(due):
        with psycopg.connect(url) as db:
            db.execute("set role service_role")
            barrier.wait(timeout=15)
            return db.execute(
                "select icg_side.talk_schedule_ensure('race','2026-10-12',%s)", (due,)
            ).fetchone()[0]

    with ThreadPoolExecutor(max_workers=2) as pool:
        slots = list(pool.map(schedule, ["2026-10-12T04:00:00Z", "2026-10-12T04:01:00Z"]))
    assert slots[0]["due_at"] == slots[1]["due_at"], slots
    print("PASS concurrent schedule candidates converge to one saved minute")
    with psycopg.connect(url, autocommit=True) as db:
        db.execute(
            "update icg_side.talk_policy set enabled=true,effective_from='2026-10-12' where page_id='race'"
        )
        for key in ["a" * 64, "b" * 64]:
            db.execute(
                "insert into icg_side.talk_items(revision,page_id,semantic_key,body_hash,send_hash,body,creative,payload,status,approved_at,due_at,expires_at) values(%s,'race',%s,%s,%s,'body','creative','{}','APPROVED',icg_side.test_now(),%s,'2026-10-12T09:00:00Z')",
                (key, key, key, "c" * 64, slots[0]["due_at"]),
            )
        db.execute(
            "insert into icg_side.facebook_deliveries(page_id,business_key,track,body_hash,state) values('race','side','sidestory','side','UNKNOWN')"
        )
    barrier = threading.Barrier(2)

    def begin(key):
        with psycopg.connect(url) as db:
            db.execute("set role service_role")
            barrier.wait(timeout=15)
            return db.execute(
                "select icg_side.talk_begin_v4('race',%s,'talk',%s,'2026-10-12T09:00:00Z')",
                (key, "c" * 64),
            ).fetchone()[0]

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(begin, ["a" * 64, "b" * 64]))
    assert sorted(row["status"] for row in results) == ["SENDING", "UNKNOWN"], results
    print("PASS independent connections serialize two revisions to one sender")
    with psycopg.connect(url, autocommit=True) as db:
        assert (
            db.execute(
                "select count(*) from icg_side.facebook_deliveries where track='talk' and state='SENDING'"
            ).fetchone()[0]
            == 1
        )
        key, token = db.execute(
            "select business_key,token from icg_side.facebook_deliveries where track='talk'"
        ).fetchone()
        db.execute("set role service_role")
        db.execute(
            "select icg_side.talk_finish_v4('race',%s,%s,'UNKNOWN',null,'TIMEOUT')", (key, token)
        )
        assert (
            db.execute(
                "select enabled from icg_side.facebook_page_policy where page_id='race'"
            ).fetchone()[0]
            is False
        )
        assert (
            db.execute(
                "select state from icg_side.facebook_deliveries where business_key='side'"
            ).fetchone()[0]
            == "UNKNOWN"
        )
        assert (
            db.execute("select enabled from icg_side.talk_policy where page_id='race'").fetchone()[
                0
            ]
            is False
        )
    print("PASS failed talk send leaves shared policy and Sidestory delivery untouched")
    print("3 real multi-connection v4 checks passed")


if __name__ == "__main__":
    main()
