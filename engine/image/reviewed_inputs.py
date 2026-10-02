"""Use private, reviewed recovery inputs without rebuilding them from live Notion."""
from __future__ import annotations

import hashlib
from pathlib import Path, PurePosixPath

from engine.image.generation_guard import GenerationHold, ProductionGenerationGuard
from engine.image.prompt_builder import PanelPrompt
from engine.image.ref_loader import get_refs_for_panel
from engine.publish.manifest import script_hash


def reviewed_panel_prompts(script: dict, *, performance_specs=None) -> list[PanelPrompt] | None:
    if '_reviewed_image_inputs' not in script:
        return None
    bundle = script['_reviewed_image_inputs']
    revision = script.get('_generation_revision')
    if (not isinstance(bundle, dict) or bundle.get('version') != 'reviewed-image-inputs-1'
            or bundle.get('script_hash') != script_hash(script)
            or bundle.get('model') != 'gemini-2.5-flash-image'
            or bundle.get('aspect_ratio') is not None
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
            prompt=prompt + '\n[model=gemini-2.5-flash-image;aspect=None]', refs=refs)
        if guard.revision != revision or guard.fingerprint != item.get('fingerprint'):
            raise GenerationHold('Reviewed provider identity changed')
        results.append(PanelPrompt(idx, ids, prompt, refs))
    return results
