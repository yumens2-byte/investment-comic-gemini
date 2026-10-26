"""Use private, reviewed recovery inputs without rebuilding them from live Notion."""
from __future__ import annotations

import hashlib
from pathlib import Path, PurePosixPath

from engine.image.generation_guard import GenerationHold, ProductionGenerationGuard
from engine.image.prompt_builder import PanelPrompt
from engine.image.ref_loader import get_refs_for_panel
from engine.publish.manifest import script_hash


def reviewed_panel_prompts(script: dict, *, performance_specs=None) -> list[PanelPrompt] | None:
    from engine.image.scene_contract import validate_scene_contracts, validate_scene_text
    contracts = validate_scene_contracts(script)
    if '_reviewed_image_inputs' not in script:
        return None
    bundle = script['_reviewed_image_inputs']
    revision = script.get('_generation_revision')
    from engine.image.scene_performance import episode_specs, payload_hash
    dynamic = episode_specs(script)
    v2 = isinstance(bundle, dict) and bundle.get('version') == 'reviewed-image-inputs-2'
    aspect = '4:5' if v2 else None
    if (not isinstance(bundle, dict) or bundle.get('version') not in {'reviewed-image-inputs-1', 'reviewed-image-inputs-2'}
            or bundle.get('script_hash') != script_hash(script)
            or bundle.get('model') != 'gemini-2.5-flash-image'
            or bundle.get('aspect_ratio') != aspect
            or bool(dynamic) != v2
            or type(revision) is not int or revision < 2 or performance_specs is not None):
        raise GenerationHold('Reviewed image configuration changed')
    scenes = script.get('panels')
    items = bundle.get('panels')
    if not isinstance(scenes, list) or not isinstance(items, list):
        raise GenerationHold('Malformed reviewed image inputs')
    if any(not isinstance(p, dict) or type(p.get('idx')) is not int for p in scenes):
        raise GenerationHold('Malformed reviewed panel indices')
    if [p['idx'] for p in scenes] != list(range(1, len(scenes) + 1)):
        raise GenerationHold('Reviewed panel indices must be contiguous')
    by_idx = {}
    for item in items:
        if (not isinstance(item, dict) or type(item.get('idx')) is not int
                or item['idx'] in by_idx):
            raise GenerationHold('Duplicate or invalid reviewed input')
        by_idx[item['idx']] = item
    required = {p['idx'] for p in scenes if p.get('panel_type') not in {'TEXT_CARD', 'DISCLAIMER'}}
    if set(by_idx) != required:
        raise GenerationHold('Reviewed inputs must cover every paid scene only')
    results = []
    for panel in scenes:
        idx = panel['idx']
        ids = [c.get('char_id', '') for c in panel.get('characters', [])]
        if idx not in required:
            if ids:
                raise GenerationHold('Character cast on compositor panel')
            results.append(PanelPrompt(idx, [], '', []))
            continue
        item = by_idx[idx]
        prompt, names, hashes = (item.get('prompt_text'), item.get('refs'), item.get('ref_sha256'))
        if (not isinstance(prompt, str) or not prompt.strip() or not isinstance(names, list)
                or not isinstance(hashes, list) or len(names) != len(hashes)):
            raise GenerationHold('Malformed reviewed prompt or references')
        if v2 and item.get('scene_sha256') != payload_hash(dynamic[idx].model_dump()):
            raise GenerationHold('Reviewed performance changed')
        if item.get('reuse_only') is not None and item.get('reuse_only') is not True:
            raise GenerationHold('Invalid reuse-only input')
        if item.get('reuse_only') is True and contracts.get(str(idx), {}).get('version') != 'reuse-only-scene-1':
            raise GenerationHold('Reuse-only input requires a preserved scene contract')
        if str(idx) in contracts and not item.get('reuse_only'):
            if panel.get('action', '') not in prompt or panel.get('setting', '') not in prompt:
                raise GenerationHold('Reviewed prompt differs from scene contract')
            validate_scene_text(prompt, idx)
        for name in names:
            if (not isinstance(name, str) or '\\' in name or
                    PurePosixPath(name).is_absolute() or '..' in PurePosixPath(name).parts
                    or not name.startswith('assets/characters/')):
                raise GenerationHold('Reviewed reference path outside canon assets')
        refs = [Path(name) for name in names]
        if refs != get_refs_for_panel(ids):
            raise GenerationHold('Reviewed references differ from canon cast')
        try:
            actual = [hashlib.sha256(ref.read_bytes()).hexdigest() for ref in refs]
        except OSError as exc:
            raise GenerationHold('Reviewed reference unavailable') from exc
        if actual != hashes:
            raise GenerationHold('Reviewed reference bytes changed')
        guard = ProductionGenerationGuard(
            scope=f"output/episodes/{script.get('date')}/panels", panel=idx,
            prompt=prompt + f'\n[model=gemini-2.5-flash-image;aspect={aspect}]', refs=refs)
        if guard.revision != revision or guard.fingerprint != item.get('fingerprint'):
            raise GenerationHold('Reviewed provider identity changed')
        results.append(PanelPrompt(idx, ids, prompt, refs))
    return results
