"""Bounded production guard integration test; never publishes or edits episodes."""
from __future__ import annotations

import hashlib
import json
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from engine.image.generation_guard import GenerationHold, ProductionGenerationGuard


def expect_hold(callback):
    try:
        callback()
    except GenerationHold:
        return
    raise AssertionError('Expected fail-closed HOLD')


def run_beta(root: Path, *, live_image: bool = False):
    report = {'status': 'failed', 'checks': [], 'live_delivery': 'not_tested',
              'comic_visual_qc': 'not_tested'}
    commit = os.environ.get('GITHUB_SHA', 'local')
    run_id = os.environ.get('GITHUB_RUN_ID', uuid.uuid4().hex)
    attempt = os.environ.get('GITHUB_RUN_ATTEMPT', '1')
    prefix = f'output/guard-beta/{commit}/{run_id}/{attempt}'

    def guard(name, panel=1, prompt='guard test'):
        return ProductionGenerationGuard(scope=f'{prefix}/{name}', panel=panel,
                                         prompt=prompt, refs=[])

    def rpc_attempt(_):
        instance = guard('concurrency')
        try:
            return instance.reserve()
        except GenerationHold:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        tokens = list(pool.map(rpc_attempt, range(2)))
    assert sum(t is not None for t in tokens) == 1
    guard('concurrency').finish(next(t for t in tokens if t), state='failed', actual_cost=0)
    report['checks'].append('atomic_concurrent_reservation')
    for _ in range(2):
        instance = guard('concurrency')
        instance.finish(instance.reserve(), state='failed', actual_cost=0)
    expect_hold(lambda: guard('concurrency').reserve())
    report['checks'].append('restart_cumulative_three_call_cap')

    instance = guard('unknown')
    expect_hold(lambda: instance.finish(instance.reserve(), state='unknown', actual_cost=None))
    expect_hold(lambda: guard('unknown', panel=2).reserve())
    report['checks'].append('unknown_cost_scope_circuit_stop')
    instance = guard('terminal')
    expect_hold(lambda: instance.finish(instance.reserve(), state='terminal', actual_cost=0))
    expect_hold(lambda: guard('terminal', panel=2).reserve())
    report['checks'].append('terminal_scope_circuit_stop')

    root.mkdir(parents=True, exist_ok=True)
    image_path = root / 'receipt.png'
    Image.new('RGB', (32, 32), '#556677').save(image_path)
    digest = hashlib.sha256(image_path.read_bytes()).hexdigest()
    instance = guard('success')
    instance.finish(instance.reserve(), state='success', actual_cost=0, output_hash=digest)
    assert guard('success').reuse(image_path)
    expect_hold(lambda: guard('success', prompt='changed').reserve())
    image_path.unlink()
    expect_hold(lambda: guard('success').reuse(image_path))
    report['checks'].append('success_reuse_identity_and_missing_artifact_hold')

    # Real adapter + durable DB, simulated quota: zero real paid calls.
    from engine.image.gemini_client import generate_panel
    class QuotaError(RuntimeError):
        code = 429
    with patch('engine.image.gemini_client._get_client', return_value=object()), patch(
        'engine.image.gemini_client._generate_one', side_effect=QuotaError('quota exhausted')
    ) as provider:
        expect_hold(lambda: generate_panel(1, 'abstract no-character background', [],
                    Path(f'{prefix}/adapter-quota'), root / 'quota.jsonl'))
        expect_hold(lambda: generate_panel(1, 'abstract no-character background', [],
                    Path(f'{prefix}/adapter-quota'), root / 'quota.jsonl'))
        assert provider.call_count == 1
    report['checks'].append('adapter_quota_rerun_no_second_call')

    if live_image:
        live_prompt = ('Pure visual abstract market atmosphere: blue and amber light ribbons over a '
            'dark geometric landscape. No people, characters, limbs, faces, text, digits, '
            'letters, labels, logos or typography. Clean coherent composition.')
        live_dir = Path(f'output/guard-beta/live-{commit}')
        live_guard = ProductionGenerationGuard(
            scope=live_dir.as_posix(), panel=1,
            prompt=live_prompt + '\n[model=gemini-2.5-flash-image;aspect=4:5]', refs=[],
        )
        receipt = live_guard._rpc('image_generation_inspect', live_guard._identity())
        if receipt.get('output_hash') and not (live_dir / 'P1.png').exists():
            report['live_image'] = {'status': 'already_settled_restore_artifact',
                                    'new_paid_calls': 0, 'visual_review': 'not_repeated'}
            report['status'] = 'pass'
            return report
        path, cost = generate_panel(
            1, live_prompt, [], live_dir, root / 'live-image.jsonl', aspect_ratio='4:5',
        )
        assert path is not None and path.is_file()
        with Image.open(path) as image:
            image.verify()
        import shutil
        shutil.copy2(path, root / 'live-image.png')
        report['live_image'] = {'status': 'pass', 'cost_usd': cost,
                                'visual_review': 'pending'}
    report['status'] = 'pass'
    return report


def main():
    root = Path('output/generation-guard-beta')
    try:
        report = run_beta(root, live_image=os.environ.get('GUARD_BETA_LIVE_IMAGE') == 'true')
    except Exception as exc:
        report = {'status': 'failed', 'error_type': type(exc).__name__}
    root.mkdir(parents=True, exist_ok=True)
    (root / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report))
    return 0 if report['status'] == 'pass' else 1


if __name__ == '__main__':
    raise SystemExit(main())
