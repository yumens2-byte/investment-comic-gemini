"""Human visual review CLI. Inspect never approves; writes require explicit action."""
from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from engine.image.generation_guard import GenerationHold
from engine.quality.visual import policy_present, rpc


def load_script(day: str) -> dict:
    from engine.common.supabase_client import icg_table
    if date.fromisoformat(day).isoformat() != day:
        raise GenerationHold('VISUAL_DATE_INVALID')
    rows = icg_table('episode_assets').select('*').eq('episode_date', day).eq('episode_no', 1).limit(2).execute().data
    if not isinstance(rows, list) or len(rows) != 1 or not policy_present(rows[0]['script_json'], rows[0]):
        raise GenerationHold('VISUAL_POLICY_EPISODE_REQUIRED')
    return rows[0]['script_json']


def review_template(script: dict) -> dict:
    manifest = script.get('_assembly_manifest') or {}
    if manifest.get('version') != 'assembly-manifest-2':
        raise GenerationHold('VISUAL_ASSEMBLY_REQUIRED')
    return {'episode_continuity': 'UNKNOWN', 'evidence': '', 'panels': [
        {'panel_idx': p['panel_idx'], 'output_hash': p['output_hash'],
         'slide_hash': manifest['slides'][p['panel_idx']-1],
         'checks': {k: {'status': 'UNKNOWN', 'evidence': ''} for k in
                    ('motion', 'rhythm', 'canon', 'story', 'typography', 'mobile')}}
        for p in script['_effective_render_manifest']]}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--stage', choices=['inspect', 'provenance', 'review', 'revoke'], default='inspect')
    p.add_argument('--date')
    p.add_argument('--review', type=Path)
    p.add_argument('--review-id')
    p.add_argument('--artifact-run-id')
    p.add_argument('--actor')
    p.add_argument('--note')
    p.add_argument('--output', type=Path)
    p.add_argument('--confirm')
    a = p.parse_args()
    if a.stage in {'inspect', 'provenance'}:
        if not a.date or not a.output:
            p.error('inspect requires --date and --output')
        script = load_script(a.date)
        if a.stage == 'provenance':
            from engine.quality.visual import base_manifest_with_origins
            template = base_manifest_with_origins(script, a.artifact_run_id)
        else:
            template = review_template(script)
        a.output.parent.mkdir(parents=True, exist_ok=True)
        with a.output.open('x', encoding='utf-8') as stream:
            json.dump(template, stream, ensure_ascii=False, indent=2)
        result = {'template_written': True, 'approved': False, 'database_writes': 0}
    else:
        if a.confirm != 'REVIEW_EXACT_VISUAL_ASSETS' or not a.actor:
            p.error('write actions require --actor and --confirm REVIEW_EXACT_VISUAL_ASSETS')
        if a.stage == 'review':
            if not a.date or not a.review:
                p.error('review requires --date and --review')
            result = rpc('visual_quality_record_review', {'p_script': load_script(a.date),
                'p_review': json.loads(a.review.read_text()), 'p_actor': a.actor})
        else:
            if not a.review_id or not a.note:
                p.error('revoke requires --review-id and --note')
            result = rpc('visual_quality_revoke', {'p_review_id': a.review_id,
                'p_actor': a.actor, 'p_note': a.note})
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
