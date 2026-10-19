"""Two-session candidate reservation and selection races on localhost PostgreSQL."""

import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from urllib.parse import urlparse

import psycopg
from psycopg.types.json import Jsonb


def main():
    url = os.environ["DATABASE_TEST_URL"]
    if urlparse(url).hostname not in {"localhost", "127.0.0.1"}:
        raise ValueError("isolated localhost database required")
    with psycopg.connect(url, autocommit=True) as db:
        db.execute("drop schema if exists icg cascade; create schema icg")
        for role in ("anon", "authenticated", "service_role"):
            if not db.execute("select 1 from pg_roles where rolname=%s", [role]).fetchone():
                db.execute(f"create role {role}")
        db.execute("alter role service_role bypassrls; grant usage on schema icg to service_role")
        db.execute(
            "create table icg.episode_assets(episode_date date,episode_no int,status text,script_json jsonb,artifact_run_id text,unique(episode_date,episode_no))"
        )
        db.execute("grant select,update on icg.episode_assets to service_role")
        for path in (
            "migrations/20261001132931_image_generation_guard.sql",
            "docs/sql/image-generation-revision.sql",
            "docs/sql/image-generation-recovery.sql",
            "docs/sql/image-generation-retry.sql",
            "docs/sql/image-generation-attempt-diagnostics.sql",
            "docs/sql/image-generation-outcome-v3.sql",
            "docs/sql/image-generation-register-recovery-v3.sql",
            "docs/sql/image-quality-candidates.sql",
        ):
            db.execute(Path(path).read_text())
        scope = "output/episodes/2026-10-20/panels"
        cid = "11111111-1111-4111-8111-111111111111"
        fp, old, new = "a" * 64, "b" * 64, "c" * 64
        source = {
            "date": "2026-10-20",
            "panels": [
                {
                    "idx": 1,
                    "panel_type": "CLIMAX",
                    "action": "observe",
                    "setting": "vault",
                    "characters": [{"char_id": "hero"}],
                }
            ],
        }
        base = [
            {
                "panel_idx": 1,
                "output_hash": old,
                "artifact_run_id": "123",
                "artifact_name": "episode-123",
                "artifact_path": "2026-10-20/panels/P1.png",
            }
        ]
        candidate = dict(
            source,
            _generation_revision=3,
            _reviewed_image_inputs={
                "version": "reviewed-image-inputs-2",
                "aspect_ratio": "4:5",
                "panels": [{"idx": 1, "fingerprint": fp}],
            },
        )
        bundle = {
            "version": "image-quality-candidate-1",
            "purpose": "QUALITY_RETAKE",
            "id": cid,
            "date": "2026-10-20",
            "revision": 3,
            "source_script": source,
            "candidate_script": candidate,
            "base_manifest": base,
            "base_artifact_run_id": "123",
            "base_selection_version": 0,
            "max_calls": 1,
            "max_cost_usd": 0.1,
            "panels": [{"panel_idx": 1, "fingerprint": fp}],
        }
        db.execute(
            "insert into icg.episode_assets values(%s,1,%s,%s,%s)",
            ["2026-10-20", "image_generated", Jsonb(source), "123"],
        )
        token = db.execute(
            "insert into icg.image_generation_calls(scope,panel,fingerprint,state,cost,output_hash,revision) values(%s,1,%s,'success',.04,%s,2) returning token",
            [scope, "f" * 64, old],
        ).fetchone()[0]
        db.execute(
            "insert into icg.image_generation_attempt_diagnostics(token,kind,payload) values(%s,'inputs',%s)",
            [token, Jsonb({"run_id": "123"})],
        )
        db.execute("set role service_role")
        r = db.execute("select icg.image_quality_register(%s)", [Jsonb(bundle)]).fetchone()[0]
        assert r.get("registered"), r
        digest = r["digest"]
        assert db.execute(
            "select icg.image_quality_approve(%s,%s,%s,%s)",
            [cid, digest, "operator", "Reviewed camera, motion, canon and cost cap"],
        ).fetchone()[0]["approved"]

        def race(sql, params):
            barrier = Barrier(2)

            def run():
                with psycopg.connect(url, autocommit=True) as conn:
                    conn.execute("set role service_role")
                    conn.execute("set statement_timeout='10s'")
                    barrier.wait(timeout=10)
                    return conn.execute(sql, params).fetchone()[0]

            with ThreadPoolExecutor(max_workers=2) as pool:
                return list(pool.map(lambda _: run(), range(2)))

        reservations = race("select icg.image_quality_reserve(%s,1,%s,%s)", [cid, fp, "456"])
        winners = [r["token"] for r in reservations if "token" in r]
        assert len(winners) == 1, reservations
        assert sum("hold" in r for r in reservations) == 1
        assert (
            db.execute(
                "select count(*) from icg.image_generation_calls where quality_candidate_id=%s",
                [cid],
            ).fetchone()[0]
            == 1
        )
        assert db.execute(
            "select icg.image_generation_finish_outcome_v3(%s,1,%s,%s,%s,.04,%s,null,null,3)",
            [scope, fp, winners[0], "success", new],
        ).fetchone()[0]["settled"]
        review = {
            "episode_continuity": "PASS",
            "evidence": "Whole episode and source/slide previews checked",
            "panels": [
                {
                    "panel_idx": 1,
                    "output_hash": new,
                    "safety": "PASS",
                    "canon": "PASS",
                    "quality": "PASS",
                    "assembly": "PASS",
                    "evidence": "Pose, shot and visible canon properties verified",
                }
            ],
        }
        assert db.execute(
            "select icg.image_quality_review(%s,%s,%s,%s)", [cid, digest, "reviewer", Jsonb(review)]
        ).fetchone()[0]["reviewed"]
        selections = race(
            "select icg.image_quality_select(%s,%s,0,%s,%s)",
            [cid, digest, "operator", "Select the reviewed candidate image and retain original"],
        )
        assert sum(r.get("selected") is True for r in selections) == 1, selections
        assert sum("hold" in r for r in selections) == 1
        assert (
            db.execute(
                "select version from icg.image_quality_selections where scope=%s", [scope]
            ).fetchone()[0]
            == 1
        )
        assert db.execute(
            "select status,script_json,artifact_run_id from icg.episode_assets"
        ).fetchone() == ("image_generated", source, "123")
        print(
            "Image quality PostgreSQL contracts PASS: two concurrent reservations yield one paid token; two concurrent selections yield one version; original episode intact"
        )


if __name__ == "__main__":
    main()
