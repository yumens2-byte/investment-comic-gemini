"""Reviewed retry contracts: offline only, no production writes or paid calls."""
import hashlib
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from engine.image import gemini_client as adapter
from engine.image.action_safety import check_observation_actions
from engine.image.generation_guard import GenerationHold
from engine.image.retry_policy import max_retries, normalized_reason
from tests.test_image_adapter_guard_v2 import png


def bundle(prompts, ref):
    body = {'version': 'image-retry-plan-1', 'prompts': prompts,
            'ref_sha256': [hashlib.sha256(ref.read_bytes()).hexdigest()]}
    body['plan_id'] = hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True,
                                  separators=(',', ':')).encode()).hexdigest()
    return body


@pytest.fixture
def harness(monkeypatch, tmp_path):
    monkeypatch.setenv('ICG_IMAGE_RETRY_V2_ENABLED', 'true')
    monkeypatch.setenv('ICG_IMAGE_DIAGNOSTICS_DIR', str(tmp_path / 'private'))
    monkeypatch.setattr(adapter, 'PROVIDER_REFUSAL_PATH', tmp_path / 'refusals.jsonl')
    ref = tmp_path / 'hero.png'
    ref.write_bytes(png())
    plan = bundle(['observes data', 'observes a calm screen', 'quiet standing observation'], ref)
    guard = Mock()
    guard.select_retry_variant.return_value = 0
    guard.retry_attempts_used = 0
    guard.reuse.return_value = False
    guard.reserve.side_effect = ['a', 'b', 'c']
    gen = Mock(return_value=(png(), 100, 1290))
    monkeypatch.setattr(adapter, '_get_client', Mock())
    monkeypatch.setattr(adapter, '_generate_one', gen)
    sleep = Mock()
    def run():
        return adapter.generate_panel(4, plan['prompts'][0], [ref], tmp_path / 'panels',
                                      tmp_path / 'run.log', guard=guard,
                                      retry_plan=plan, sleeper=sleep)
    return run, guard, gen, sleep, plan, ref, tmp_path


def test_refusal_then_reviewed_success(harness):
    run, guard, gen, sleep, plan, _, _ = harness
    gen.side_effect = [adapter.NoImageResponse('FinishReason.PROHIBITED_CONTENT', 100, 0),
                       (png(), 100, 1290)]
    path, cost = run()
    assert path.read_bytes() == png()
    assert cost == pytest.approx(adapter._calc_cost(100, 0) + adapter._calc_cost(100, 1290))
    assert [call.args[1] for call in gen.call_args_list] == plan['prompts'][:2]
    assert guard.finish_reviewed.call_args_list[0].kwargs['reason'] == 'PROHIBITED_CONTENT'
    sleep.assert_called_once()


def test_two_extra_retries_only(harness):
    run, guard, gen, sleep, plan, _, _ = harness
    gen.side_effect = adapter.NoImageResponse('PROHIBITED_CONTENT', 100, 0)
    with pytest.raises(adapter.PanelGenerationFailed):
        run()
    assert gen.call_count == 3 and guard.reserve.call_count == 3
    assert [call.args[1] for call in gen.call_args_list] == plan['prompts']
    assert sleep.call_count == 2


def test_restart_uses_ledger_selected_variant(harness):
    run, guard, gen, _, plan, _, _ = harness
    guard.select_retry_variant.return_value = 1
    run()
    assert gen.call_args.args[1] == plan['prompts'][1]
    assert gen.call_count == 1


@pytest.mark.parametrize('reason', ['SPII', 'RECITATION', 'BLOCKLIST'])
def test_unreviewable_refusal_stops(harness, reason):
    run, _, gen, sleep, _, _, _ = harness
    gen.side_effect = adapter.NoImageResponse(reason, 100, 0)
    with pytest.raises(GenerationHold):
        run()
    assert gen.call_count == 1
    sleep.assert_not_called()


def test_unknown_cost_prevents_content_retry(harness):
    run, guard, gen, _, _, _, _ = harness
    gen.side_effect = adapter.NoImageResponse('PROHIBITED_CONTENT', 0, 0)
    guard.finish_reviewed.side_effect = GenerationHold('unknown billing')
    with pytest.raises(GenerationHold):
        run()
    assert gen.call_count == 1


