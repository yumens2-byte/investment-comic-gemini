"""Read-only workflow invariants: dry dispatch cannot reach live mutation steps."""
from pathlib import Path

import pytest
import yaml

WORKFLOW = Path('.github/workflows/run_market.yml')


def workflow():
    return yaml.safe_load(WORKFLOW.read_text(encoding='utf-8'))


def steps():
    return workflow()['jobs']['pipeline']['steps']


def named(name):
    return next(step for step in steps() if step['name'] == name)


def test_dispatch_dry_run_is_real_boolean_not_string():
    parsed = workflow()
    trigger = parsed.get('on', parsed.get(True))
    dry = trigger['workflow_dispatch']['inputs']['dry_run']
    assert dry['type'] == 'boolean'
    assert dry['default'] is False
    env = parsed['jobs']['pipeline']['env']
    assert env['DRY_RUN'] == "${{ inputs.dry_run == true && 'true' || 'false' }}"


@pytest.mark.parametrize('name', [
    'STEP 2 — Data Ingest', 'STEP 3 — Analysis',
    'STEP 3.5 — Major Event Gate (for cost control)', 'STEP 3.6 — Major Gate Summary',
    'STEP 4 — Narrative (Claude)', 'STEP 5 — Persist',
    'STEP 6 — Image Generation (Gemini)',
])
def test_every_live_stage_requires_preflight_permission(name):
    condition = named(name)['if']
    # Parentheses keep stage OR branches from bypassing the shared gate.
    assert condition.startswith("${{ steps.preflight.outputs.allowed == 'true' && (")
    assert condition.endswith(') }}')


def test_preflight_runs_before_data_and_uses_read_only_cli():
    all_steps = steps()
    preflight = named('Execution preflight (read only)')
    assert preflight['id'] == 'preflight'
    assert all_steps.index(preflight) < all_steps.index(named('STEP 2 — Data Ingest'))
    script = preflight['run']
    assert 'python -m scripts.run_market --preflight-only' in script
    assert 'report["allowed"] and report["mode"] != "dry_run"' in script
    assert 'Live block reason:' in script
    assert 'status:' in script
    assert 'no DB writes, paid calls or publication' in script


def test_failure_notification_skips_dry_run():
    notification = named('Notify Failure')
    assert notification['if'] == "${{ failure() && env.DRY_RUN != 'true' }}"


def test_summary_does_not_claim_unexecuted_pipeline_finished():
    summary = named('PAUSE — Dialog Gate')
    assert summary['if'] == "${{ steps.preflight.outputs.allowed == 'true' }}"
    # Data-only and non-major schedule runs may execute only a subset.
    assert 'STEP 2~6 완료' not in summary['run']


def test_preflight_report_is_uploaded_for_dry_and_blocked_runs():
    artifact = named('Upload Episode Artifact')
    assert artifact['if'] == 'always()'
    assert 'output/run-market-preflight.json' in artifact['with']['path']
