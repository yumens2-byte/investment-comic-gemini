from copy import deepcopy

import pytest

from engine.quality.recovery_audit import audit_recovery


@pytest.fixture
def evidence():
    arc = {'id': 1, 'last_episode_date': '2026-10-01', 'open_hook': 'unpublished hook', 'arc_day': 64}
    episode = {'episode_date': '2026-10-02', 'status': 'narrative_done', 'script_json': {
        '_generation_revision': 2, '_state_candidate': {'base_arc': deepcopy(arc)},
        '_recovery_qc': {'status': 'HOLD'}}}
    calls = [{'scope': 'output/episodes/2026-10-02/panels', 'token': 'token', 'panel': 6,
              'revision': 2, 'fingerprint': 'a' * 64, 'state': 'terminal', 'cost': .0005385}]
    previous = {'episode_date': '2026-10-01', 'episode_no': 1, 'status': 'published',
                'script_json': {'next_hook': 'published hook'}}
    return episode, calls, arc, previous


def test_proposes_only_evidence_backed_hook_repair_without_mutation(evidence):
    before = deepcopy(evidence)
    report = audit_recovery(*evidence)
    assert evidence == before
    assert report['ledger_cost_usd'] == '0.0005385'
    assert report['proposed_open_hook_repair']['after'] == 'published hook'
    assert report['proposed_open_hook_repair']['apply'] is False
    assert report['terminal_calls'][0]['token'] == 'token'
    assert report['generation_authorized'] is False
    assert report['database_writes'] == report['paid_calls'] == report['sns_sends'] == 0


@pytest.mark.parametrize('change', [{'status': 'narrative_done'}, {'episode_date': '2026-09-30'},
                                   {'script_json': {}}, {'episode_no': 2}])
def test_unverified_baseline_cannot_propose_restore(evidence, change):
    evidence[3].update(change)
    report = audit_recovery(*evidence)
    assert report['proposed_open_hook_repair'] is None
    assert 'PUBLISHED_STATE_BASELINE_UNVERIFIED' in report['blockers']


@pytest.mark.parametrize('state', ['unknown', 'reserved'])
def test_unsettled_records_remain_blocked(evidence, state):
    evidence[1][0]['state'] = state
    assert 'UNSETTLED_CALL:token' in audit_recovery(*evidence)['blockers']


@pytest.mark.parametrize('cost', [-1, float('inf'), float('nan'), 'invalid'])
def test_invalid_cost_rejects_evidence(evidence, cost):
    evidence[1][0]['cost'] = cost
    with pytest.raises(ValueError, match='ledger cost'):
        audit_recovery(*evidence)


def test_candidate_drift_identified(evidence):
    evidence[0]['script_json']['_state_candidate']['base_arc']['arc_day'] = 65
    assert 'STATE_CANDIDATE_BASE_DIFFERS_FROM_CURRENT_ARC' in audit_recovery(*evidence)['blockers']


def test_even_clean_audit_is_not_generation_permission(evidence):
    evidence[2]['open_hook'] = 'published hook'
    evidence[0]['script_json']['_state_candidate']['base_arc'] = deepcopy(evidence[2])
    evidence[0]['script_json']['_recovery_qc']['status'] = 'PASS'
    report = audit_recovery(evidence[0], [], evidence[2], evidence[3])
    assert report['status'] == 'REVIEW_REQUIRED'
    assert report['generation_authorized'] is False
