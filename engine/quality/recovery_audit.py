"""Read-only recovery evidence; neither provider failures nor story state are rewritten."""
from __future__ import annotations

import hashlib
import json
from decimal import Decimal, InvalidOperation


def _sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':')).encode()).hexdigest()


def audit_recovery(episode: dict, calls: list[dict], arc: dict, previous: dict) -> dict:
    script = episode.get('script_json') or {}
    revision = script.get('_generation_revision')
    if type(revision) is not int or not 1 <= revision <= 100:
        raise ValueError('invalid current generation revision')
    scope = f"output/episodes/{episode['episode_date']}/panels"
    blockers, terminal = [], []
    total = Decimal('0')
    for row in calls:
        if row.get('scope') != scope or row.get('state') not in {
            'reserved', 'unknown', 'terminal', 'success', 'failed'
        }:
            raise ValueError('invalid ledger evidence')
        try:
            cost = Decimal(str(row['cost']))
        except (KeyError, InvalidOperation) as exc:
            raise ValueError('invalid ledger cost') from exc
        if not cost.is_finite() or cost < 0:
            raise ValueError('invalid ledger cost')
        total += cost
        if row['state'] in {'reserved', 'unknown'}:
            blockers.append(f"UNSETTLED_CALL:{row['token']}")
        if row['state'] == 'terminal':
            terminal.append({key: row[key] for key in
                             ('token', 'panel', 'revision', 'fingerprint', 'cost')})
    if terminal:
        blockers.append('TERMINAL_RECEIPT_REQUIRED')
    previous_script = previous.get('script_json') or {}
    expected_hook = previous_script.get('next_hook')
    baseline_verified = (
        previous.get('status') == 'published'
        and previous.get('episode_no') == 1
        and previous.get('episode_date') == arc.get('last_episode_date')
        and previous.get('episode_date', '') < episode['episode_date']
        and isinstance(expected_hook, str) and bool(expected_hook.strip())
    )
    hook_repair = None
    if not baseline_verified:
        blockers.append('PUBLISHED_STATE_BASELINE_UNVERIFIED')
    elif arc.get('open_hook') != expected_hook:
        blockers.append('OPEN_HOOK_DIFFERS_FROM_LAST_PUBLISHED_EPISODE')
        hook_repair = {'field': 'open_hook', 'before': arc.get('open_hook'), 'after': expected_hook,
                       'source_episode_date': previous['episode_date'],
                       'source_script_sha256': _sha(previous_script),
                       'expected_arc_sha256': _sha(arc), 'apply': False}
    candidate = script.get('_state_candidate') or {}
    if candidate.get('base_arc') != arc:
        blockers.append('STATE_CANDIDATE_BASE_DIFFERS_FROM_CURRENT_ARC')
    if episode.get('status') != 'narrative_done':
        blockers.append('EPISODE_NOT_NARRATIVE_DONE')
    if (script.get('_recovery_qc') or {}).get('status') != 'PASS':
        blockers.append('CONTENT_QC_REVIEW_REQUIRED')
    return {'version': 'recovery-audit-1', 'episode_date': episode['episode_date'],
            'generation_revision': revision, 'scope': scope, 'call_count': len(calls),
            'ledger_cost_usd': format(total.quantize(Decimal('0.000000001')), 'f').rstrip('0').rstrip('.'),
            'ledger_cost_usd_exact': str(total), 'ledger_sha256': _sha(calls),
            'script_sha256': _sha(script), 'terminal_calls': terminal,
            'published_baseline_verified': baseline_verified,
            'proposed_open_hook_repair': hook_repair, 'blockers': blockers,
            'status': 'BLOCKED' if blockers else 'REVIEW_REQUIRED',
            'generation_authorized': False, 'database_writes': 0, 'paid_calls': 0, 'sns_sends': 0}
