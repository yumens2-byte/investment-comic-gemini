"""Two real PostgreSQL sessions: claim/revoke/selection serialization, no SNS IO."""
from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from urllib.parse import urlparse

import psycopg
from psycopg.types.json import Jsonb

MIGRATIONS = (
    'migrations/20261001132931_image_generation_guard.sql',
    'docs/sql/image-generation-revision.sql', 'docs/sql/image-generation-recovery.sql',
    'docs/sql/image-generation-retry.sql', 'docs/sql/image-generation-attempt-diagnostics.sql',
    'docs/sql/image-generation-outcome-v3.sql', 'docs/sql/image-generation-register-recovery-v3.sql',
    'docs/sql/image-quality-candidates.sql', 'supabase/migrations/20261026041544_visual_quality_contracts.sql',
)


def main():
    url = os.environ['DATABASE_TEST_URL']
    if urlparse(url).hostname not in {'localhost', '127.0.0.1'}:
        raise ValueError('isolated localhost PostgreSQL required')
    day, scope = '2026-10-26', 'output/episodes/2026-10-26/panels'
    fp, output, scene_hash = ('a'*64, 'b'*64, 'c'*64)
    source = {'date': day, 'episode_id': f'ICG-{day}-001', '_state_candidate': {'version': 'state-candidate-1'},
              'panels': [{'idx': 1, 'panel_type': 'CLIMAX', 'action': 'turns', 'setting': 'vault'}],
              '_scene_performance_v2': {'1': {'required_story_facts': ['unchanged']}}}
    initial = dict(source, _generation_revision=1, _reviewed_image_inputs={
        'version': 'reviewed-image-inputs-2', 'origin': 'INITIAL_GENERATION',
        'model': 'gemini-2.5-flash-image', 'aspect_ratio': '4:5', 'ref_binding_version': 'canon-form-1',
        'panels': [{'idx': 1, 'fingerprint': fp, 'scene_sha256': scene_hash, 'ref_bindings': []}]})
    policy = {'version': 'visual-quality-1', 'mode': 'enforce', 'layout': 'mobile-reserved-band-1', 'layout_sha256': 'd'*64}
    with psycopg.connect(url, autocommit=True) as db:
        db.execute('drop schema if exists icg cascade; create schema icg')
        for role in ('anon', 'authenticated', 'service_role'):
            if not db.execute('select 1 from pg_roles where rolname=%s', [role]).fetchone():
                db.execute(f'create role {role}')
        db.execute('alter role service_role bypassrls; grant usage on schema icg to service_role')
        db.execute('''create table icg.episode_assets(episode_date date,episode_no int,status text,
            script_json jsonb,artifact_run_id text,error_message text,updated_at timestamptz default clock_timestamp(),unique(episode_date,episode_no))''')
        db.execute('grant select,insert,update on icg.episode_assets to service_role')
        for path in MIGRATIONS:
            db.execute(Path(path).read_text())

        def fixture():
            db.execute('reset role')
            db.execute('''truncate icg.visual_quality_claims,icg.visual_quality_revocations,icg.visual_quality_reviews,
                icg.visual_quality_inputs,icg.image_quality_candidates,icg.image_quality_selections,icg.image_quality_selection_history,
                icg.image_generation_attempt_diagnostics,icg.image_generation_diagnostics,icg.image_generation_recovery_receipts,
                icg.image_generation_calls,icg.episode_assets cascade''')
            db.execute('insert into icg.episode_assets(episode_date,episode_no,status,script_json) values(%s,1,%s,%s)',
                       [day, 'narrative_done', Jsonb(source)])
            db.execute('set role service_role')
            frozen = db.execute('select icg.visual_quality_freeze_inputs(%s,%s,%s,%s,%s)',
                [Jsonb(source), Jsonb(initial), Jsonb(policy), 'operator', 'Freeze exact synthetic contract inputs before tests']).fetchone()[0]['script']
            token = db.execute('''insert into icg.image_generation_calls(scope,panel,fingerprint,state,cost,output_hash,revision)
                values(%s,1,%s,'success',.04,%s,1) returning token''', [scope, fp, output]).fetchone()[0]
            effective = [{'panel_idx': 1, 'output_hash': output, 'fingerprint': fp,
                'origin_token': str(token), 'origin_revision': 1, 'candidate_id': None,
                'scene_sha256': scene_hash, 'scene': source['_scene_performance_v2']['1'], 'ref_bindings': []}]
            script = dict(frozen, _effective_render_manifest=effective, _assembly_manifest={
                'version': 'assembly-manifest-2', 'policy_sha256': frozen['_visual_policy_sha256'],
                'effective_render_manifest': effective, 'slides': ['e'*64]})
            script['_assembly_manifest']['visual_contract'] = {
                'policy': script['_visual_policy'], 'scene_plan': script['_scene_performance_v2'],
                'mobile_layout_report': script.get('_mobile_layout_report'),
                'public_script': {k: v for k, v in script.items() if not k.startswith('_')},
            }
            db.execute("update icg.episode_assets set status='assembled',script_json=%s", [Jsonb(script)])
            review = {'episode_continuity': 'PASS', 'evidence': 'Synthetic test of a complete human evidence contract',
                'panels': [{'panel_idx': 1, 'output_hash': output, 'slide_hash': 'e'*64,
                'checks': {k: {'status': 'PASS', 'evidence': 'Synthetic contract evidence, not real visual approval'}
                           for k in ('motion', 'rhythm', 'canon', 'story', 'typography', 'mobile')}}]}
            rid = db.execute('select icg.visual_quality_record_review(%s,%s,%s)',
                             [Jsonb(script), Jsonb(review), 'reviewer']).fetchone()[0]['id']
            version = db.execute('select updated_at from icg.episode_assets').fetchone()[0]
            return script, rid, version

        def race(op_a, op_b):
            gate = Barrier(2)

            def execute(op):
                with psycopg.connect(url, autocommit=True) as session:
                    session.execute('set role service_role')
                    session.execute("set statement_timeout='10s'")
                    gate.wait(timeout=10)
                    try:
                        return op(session)
                    except psycopg.Error as exc:
                        if 'PUBLICATION_BUSY' not in str(exc):
                            raise
                        return {'hold': 'PUBLICATION_BUSY'}

            with ThreadPoolExecutor(max_workers=2) as pool:
                jobs = [pool.submit(execute, op) for op in (op_a, op_b)]
                return [job.result(timeout=20) for job in jobs]

        script, rid, version = fixture()

        def claim(session):
            return session.execute('select icg.claim_visual_publication(%s,1,%s,%s)',
                                   [day, version, Jsonb(script)]).fetchone()[0]

        a, b = race(claim, claim)
        assert sum('token' in r for r in (a, b)) == 1, (a, b)
        script, rid, version = fixture()

        def revoke(session):
            return session.execute('select icg.visual_quality_revoke(%s,%s,%s)',
                [rid, 'reviewer', 'Revoke exact synthetic review before sending']).fetchone()[0]

        a, b = race(claim, revoke)
        assert ('token' in a) != bool(b.get('revoked')), (a, b)
        script, rid, version = fixture()

        def select(session):
            session.execute('insert into icg.image_quality_selections(scope,version,manifest,actor,note) values(%s,1,%s,%s,%s)',
                            [scope, Jsonb([]), 'operator', 'Synthetic selection race'])
            return {'selected': True}

        a, b = race(claim, select)
        assert ('token' in a) != bool(b.get('selected')), (a, b)
    print('PASS: two-session claim/claim, claim/revoke, claim/selection races; no provider or SNS calls')


if __name__ == '__main__':
    main()
