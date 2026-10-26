"""Offline regression of the 2026-10-14 P5 refusal and Resume idle handling."""
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from engine.image import gemini_client as adapter
from engine.image.generation_guard import GenerationHold
from scripts import notify_failure, run_market, run_resume
from tests.test_image_adapter_guard_v2 import png
from tests.test_image_retry_defense import bundle


def target_table(monkeypatch, rows):
    import sys
    table = Mock()
    for method in ('select', 'eq', 'limit'):
        getattr(table, method).return_value = table
    table.execute.return_value = SimpleNamespace(data=rows)
    monkeypatch.setattr(sys.modules['engine.common.supabase_client'], 'icg_table', lambda _: table)
    return table


def test_scheduled_resume_idle_but_manual_missing_is_error(monkeypatch):
    monkeypatch.setattr(run_resume, '_latest_episode_id', lambda **kw: None)
    assert run_resume.prepare_resume_target(scheduled=True)['ready'] is False
    with pytest.raises(RuntimeError, match='No eligible'):
        run_resume.prepare_resume_target()


def test_resume_download_and_assembly_have_same_identity(monkeypatch):
    episode = 'ICG-2026-10-14-001'
    monkeypatch.setattr(run_resume, '_latest_episode_id', lambda **kw: episode)
    table = target_table(monkeypatch, [{'status': 'image_generated', 'artifact_run_id': '38470953872'}])
    result = run_resume.prepare_resume_target(scheduled=True)
    assert result == {'status': 'ready', 'ready': True, 'episode_id': episode, 'run_id': '38470953872'}
    assert [c.args for c in table.eq.call_args_list] == [('episode_date', '2026-10-14'), ('episode_no', 1)]


@pytest.mark.parametrize('status', ['narrative_done', 'failed', 'published', 'assembled'])
def test_scheduled_resume_never_adopts_ineligible_asset(monkeypatch, status):
    target_table(monkeypatch, [{'status': status, 'artifact_run_id': '1'}])
    with pytest.raises(RuntimeError):
        run_resume.prepare_resume_target('ICG-2026-10-14-001', scheduled=True)


@pytest.mark.parametrize('value', [None, '', '1\nready=true', True, 0, -1])
def test_invalid_artifact_identity_is_not_idle(monkeypatch, value):
    target_table(monkeypatch, [{'status': 'image_generated', 'artifact_run_id': value}])
    with pytest.raises(RuntimeError):
        run_resume.prepare_resume_target('ICG-2026-10-14-001', scheduled=True)


def test_resume_lookup_outage_is_not_idle(monkeypatch):
    table = target_table(monkeypatch, [])
    table.order.return_value = table
    table.execute.side_effect = ConnectionError('DB outage')
    with pytest.raises(RuntimeError, match='lookup failed'):
        run_resume.prepare_resume_target(scheduled=True)


def test_resume_outputs_idle_does_not_point_to_previous_artifact(monkeypatch, tmp_path):
    path = tmp_path / 'outputs'
    monkeypatch.setenv('GITHUB_OUTPUT', str(path))
    run_resume.emit_resume_target({'status': 'idle', 'ready': False})
    assert path.read_text() == 'ready=false\nepisode_id=\nrun_id=\n'


