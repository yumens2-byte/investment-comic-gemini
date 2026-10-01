"""Durable, fail-closed paid image reservations shared across runners."""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path

from engine.common.supabase_client import get_client, get_schema


class GenerationHold(RuntimeError):
    """Requires reconciliation rather than automatic paid regeneration."""


def generation_revision() -> int:
    value = os.environ.get("ICG_GENERATION_REVISION", "1")
    if not value.isascii() or not value.isdigit() or not 1 <= int(value) <= 100:
        raise GenerationHold("generation revision must be 1..100")
    return int(value)


class ProductionGenerationGuard:
    def __init__(self, *, scope: str, panel: int, prompt: str, refs: list[Path]):
        parts = Path(scope).parts
        if '..' in parts:
            raise GenerationHold('Invalid generation identity')
        # Runner checkout prefixes change; retain the stable output namespace.
        if 'output' in parts:
            scope = '/'.join(parts[parts.index('output'):])
        elif Path(scope).is_absolute():
            raise GenerationHold('Generation scope must have a stable output namespace')
        if not scope or '..' in Path(scope).parts or panel <= 0:
            raise GenerationHold('Invalid generation identity')
        try:
            ref_hashes = [hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in refs]
        except OSError as exc:
            raise GenerationHold('Mandatory reference unavailable') from exc
        self.scope, self.panel = scope, panel
        self.revision = generation_revision()
        self.fingerprint = hashlib.sha256(json.dumps(
            [prompt, ref_hashes], ensure_ascii=False, separators=(',', ':')
        ).encode()).hexdigest()

    def _rpc(self, name: str, params: dict):
        try:
            result = get_client().schema(get_schema()).rpc(name, params).execute().data
            if not isinstance(result, dict):
                raise ValueError('Invalid reservation receipt')
            if result.get('hold'):
                raise GenerationHold(str(result['hold']))
            return result
        except GenerationHold:
            raise
        except Exception as exc:
            raise GenerationHold('Durable generation ledger unavailable') from exc

    def _identity(self):
        return {'p_scope': self.scope, 'p_panel': self.panel,
                'p_fingerprint': self.fingerprint}

    def reuse(self, output_path: Path) -> bool:
        name = 'image_generation_inspect' if self.revision == 1 else 'image_generation_inspect_v2'
        params = self._identity()
        if self.revision > 1:
            params['p_revision'] = self.revision
        receipt = self._rpc(name, params)
        digest = receipt.get('output_hash')
        if digest:
            try:
                actual = hashlib.sha256(output_path.read_bytes()).hexdigest()
            except OSError as exc:
                raise GenerationHold('Restore successful artifact; do not regenerate') from exc
            if actual != digest:
                raise GenerationHold('Successful artifact hash mismatch')
            return True
        if output_path.exists():
            if self.revision > 1:
                digest = hashlib.sha256(output_path.read_bytes()).hexdigest()
                if digest in receipt.get('prior_hashes', []):
                    archive = output_path.parent / 'previous-revisions'
                    archive.mkdir(exist_ok=True)
                    output_path.replace(archive / f'P{self.panel}-{digest}.png')
                    return False
            raise GenerationHold('Unreceipted image requires reconciliation')
        return False

    def reserve(self) -> str:
        name = 'image_generation_reserve' if self.revision == 1 else 'image_generation_reserve_v2'
        params = self._identity()
        if self.revision > 1:
            params['p_revision'] = self.revision
        receipt = self._rpc(name, params)
        token = receipt.get('token')
        if not isinstance(token, str) or not token:
            raise GenerationHold('Missing reservation token')
        return token

    def finish(self, token: str, *, state: str, actual_cost: float | None,
               output_hash: str | None = None):
        if state not in {'success', 'failed', 'terminal', 'unknown'}:
            raise GenerationHold('Invalid generation outcome')
        if actual_cost is not None and (isinstance(actual_cost, bool)
                                       or not math.isfinite(actual_cost) or actual_cost < 0):
            raise GenerationHold('Invalid generation cost; reservation remains held')
        receipt = self._rpc('image_generation_finish', {
            **self._identity(), 'p_token': token, 'p_state': state,
            'p_actual_cost': actual_cost, 'p_output_hash': output_hash,
        })
        if receipt.get('settled') is not True:
            raise GenerationHold('Settlement not confirmed')
