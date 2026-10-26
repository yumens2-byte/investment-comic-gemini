"""Versioned visual evidence and DB authorization. Legacy policies remain optional."""
from __future__ import annotations

import hashlib
from copy import deepcopy
from pathlib import Path

from engine.image.generation_guard import GenerationHold, ProductionGenerationGuard
from engine.image.scene_performance import episode_specs, payload_hash, rhythm_report

CAPABILITY = 'visual-quality-1'


def rpc(name: str, params: dict) -> dict:
    from engine.common.supabase_client import get_client, get_schema
    try:
        value = get_client().schema(get_schema()).rpc(name, params).execute().data
    except Exception as exc:
        raise GenerationHold('VISUAL_DATABASE_UNAVAILABLE') from exc
    if not isinstance(value, dict) or value.get('hold'):
        raise GenerationHold(value.get('hold', 'VISUAL_INVALID_RECEIPT') if isinstance(value, dict)
                             else 'VISUAL_INVALID_RECEIPT')
    return value


def policy_for_new_episode() -> dict | None:
    import os

    from engine.assembly.mobile_layout import PROFILE
    mode = os.environ.get('ICG_VISUAL_QUALITY_MODE', 'off')
    if mode not in {'off', 'shadow', 'enforce'}:
        raise GenerationHold('VISUAL_MODE_INVALID')
    if mode != 'enforce':
        return None
    return {'version': CAPABILITY, 'mode': 'enforce', 'layout': PROFILE['id'],
            'layout_sha256': payload_hash(PROFILE)}


def freeze_initial_inputs(source: dict, *, actor: str, note: str) -> dict:
    """Existing persisted narrative CAS -> revision 1 DB receipt; no image calls."""
    from engine.image.prompt_builder import build_for_episode
    from engine.image.ref_loader import get_ref_bindings_for_panel
    from engine.publish.manifest import script_hash
    policy = policy_for_new_episode()
    if (policy is None or type(source.get('_generation_revision', 1)) is not int
            or source.get('_generation_revision', 1) != 1
            or (source.get('_state_candidate') or {}).get('version') != 'state-candidate-1'):
        raise GenerationHold('VISUAL_INITIAL_POLICY_REQUIRED')
    if source.get('_reviewed_image_inputs') is not None:
        raise GenerationHold('VISUAL_INITIAL_INPUTS_ALREADY_PRESENT')
    specs = episode_specs(source)
    if not specs:
        raise GenerationHold('VISUAL_PLAN_MISSING')
    capability = rpc('visual_quality_capability', {})
    if capability.get('version') != CAPABILITY:
        raise GenerationHold('VISUAL_CAPABILITY_MISSING')
    candidate = deepcopy(source)
    candidate['_generation_revision'] = 1
    inputs = []
    for prompt in build_for_episode(candidate):
        if prompt.panel_idx not in specs:
            continue
        guard = ProductionGenerationGuard(scope=f"output/episodes/{source['date']}/panels",
            panel=prompt.panel_idx, prompt=prompt.prompt_text+'\n[model=gemini-2.5-flash-image;aspect=4:5]',
            refs=prompt.ref_image_paths)
        if guard.revision != 1:
            raise GenerationHold('VISUAL_INITIAL_REVISION_REQUIRED')
        inputs.append({'idx': prompt.panel_idx, 'prompt_text': prompt.prompt_text,
            'refs': [p.as_posix() for p in prompt.ref_image_paths],
            'ref_sha256': [hashlib.sha256(p.read_bytes()).hexdigest() for p in prompt.ref_image_paths],
            'ref_bindings': get_ref_bindings_for_panel(candidate['panels'][prompt.panel_idx-1].get('characters', [])),
            'fingerprint': guard.fingerprint,
            'render_sources_report': prompt.render_sources_report,
            'scene_sha256': payload_hash(specs[prompt.panel_idx].model_dump())})
    candidate['_reviewed_image_inputs'] = {'version': 'reviewed-image-inputs-2',
        'origin': 'INITIAL_GENERATION', 'ref_binding_version': 'canon-form-1',
        'script_hash': script_hash(candidate), 'model': 'gemini-2.5-flash-image',
        'aspect_ratio': '4:5', 'panels': inputs}
    result = rpc('visual_quality_freeze_inputs', {'p_expected_script': source,
        'p_script': candidate, 'p_policy': policy, 'p_actor': actor, 'p_note': note})
    if result.get('registered') is not True or not isinstance(result.get('script'), dict):
        raise GenerationHold('VISUAL_FREEZE_NOT_CONFIRMED')
    return result['script']