def test_p5_hold_progress_and_current_attempt_cost(monkeypatch, tmp_path):
    monkeypatch.setenv('GITHUB_RUN_ID', '123')
    monkeypatch.setenv('GITHUB_RUN_ATTEMPT', '2')
    def generate(**kw):
        idx = kw['panel_idx']
        adapter._write_jsonl_log(tmp_path / 'gemini_run.log', {
            'run_id': '123', 'run_attempt': '2', 'cost_usd': .000564 if idx == 5 else .04})
        if idx == 5:
            try:
                raise adapter.NoImageResponse('FinishReason.PROHIBITED_CONTENT', 1880, 0)
            except adapter.NoImageResponse as exc:
                raise GenerationHold('requires reconciliation') from exc
        p = tmp_path / f'P{idx}.png'
        p.write_bytes(png())
        return p, .04
    adapter._write_jsonl_log(tmp_path / 'gemini_run.log', {
        'run_id': '123', 'run_attempt': '1', 'cost_usd': 50})
    monkeypatch.setattr(adapter, 'generate_panel', generate)
    with pytest.raises(GenerationHold):
        adapter.generate_episode([{'panel_idx': i} for i in range(1, 7)], tmp_path)
    report = json.loads((tmp_path / 'generation-summary.json').read_text())
    assert report['successful_images'] == 4 and report['expected_images'] == 6
    assert report['held_panel'] == 5 and report['not_attempted_images'] == 1
    assert report['provider_reason'] == 'PROHIBITED_CONTENT'
    assert report['observed_provider_cost_usd'] == pytest.approx(.160564)
    assert report['cost_complete'] is False and report['complete'] is False
    assert not (tmp_path / 'P5.png').exists() and not (tmp_path / 'P6.png').exists()
    assert all((tmp_path / f'P{i}.png').is_file() for i in range(1, 5))


def test_invalid_later_retry_plan_blocks_all_paid_calls(monkeypatch, tmp_path):
    monkeypatch.setenv('ICG_IMAGE_RETRY_V2_ENABLED', 'true')
    ref = tmp_path / 'ref.png'
    ref.write_bytes(png())
    plan = bundle(['safe observation', 'safe screen observation'], ref)
    plan['plan_id'] = '0' * 64
    paid = Mock()
    monkeypatch.setattr(adapter, 'generate_panel', paid)
    with pytest.raises(GenerationHold):
        adapter.generate_episode([
            {'panel_idx': 1}, {'panel_idx': 5, 'prompt_text': 'safe observation',
                             'ref_image_paths': [ref], 'retry_plan': plan}], tmp_path)
    paid.assert_not_called()


def test_alert_uses_only_current_run_attempt_without_private_inputs(monkeypatch, tmp_path):
    monkeypatch.setenv('GITHUB_RUN_ID', '123')
    monkeypatch.setenv('GITHUB_RUN_ATTEMPT', '2')
    root = tmp_path / 'episodes'
    def report(day, run_id, attempt, done):
        path = root / day / 'panels' / 'generation-summary.json'
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({'run_id': run_id, 'run_attempt': attempt,
            'complete': False, 'expected_images': 6, 'successful_images': done,
            'not_attempted_images': 1, 'prompt_text': 'PRIVATE'}))
    report('2026-10-14', '123', '2', 4)
    report('2026-10-13', '123', '1', 1)
    text = notify_failure.image_hold_details(root)
    assert '4/6' in text and '1/6' not in text and 'PRIVATE' not in text


@pytest.mark.parametrize('attempt', ['1', '5'])
def test_held_image_run_preserves_artifact_pointer_without_success_status(monkeypatch, tmp_path, attempt):
    from engine.image import prompt_builder
    from engine.persist import asset_writer
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('GITHUB_RUN_ID', '123')
    monkeypatch.setenv('GITHUB_RUN_ATTEMPT', attempt)
    summary = tmp_path / 'output/episodes/2026-10-14/panels/generation-summary.json'
    summary.parent.mkdir(parents=True)
    summary.write_text(json.dumps({'run_id': '123', 'run_attempt': attempt, 'successful_images': 1}))
    prompts = [SimpleNamespace(panel_idx=1, prompt_text='safe', ref_image_paths=[])]
    monkeypatch.setattr(prompt_builder, 'build_for_episode', lambda *a, **kw: prompts)
    monkeypatch.setattr(adapter, 'generate_episode', Mock(side_effect=GenerationHold('P1 held')))
    patch = Mock()
    monkeypatch.setattr(asset_writer, 'patch_by_episode', patch)
    with pytest.raises(GenerationHold):
        run_market.step_image('2026-10-14', 'ICG-2026-10-14-001', {},
            {'panels': [{'idx': 1, 'panel_type': 'TENSION'}]}, Mock())
    assert patch.call_args.args == ('2026-10-14', 1, {'artifact_run_id': '123'})