def test_timeout_does_not_retry(harness):
    run, _, gen, sleep, _, _, _ = harness
    gen.side_effect = TimeoutError('ambiguous')
    with pytest.raises(GenerationHold):
        run()
    assert gen.call_count == 1
    sleep.assert_not_called()


def test_settlement_failure_does_not_retry(harness):
    run, guard, gen, sleep, _, _, _ = harness
    gen.side_effect = adapter.NoImageResponse('PROHIBITED_CONTENT', 100, 0)
    guard.finish_reviewed.side_effect = GenerationHold('DB unavailable')
    with pytest.raises(GenerationHold):
        run()
    assert gen.call_count == 1
    sleep.assert_not_called()


def test_success_reuse_never_calls_provider(harness):
    run, guard, gen, _, _, _, root = harness
    path = root / 'panels/P4.png'
    path.parent.mkdir()
    path.write_bytes(png())
    guard.reuse.return_value = True
    assert run() == (path, 0.0)
    gen.assert_not_called()
    guard.reserve.assert_not_called()


@pytest.mark.parametrize('field,value', [('plan_id','0'*64), ('prompts',['different']),
                                        ('ref_sha256',['changed'])])
def test_changed_reviewed_plan_blocks_before_call(harness, field, value):
    run, guard, gen, _, plan, _, _ = harness
    plan[field] = value
    with pytest.raises(GenerationHold):
        run()
    gen.assert_not_called()
    guard.reserve.assert_not_called()


def test_no_private_storage_blocks_before_call(harness, monkeypatch):
    run, _, gen, _, _, _, _ = harness
    monkeypatch.delenv('ICG_IMAGE_DIAGNOSTICS_DIR')
    with pytest.raises(GenerationHold, match='diagnostics'):
        run()
    gen.assert_not_called()


def test_diagnostics_permissions_and_ref_hashes(harness):
    run, _, _, _, plan, _, root = harness
    run()
    path = next((root / 'private').glob('*.json'))
    assert path.stat().st_mode & 0o777 == 0o600
    assert json.loads(path.read_text())['plan_id'] == plan['plan_id']


def test_zero_retries_means_one_call(harness, monkeypatch):
    run, _, gen, sleep, _, _, _ = harness
    monkeypatch.setenv('ICG_IMAGE_MAX_RETRIES', '0')
    gen.side_effect = adapter.NoImageResponse('PROHIBITED_CONTENT', 100, 0)
    with pytest.raises(adapter.PanelGenerationFailed):
        run()
    assert gen.call_count == 1
    sleep.assert_not_called()


@pytest.mark.parametrize('value', ['-1','3','true','02'])
def test_unbounded_retry_setting_rejected(monkeypatch, value):
    monkeypatch.setenv('ICG_IMAGE_MAX_RETRIES', value)
    with pytest.raises(GenerationHold):
        max_retries()


def test_reason_enum_normalization():
    assert normalized_reason(SimpleNamespace(name='PROHIBITED_CONTENT')) == 'PROHIBITED_CONTENT'
    assert normalized_reason('FinishReason.SAFETY') == 'SAFETY'


def test_observation_conflict_and_safe_scene():
    script = {'_episode_decision': {'scenario_type':'NO_BATTLE', 'action_mode':'OBSERVATION'},
              'panels':[{'idx':4, 'action':'Hero raises both fists and drives them into holographic columns'}]}
    assert check_observation_actions(script)[0].rule == 'OBSERVATION_ACTION_CONFLICT'
    script['panels'][0]['action'] = 'Hero observes holographic columns with hands lowered'
    assert check_observation_actions(script) == []


def test_refusal_with_inline_image_is_not_success(monkeypatch):
    client = Mock()
    client.models.generate_content.return_value = {
        'candidates':[{'finish_reason':'PROHIBITED_CONTENT', 'content':{'parts':[{'inline_data':{'data':png()}}]}}],
        'usage_metadata':{'prompt_token_count':100},
    }
    with pytest.raises(adapter.NoImageResponse):
        adapter._generate_one(client, 'observation', [])
    assert client.models.generate_content.call_args.kwargs['config'].automatic_function_calling.disable is True


