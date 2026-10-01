"""Proposed SQL integration test; refuses every non-local database URL."""
import os
from pathlib import Path
from urllib.parse import urlparse

import psycopg
from psycopg.types.json import Jsonb


def main():
    url = os.environ["DATABASE_TEST_URL"]
    if urlparse(url).hostname not in {"localhost", "127.0.0.1"}:
        raise ValueError("isolated localhost database required")
    with psycopg.connect(url, autocommit=True) as db:
        db.execute("create schema icg")
        for role in ("anon", "authenticated", "service_role"):
            db.execute(f"create role {role}")
        ints = "arc_day arc_tension edt_pressure hero_momentum crowd_momentum villain_streak hero_win_streak season_arc_days defeated_villains villain_signature emergence_deficit_days dimensional_rift_progress".split()
        bools = "form2_available form3_activated volatility_fields_active zero_block_just_appeared".split()
        texts = "open_hook last_outcome active_villain last_episode_type".split()
        columns = [f"{k} integer" for k in ints] + [f"{k} boolean" for k in bools]
        columns += [f"{k} text" for k in texts] + ["last_episode_date date", "pair_tension jsonb", "updated_at timestamptz"]
        db.execute("create table icg.arc_state(id integer primary key," + ",".join(columns) + ")")
        db.execute("create table icg.episode_assets(id integer primary key,episode_date date,episode_no integer,event_type text,status text,script_json jsonb,error_message text,total_runtime_sec numeric,unique(episode_date,episode_no))")
        db.execute("create table icg.daily_analysis(analysis_date date primary key,story_state_json jsonb)")
        db.execute("create table icg.published_comics(publish_date date,comic_type text,episode_no integer,risk_level text,tweet_id text,cut_count integer,cost_usd numeric,status text)")
        for path in ("migrations/20261001132931_image_generation_guard.sql", "docs/sql/narrative-publication-state.sql", "docs/sql/image-generation-revision.sql"):
            db.execute(Path(path).read_text())
        db.execute("insert into icg.arc_state(id,arc_day,arc_tension) values(1,63,0)")
        arc = db.execute("select to_jsonb(a) from icg.arc_state a").fetchone()[0]
        candidate = {"version": "state-candidate-1", "episode_date": "2026-10-02", "base_arc": arc,
                     "arc_after": dict(arc, arc_day=64), "story_after": {"arc_episode": 5}}
        script = {"_state_candidate": candidate, "_assembly_manifest": {"version": "test"}, "_generation_revision": 2}
        db.execute("insert into icg.episode_assets values(1,'2026-10-02',1,'BATTLE','narrative_done',%s,null,null)", [Jsonb(script)])
        db.execute("insert into icg.daily_analysis values('2026-10-02',null)")
        scope, first, changed, image_hash = "output/episodes/2026-10-02/panels", "a"*64, "b"*64, "c"*64
        db.execute("insert into icg.image_generation_calls(scope,panel,fingerprint,state,cost,output_hash) values(%s,1,%s,'success',.04,%s)", [scope, first, image_hash])
        assert db.execute("select icg.image_generation_inspect_v2(%s,1,%s,2)", [scope, first]).fetchone()[0]["output_hash"] == image_hash
        token = db.execute("select icg.image_generation_reserve_v2(%s,1,%s,2)", [scope, changed]).fetchone()[0]["token"]
        db.execute("select icg.image_generation_finish(%s,1,%s,%s,'success',.04,%s)", [scope, changed, token, "d"*64])
        assert db.execute("select icg.image_generation_inspect_v2(%s,1,%s,2)", [scope, "e"*64]).fetchone()[0]["hold"] == "revision identity changed"
        assert db.execute("select count(*) from icg.image_generation_calls where scope=%s", [scope]).fetchone()[0] == 2
        db.execute("update icg.episode_assets set status='assembled',error_message='PUBLISH_HOLD:test'")
        assert db.execute("select icg.publication_state_preflight('2026-10-02',1,%s)", [Jsonb(candidate)]).fetchone()[0]["ready"] is True
        db.execute("update icg.arc_state set arc_day=99")
        assert db.execute("select icg.publication_state_preflight('2026-10-02',1,%s)", [Jsonb(candidate)]).fetchone()[0]["ready"] is False
        db.execute("update icg.arc_state set arc_day=63")
        db.execute("select icg.record_episode_delivery('2026-10-02',1,'PUBLISH_HOLD:test','x',%s)", [Jsonb(["tweet-1"])])
        db.execute("select icg.record_episode_delivery('2026-10-02',1,'PUBLISH_HOLD:test','telegram:chat',%s)", [Jsonb([123])])
        query = "select icg.finalize_episode_publication('2026-10-02',1,%s,%s,%s,8,.08,1)"
        try:
            db.execute(query, [Jsonb(candidate), Jsonb(["wrong"]), Jsonb({"chat": [123]})])
        except psycopg.Error:
            pass
        else:
            raise AssertionError("receipt mismatch must block")
        assert db.execute("select arc_day from icg.arc_state").fetchone()[0] == 63
        args = [Jsonb(candidate), Jsonb(["tweet-1"]), Jsonb({"chat": [123]})]
        assert db.execute(query, args).fetchone()[0]["committed"] is True
        assert db.execute(query, args).fetchone()[0]["committed"] is True
        assert db.execute("select arc_day from icg.arc_state").fetchone()[0] == 64
        assert db.execute("select count(*) from icg.published_comics").fetchone()[0] == 1
        assert db.execute("select story_state_json from icg.daily_analysis").fetchone()[0] == {"arc_episode": 5}
        print("PostgreSQL contracts passed: receipts, rollback, idempotence, revision budget")


if __name__ == "__main__":
    main()