@pytest.mark.parametrize('rows', [None, [{'episode_date': '2026-10-14', 'episode_no': True}],
    [{'episode_date': '2026-99-14', 'episode_no': 1}], 'bad-response'])
def test_malformed_resume_query_is_not_idle(monkeypatch, rows):
    table = target_table(monkeypatch, rows)
    table.order.return_value = table
    with pytest.raises(RuntimeError, match='lookup failed'):
        run_resume.prepare_resume_target(scheduled=True)


@pytest.mark.parametrize('attempt', ['1', '5'])
def test_failed_artifact_pointer_write_preserves_original_hold(monkeypatch, tmp_path, attempt):
    from engine.image import prompt_builder
    from engine.persist import asset_writer
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('GITHUB_RUN_ID', '123')
    monkeypatch.setenv('GITHUB_RUN_ATTEMPT', attempt)
    summary = tmp_path / 'output/episodes/2026-10-14/panels/generation-summary.json'
    summary.parent.mkdir(parents=True)
    summary.write_text(json.dumps({'run_id': '123', 'run_attempt': attempt, 'successful_images': 1}))
    prompts = [SimpleNamespace(panel_idx=1, prompt_text='safe', ref_image_paths=[])]
    monkeypatch.setattr(prompt_builder, 'build_for_episode', lambda *a, **kw: prompts)
    monkeypatch.setattr(adapter, 'generate_episode', Mock(side_effect=GenerationHold('original hold')))
    patch = Mock(side_effect=ConnectionError('outage'))
    monkeypatch.setattr(asset_writer, 'patch_by_episode', patch)
    with pytest.raises(GenerationHold, match='original hold'):
        run_market.step_image('2026-10-14', 'ICG-2026-10-14-001', {},
            {'panels': [{'idx': 1, 'panel_type': 'TENSION'}]}, Mock())
    patch.assert_called_once()


def test_held_image_run_rejects_other_attempt_pointer(monkeypatch, tmp_path):
    from engine.image import prompt_builder
    from engine.persist import asset_writer
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('GITHUB_RUN_ID', '123')
    monkeypatch.setenv('GITHUB_RUN_ATTEMPT', '5')
    summary = tmp_path / 'output/episodes/2026-10-14/panels/generation-summary.json'
    summary.parent.mkdir(parents=True)
    summary.write_text(json.dumps({'run_id': '123', 'run_attempt': '1', 'successful_images': 1}))
    monkeypatch.setattr(prompt_builder, 'build_for_episode', lambda *a, **kw: [
        SimpleNamespace(panel_idx=1, prompt_text='safe', ref_image_paths=[])])
    monkeypatch.setattr(adapter, 'generate_episode', Mock(side_effect=GenerationHold('original hold')))
    patch = Mock()
    monkeypatch.setattr(asset_writer, 'patch_by_episode', patch)
    with pytest.raises(GenerationHold, match='original hold'):
        run_market.step_image('2026-10-14', 'ICG-2026-10-14-001', {},
            {'panels': [{'idx': 1, 'panel_type': 'TENSION'}]}, Mock())
    patch.assert_not_called()


@pytest.mark.parametrize('summary', [None,
    {'run_id': 'old', 'run_attempt': '1', 'successful_images': 4},
    {'run_id': '123', 'run_attempt': '1', 'successful_images': 0}])
def test_early_hold_never_overwrites_previous_artifact_pointer(monkeypatch, tmp_path, summary):
    from engine.image import prompt_builder
    from engine.persist import asset_writer
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('GITHUB_RUN_ID', '123')
    if summary is not None:
        path = tmp_path / 'output/episodes/2026-10-14/panels/generation-summary.json'
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(summary))
    monkeypatch.setattr(prompt_builder, 'build_for_episode', Mock(side_effect=GenerationHold('precall hold')))
    patch = Mock()
    monkeypatch.setattr(asset_writer, 'patch_by_episode', patch)
    with pytest.raises(GenerationHold):
        run_market.step_image('2026-10-14', 'ICG-2026-10-14-001', {}, {'panels': []}, Mock())
    patch.assert_not_called()