def require_inputs(script: dict) -> None:
    value = rpc('visual_quality_require_inputs', {'p_script': script})
    if value.get('authorized') is not True:
        raise GenerationHold('VISUAL_INPUTS_NOT_AUTHORIZED')


def policy_present(script: dict, row: dict | None = None) -> bool:
    """The DB row is authoritative when supplied; a missing mirror must not bypass."""
    if row and row.get('visual_policy_json') is not None:
        if (script.get('_visual_policy') != row['visual_policy_json']
                or script.get('_visual_policy_sha256') != row.get('visual_policy_sha256')):
            raise GenerationHold('VISUAL_POLICY_MIRROR_CHANGED')
        return True
    return any(key in script for key in ('_visual_policy_intent', '_visual_policy', '_visual_policy_sha256'))


def source_manifest(script: dict, images: list[Path | None]) -> list[dict]:
    """Join actual PNG bytes to the selected panel's own plan and generation receipt."""
    from engine.common.supabase_client import icg_table
    scope = f"output/episodes/{script['date']}/panels"
    calls = icg_table('image_generation_calls').select('*').eq('scope', scope).eq('state', 'success').execute().data
    if not isinstance(calls, list):
        raise GenerationHold('VISUAL_PROVENANCE_UNAVAILABLE')
    specs = episode_specs(script)
    fixed = {p['idx']: p for p in script['_reviewed_image_inputs']['panels']}
    selection = {p['panel_idx']: p for p in (script.get('_image_quality_selection') or {}).get('manifest', [])}
    result = []
    for panel, image in zip(script['panels'], images):
        idx = panel['idx']
        if idx not in specs:
            continue
        if image is None:
            raise GenerationHold('VISUAL_SOURCE_MISSING')
        digest = hashlib.sha256(image.read_bytes()).hexdigest()
        item, scene = fixed[idx], specs[idx].model_dump()
        selected = selection.get(idx, {})
        candidate_id = None
        artifact = selected.get('artifact_name', '')
        if artifact.startswith('image-quality-'):
            import uuid
            candidate_id = str(uuid.UUID(artifact.removeprefix('image-quality-')))
            rows = icg_table('image_quality_candidates').select('bundle').eq('id', candidate_id).execute().data
            if not isinstance(rows, list) or len(rows) != 1:
                raise GenerationHold('VISUAL_SELECTED_PLAN_MISSING')
            candidate = rows[0]['bundle']['candidate_script']
            item = next(p for p in candidate['_reviewed_image_inputs']['panels'] if p['idx'] == idx)
            scene = episode_specs(candidate)[idx].model_dump()
        if selected and selected.get('output_hash') != digest:
            raise GenerationHold('VISUAL_SELECTED_PNG_CHANGED')
        matches = [c for c in calls if c.get('panel') == idx and c.get('output_hash') == digest
                   and c.get('fingerprint') == item['fingerprint']
                   and (not candidate_id or str(c.get('quality_candidate_id')) == candidate_id)]
        if len(matches) != 1:
            raise GenerationHold('VISUAL_EXACT_GENERATION_RECEIPT_REQUIRED')
        call = matches[0]
        result.append({'panel_idx': idx, 'output_hash': digest, 'fingerprint': item['fingerprint'],
            'origin_token': str(call['token']), 'origin_revision': call['revision'],
            'candidate_id': candidate_id, 'scene_sha256': payload_hash(scene),
            'scene': scene, 'ref_bindings': item.get('ref_bindings', [])})
    if len(result) != len(specs) or len(images) != len(script['panels']):
        raise GenerationHold('VISUAL_MANIFEST_COVERAGE_REQUIRED')
    return result


