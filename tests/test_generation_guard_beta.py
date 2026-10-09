"""The operational fault drill exercises the adapter without paid test calls."""
from types import SimpleNamespace
from unittest.mock import patch

from engine.image import generation_guard
from scripts.run_generation_guard_beta import run_beta


def test_operational_drill_all_faults_with_durable_fake_backend(tmp_path, monkeypatch):
    import threading
    import uuid
    rows = []
    lock = threading.Lock()

    def rpc(_self, name, args):
        with lock:
            scope = args['p_scope']
            matches = [r for r in rows if r['scope'] == scope]
            panels = [r for r in matches if r['panel'] == args['p_panel']]
            if name == 'image_generation_store_attempt_diagnostic':
                row = next(r for r in panels if r['token'] == args['p_token'])
                assert row['fingerprint'] == args['p_fingerprint']
                assert args['p_kind'] in {'inputs', 'refusal'}
                return {'stored': True}
            if name.endswith('finish'):
                row = next(r for r in rows if r['token'] == args['p_token'])
                assert row['state'] == 'reserved'
                row['state'] = 'unknown' if args['p_actual_cost'] is None else args['p_state']
                row['hash'] = args['p_output_hash']
                if row['state'] in {'unknown', 'terminal'}:
                    raise generation_guard.GenerationHold('scope hold')
                return {'settled': True}
            if any(r['state'] in {'reserved', 'unknown', 'terminal'} for r in matches):
                raise generation_guard.GenerationHold('scope hold')
            if any(r['fingerprint'] != args['p_fingerprint'] for r in panels):
                raise generation_guard.GenerationHold('identity hold')
            success = next((r for r in panels if r['state'] == 'success'), None)
            if name.endswith('inspect'):
                return {'output_hash': success['hash']} if success else {}
            if success or len(panels) >= 3:
                raise generation_guard.GenerationHold('cap hold')
            token = str(uuid.uuid4())
            rows.append({'scope': scope, 'panel': args['p_panel'],
                         'fingerprint': args['p_fingerprint'], 'state': 'reserved',
                         'token': token})
            return {'token': token}

    monkeypatch.setattr(generation_guard.ProductionGenerationGuard, '_rpc', rpc)
    monkeypatch.chdir(tmp_path)
    with patch('engine.image.gemini_client._get_client', return_value=SimpleNamespace()):
        report = run_beta(tmp_path / 'report')
    assert report['status'] == 'pass'
    assert len(report['checks']) == 6
    assert report['live_delivery'] == 'not_tested'
    assert all(r['state'] != 'reserved' for r in rows)