def test_settled_panel_failure_continues_but_global_hold_stops(monkeypatch, tmp_path):
    monkeypatch.setenv('ICG_IMAGE_RETRY_V2_ENABLED','true')
    def settled(**kwargs):
        if kwargs['panel_idx'] == 1:
            raise adapter.PanelGenerationFailed('exhausted', 0.01)
        return tmp_path / 'P2.png', 0.04
    monkeypatch.setattr(adapter, 'generate_panel', settled)
    (tmp_path / 'gemini_run.log').write_text('{"panel":1,"cost_usd":0.01}\n')
    results, cost = adapter.generate_episode([{'panel_idx':1},{'panel_idx':2}],tmp_path)
    assert results[0] is None and results[1].name == 'P2.png'
    assert cost == pytest.approx(0.05)
    blocked = Mock(side_effect=GenerationHold('unknown'))
    monkeypatch.setattr(adapter, 'generate_panel', blocked)
    with pytest.raises(GenerationHold):
        adapter.generate_episode([{'panel_idx':1},{'panel_idx':2}],tmp_path)
    assert blocked.call_count == 1


def test_existing_two_calls_only_allow_one_remaining(harness):
    run, guard, gen, sleep, _, _, _ = harness
    guard.retry_attempts_used = 2
    gen.side_effect = adapter.NoImageResponse('PROHIBITED_CONTENT', 100, 0)
    with pytest.raises(adapter.PanelGenerationFailed):
        run()
    assert gen.call_count == 1
    sleep.assert_not_called()


def test_retry_guard_cursor_requires_durable_count(tmp_path, monkeypatch):
    from engine.image.generation_guard import ProductionGenerationGuard
    ref = tmp_path / 'ref'
    ref.write_bytes(b'ref')
    guard = ProductionGenerationGuard(scope='output/episodes/2026-10-08/panels',
                                     panel=4, prompt='first', refs=[ref], retry_plan_id='a'*64)
    monkeypatch.setattr(guard, '_rpc', lambda *_: {'fingerprint': guard.fingerprint})
    with pytest.raises(GenerationHold, match='durable retry count'):
        guard.select_retry_variant(('first',), '')


def test_retry_guard_cursor_selects_existing_success_variant(tmp_path, monkeypatch):
    from engine.image.generation_guard import ProductionGenerationGuard
    ref = tmp_path / 'ref'
    ref.write_bytes(b'ref')
    guard = ProductionGenerationGuard(scope='output/episodes/2026-10-08/panels',
                                     panel=4, prompt='first', refs=[ref], retry_plan_id='a'*64)
    guard.activate_prompt('second')
    desired = guard.fingerprint
    monkeypatch.setattr(guard, '_rpc', lambda *_: {'fingerprint': desired, 'attempts_used': 2})
    assert guard.select_retry_variant(('first','second'), '') == 1
    assert guard.fingerprint == desired and guard.retry_attempts_used == 2


def test_private_refusal_evidence_preserves_details(harness):
    run, _, gen, _, _, _, root = harness
    gen.side_effect = [adapter.NoImageResponse('PROHIBITED_CONTENT', 100, 0,
                        {'finish_message':'provider explanation','safety_ratings':[]}),
                       (png(),100,1290)]
    run()
    evidence = json.loads(next((root / 'private').glob('response-*.json')).read_text())
    assert evidence['details']['finish_message'] == 'provider explanation'
    assert evidence['attempt'] == 1


def test_private_persistence_failure_prevents_paid_call(harness):
    run, guard, gen, _, _, _, _ = harness
    guard.store_diagnostic.side_effect = GenerationHold('storage unavailable')
    with pytest.raises(GenerationHold):
        run()
    gen.assert_not_called()


def test_private_refusal_persistence_failure_settles_before_hold(harness):
    run, guard, gen, sleep, _, _, _ = harness
    guard.store_diagnostic.side_effect = [None, GenerationHold('storage unavailable')]
    gen.side_effect = adapter.NoImageResponse('PROHIBITED_CONTENT',100,0)
    with pytest.raises(GenerationHold):
        run()
    assert guard.finish_reviewed.call_count == 1
    assert gen.call_count == 1
    sleep.assert_not_called()