def base_manifest_with_origins(script: dict, artifact_run_id: str) -> list[dict]:
    """Read-only export for mixed-run base registration; never infer a missing receipt."""
    from engine.common.supabase_client import icg_table
    if not isinstance(artifact_run_id, str) or not artifact_run_id.isascii() or not artifact_run_id.isdigit():
        raise GenerationHold('VISUAL_CONTAINER_ARTIFACT_REQUIRED')
    scope = f"output/episodes/{script['date']}/panels"
    calls = icg_table('image_generation_calls').select('*').eq('scope', scope).eq('state', 'success').execute().data
    if not isinstance(calls, list) or not calls:
        raise GenerationHold('VISUAL_BASE_RECEIPTS_REQUIRED')
    rows = icg_table('image_generation_attempt_diagnostics').select('token,payload').eq('kind', 'inputs').in_(
        'token', [c['token'] for c in calls]).execute().data
    if not isinstance(rows, list):
        raise GenerationHold('VISUAL_BASE_ORIGINS_REQUIRED')
    origins = {str(r['token']): r['payload'].get('run_id') for r in rows}
    inputs = {p['idx']: p for p in (script.get('_reviewed_image_inputs') or {}).get('panels', [])}
    result = []
    for panel in script['panels']:
        if panel['panel_type'] in {'TEXT_CARD', 'DISCLAIMER'}:
            continue
        matches = [c for c in calls if c['panel'] == panel['idx'] and
                   (panel['idx'] not in inputs or c['fingerprint'] == inputs[panel['idx']]['fingerprint'])]
        if len(matches) != 1:
            raise GenerationHold('VISUAL_BASE_ORIGIN_AMBIGUOUS')
        call = matches[0]
        run = origins.get(str(call['token']))
        if not isinstance(run, str) or not run.isascii() or not run.isdigit():
            raise GenerationHold('VISUAL_BASE_ORIGIN_RUN_REQUIRED')
        result.append({'panel_idx': panel['idx'], 'output_hash': call['output_hash'],
            'artifact_run_id': artifact_run_id, 'artifact_name': 'episode-'+artifact_run_id,
            'artifact_path': f"{script['date']}/panels/P{panel['idx']}.png",
            'origin_run_id': run, 'origin_token': str(call['token']), 'origin_fingerprint': call['fingerprint']})
    return result


def prepare_assembly(script: dict, images: list[Path | None], slides_dir: Path) -> tuple[list[Path], dict]:
    from engine.assembly.mobile_layout import PROFILE, compose_mobile, font_profile
    from engine.assembly.pil_composer import compose_slide, validate_panel_sources
    require_inputs(script)
    validate_panel_sources(script['panels'], images)
    if script['_visual_policy'].get('layout_sha256') != payload_hash(PROFILE):
        raise GenerationHold('VISUAL_LAYOUT_PROFILE_CHANGED')
    effective = source_manifest(script, images)
    report, slides = [], []
    for panel, image in zip(script['panels'], images):
        output = slides_dir / f"S{panel['idx']}.png"
        if panel['panel_type'] not in {'TEXT_CARD', 'DISCLAIMER'}:
            report.append(compose_mobile(panel, image, output))
        else:
            compose_slide(image, panel.get('key_text', ''), panel.get('narration', ''),
                          panel['idx'], panel['panel_type'], panel.get('market_ref'), output, strict=True)
        slides.append(output)
    meta = font_profile()
    prepared = deepcopy(script)
    prepared['_effective_render_manifest'] = effective
    prepared['_mobile_layout_report'] = {'version': 'mobile-layout-report-1', 'panels': report,
        'layout_sha256': meta['layout_sha256'], 'font_sha256': meta['sha256']}
    prepared['_declared_storyboard_report'] = rhythm_report(list(episode_specs(script).values()))
    return slides, prepared


def require_ready(script: dict, slides: list[Path] | None = None, row: dict | None = None) -> None:
    if not policy_present(script, row):
        return
    if slides is not None:
        from engine.publish.manifest import validate_manifest
        validate_manifest(script, slides)
    result = rpc('visual_quality_publication_ready', {'p_script': script})
    if result.get('ready') is not True:
        raise GenerationHold('VISUAL_REVIEW_REQUIRED')


def claim(row: dict, day: str, number: int) -> str:
    require_ready(row['script_json'], row=row)
    result = rpc('claim_visual_publication', {'p_date': day, 'p_episode_no': number,
        'p_expected_version': row.get('updated_at'), 'p_script': row['script_json']})
    token = result.get('token')
    if not isinstance(token, str) or not token.startswith('PUBLISH_HOLD:'):
        raise GenerationHold('VISUAL_PUBLICATION_CLAIM_REQUIRED')
    return token


def require_snapshot(script: dict, token: str, slides: list[Path]) -> None:
    from engine.publish.manifest import validate_manifest
    validate_manifest(script, slides)
    result = rpc('visual_quality_require_snapshot', {'p_date': script['date'], 'p_token': token})
    if result.get('authorized') is not True:
        raise GenerationHold('VISUAL_PUBLICATION_SNAPSHOT_CHANGED')
