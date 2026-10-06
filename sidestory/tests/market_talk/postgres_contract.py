"""Real multi-connection Postgres checks, restricted to a disposable loopback DB."""

from __future__ import annotations

import os
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import psycopg
from psycopg.conninfo import conninfo_to_dict


def main():
    url = os.environ.get("MARKET_TALK_TEST_DATABASE_URL", "")
    if not url or conninfo_to_dict(url).get("host") not in {"127.0.0.1", "localhost", "::1"}:
        raise SystemExit("Only an explicit disposable loopback test DB is permitted")
    migration = next(
        (Path(__file__).resolve().parents[2] / "supabase/migrations").glob("*_market_talk.sql")
    )
    with psycopg.connect(url, autocommit=True) as db:
        # Fail rather than delete/reuse an existing schema.
        db.execute("create schema icg_side")
        db.execute(
            "create role anon; create role authenticated; create role service_role bypassrls"
        )
        db.execute("grant usage on schema icg_side to service_role")
        db.execute(
            "create schema icg; create table icg.main_sentinel(id integer primary key, value text)"
        )
        db.execute("insert into icg.main_sentinel values(1,'unchanged')")
        db.execute(migration.read_text())
        db.execute(
            "insert into icg_side.facebook_page_policy(page_id,enabled,exclusive_managed,observed_at,daily_budget_usd,monthly_budget_usd) values('race',true,true,now(),1,2)"
        )
    barrier = threading.Barrier(2)

    def begin(key):
        with psycopg.connect(url) as db:
            db.execute("set role service_role")
            barrier.wait(timeout=15)
            return db.execute(
                "select icg_side.facebook_begin('race',%s,'sidestory',%s,now()+interval '1 hour')",
                (key, "a" * 64),
            ).fetchone()[0]

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(begin, ["first", "second"]))
    assert sorted(r["status"] for r in results) == ["SENDING", "UNKNOWN"], results
    print("PASS independent DB connections: only one Page sender")
    with psycopg.connect(url, autocommit=True) as db:
        assert (
            db.execute(
                "select count(*) from icg_side.facebook_deliveries where state='SENDING'"
            ).fetchone()[0]
            == 1
        )
        token, key = db.execute(
            "select token,business_key from icg_side.facebook_deliveries where page_id='race'"
        ).fetchone()
        db.execute("set role service_role")
        try:
            db.execute(
                "select icg_side.facebook_finish('race',%s,null,'PUBLISHED','race_1','')", (key,)
            )
        except psycopg.Error:
            pass
        else:
            raise AssertionError("NULL token accepted")
        print("PASS NULL claim cannot finish")
        db.execute(
            "select icg_side.facebook_finish('race',%s,%s,'UNKNOWN',null,'timeout')", (key, token)
        )
        assert (
            db.execute(
                "select icg_side.facebook_begin('race',%s,'sidestory',%s,now()+interval '1 hour')",
                (key, "a" * 64),
            ).fetchone()[0]["status"]
            == "UNKNOWN"
        )
        print("PASS ambiguous result blocks retry across connections")
    barrier = threading.Barrier(2)

    def reserve(key):
        try:
            with psycopg.connect(url) as db:
                db.execute("set role service_role")
                barrier.wait(timeout=15)
                db.execute("select icg_side.talk_cost_reserve('race',%s,0.7)", (key,))
            return "reserved"
        except psycopg.Error as exc:
            if "cost limit" not in str(exc):
                raise
            return "limited"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(reserve, ["cost1", "cost2"]))
    assert sorted(results) == ["limited", "reserved"], results
    print("PASS independent DB connections: cost cannot oversubscribe")
    with psycopg.connect(url) as db:
        assert (
            db.execute("select value from icg.main_sentinel where id=1").fetchone()[0]
            == "unchanged"
        )
    print("PASS main schema unchanged")
    print("REAL POSTGRES CONTRACT: 5 passed; no Meta/LLM/production DB calls")


if __name__ == "__main__":
    main()
