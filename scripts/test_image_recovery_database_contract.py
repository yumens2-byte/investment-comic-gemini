"""Recovery SQL contracts on an isolated localhost database, never production."""
import os
from pathlib import Path
from urllib.parse import urlparse

import psycopg
from psycopg.types.json import Jsonb


def main():
    url = os.environ['DATABASE_TEST_URL']
    if urlparse(url).hostname not in {'localhost', '127.0.0.1'}:
        raise ValueError('isolated localhost database required')
    with psycopg.connect(url, autocommit=True) as db:
        db.execute('drop schema if exists icg cascade')
        db.execute('create schema icg')
        for role in ('anon', 'authenticated', 'service_role'):
            if not db.execute('select 1 from pg_roles where rolname=%s', [role]).fetchone():
                db.execute(f'create role {role}')
        db.execute('create table icg.episode_assets(episode_date date,episode_no integer,'
                   'status text,script_json jsonb,unique(episode_date,episode_no))')
        for path in ('migrations/20261001132931_image_generation_guard.sql',
                     'docs/sql/image-generation-revision.sql',
                     'docs/sql/image-generation-recovery.sql'):
            if path.endswith('image-generation-recovery.sql'):
                db.execute('alter default privileges in schema icg grant all on tables to service_role')
            db.execute(Path(path).read_text())
        scope = 'output/episodes/2026-10-02/panels'
        old, new = 'a' * 64, 'b' * 64
        script = {'_generation_revision': 3, '_state_candidate': {'version': 'state-candidate-1'},
                  '_recovery_qc': {'status': 'HOLD'},
                  'panels': [{'idx': 1}, {'idx': 6}, {'idx': 7, 'panel_type': 'TEXT_CARD'}]}
        db.execute("insert into icg.episode_assets values('2026-10-02',1,'narrative_done',%s)",
                   [Jsonb(script)])
        token = db.execute("insert into icg.image_generation_calls"
                           "(scope,panel,fingerprint,state,cost,revision) "
                           "values(%s,6,%s,'terminal',.0005385,2) returning token", [scope, old])
        token = token.fetchone()[0]
        before = db.execute('select to_jsonb(c) from icg.image_generation_calls c').fetchall()
        fingerprints = {'1': 'c' * 64, '6': new}
        evidence = 'run 36941053986: known provider usage, reviewed scene redesign'

        def ack(cost=.0005385, fp=None, reviewed=None, note=evidence):
            return db.execute('select icg.image_generation_acknowledge_terminal(%s,3,%s::numeric,%s,%s,%s)',
                              [token, cost, Jsonb(reviewed or script),
                               Jsonb(fp or fingerprints), note]).fetchone()[0]

        def inspect(fp=new, revision=3):
            return db.execute('select icg.image_generation_inspect_v2(%s,6,%s,%s)',
                              [scope, fp, revision]).fetchone()[0]

        assert 'hold' in inspect()
        assert 'hold' in ack(cost=.10)
        assert 'hold' in ack(cost=None)
        assert 'hold' in ack(fp={'1': 'c' * 64, '6': old})
        assert 'hold' in ack(fp={'6': new})
        assert 'hold' in ack(fp={'1': None, '6': new})
        assert 'hold' in ack(note='unverified')
        assert 'hold' in ack(reviewed=dict(script, title='changed'))
        assert ack()['acknowledged'] is True
        assert ack()['acknowledged'] is True
        assert 'hold' in ack(fp={'1': 'd' * 64, '6': new})
        assert db.execute('select count(*) from icg.image_generation_recovery_receipts').fetchone()[0] == 1
        assert db.execute('select to_jsonb(c) from icg.image_generation_calls c').fetchall() == before
        assert 'hold' not in inspect()
        assert 'hold' in inspect(fp='e' * 64)
        db.execute('update icg.episode_assets set script_json=%s', [Jsonb(dict(script, title='drift'))])
        assert 'hold' in inspect()
        db.execute('update icg.episode_assets set script_json=%s', [Jsonb(script)])
        # A reviewed scene gets one reservation; the old terminal row remains intact.
        new_token = db.execute('select icg.image_generation_reserve_v2(%s,1,%s,3)',
                               [scope, fingerprints['1']]).fetchone()[0]['token']
        result = db.execute("select icg.image_generation_finish(%s,1,%s,%s,'success',.04,%s)",
                            [scope, fingerprints['1'], new_token, 'd' * 64]).fetchone()[0]
        assert result['settled'] is True
        assert db.execute('select to_jsonb(c) from icg.image_generation_calls c where token=%s',
                          [token]).fetchall() == before
        assert db.execute('select count(*) from icg.image_generation_calls').fetchone()[0] == 2
        # Every unsettled/new terminal outcome freezes the scope again.
        for state in ('reserved', 'unknown', 'terminal'):
            t = db.execute('insert into icg.image_generation_calls'
                           '(scope,panel,fingerprint,state,revision) values(%s,2,%s,%s,3) returning token',
                           [scope, 'f' * 64, state]).fetchone()[0]
            assert 'hold' in inspect()
            if state != 'terminal':
                assert 'hold' in ack()
            db.execute('delete from icg.image_generation_calls where token=%s', [t])
        # Preserved calls count toward the original panel cap.
        db.execute("insert into icg.image_generation_calls(scope,panel,fingerprint,state,cost) "
                   "values(%s,6,%s,'success',.04),(%s,6,%s,'success',.04)",
                   [scope, 'd' * 64, scope, 'e' * 64])
        assert db.execute('select icg.image_generation_reserve_v2(%s,6,%s,3)',
                          [scope, new]).fetchone()[0]['hold'] == 'generation budget exhausted'
        # Cost-overrun terminals can contain an image. Archive its receipted bytes,
        # rather than treating the restored file as an unreceipted provider result.
        over_scope = 'output/episodes/2026-10-03/panels'
        db.execute("insert into icg.episode_assets values('2026-10-03',1,'narrative_done',%s)",
                   [Jsonb(script)])
        over_token = db.execute("insert into icg.image_generation_calls"
                                "(scope,panel,fingerprint,state,cost,revision,output_hash) "
                                "values(%s,1,%s,'terminal',.12,2,%s) returning token",
                                [over_scope, old, '7' * 64]).fetchone()[0]
        assert db.execute('select icg.image_generation_acknowledge_terminal'
                          '(%s,3,.12,%s,%s,%s)', [over_token, Jsonb(script),
                                                Jsonb(fingerprints), evidence]).fetchone()[0][
                                                    'acknowledged'] is True
        archived = db.execute('select icg.image_generation_inspect_v2(%s,1,%s,3)',
                              [over_scope, fingerprints['1']]).fetchone()[0]
        assert archived['prior_hashes'] == ['7' * 64]
        # An unreviewed target revision cannot use that archival receipt.
        assert 'hold' in db.execute('select icg.image_generation_inspect_v2(%s,1,%s,4)',
                                   [over_scope, fingerprints['1']]).fetchone()[0]
        for role in ('anon', 'authenticated'):
            assert not db.execute("select has_function_privilege(%s,"
                                  "'icg.image_generation_acknowledge_terminal(uuid,integer,numeric,jsonb,jsonb,text)',"
                                  "'execute')", [role]).fetchone()[0]
            assert not db.execute("select has_table_privilege(%s,"
                                  "'icg.image_generation_recovery_receipts','select')", [role]).fetchone()[0]
        assert not db.execute("select has_table_privilege('service_role',"
                              "'icg.image_generation_recovery_receipts','update')").fetchone()[0]
        assert all(row[0] == script for row in db.execute(
            'select script_json from icg.episode_assets').fetchall())
        print('Recovery PostgreSQL contracts passed: immutable receipts, exact inputs, '
              'known costs, unsettled holds, unchanged ledger, budget caps, service-only access')


if __name__ == '__main__':
    main()
