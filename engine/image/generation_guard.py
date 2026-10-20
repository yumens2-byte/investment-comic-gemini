"""Durable, fail-closed paid image reservations shared across runners."""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath, PureWindowsPath

from engine.common.supabase_client import get_client, get_schema


class GenerationHold(RuntimeError):
    """Requires reconciliation rather than automatic paid regeneration."""


def generation_revision() -> int:
    value = os.environ.get("ICG_GENERATION_REVISION", "1")
    if not value.isascii() or not value.isdigit() or not 1 <= int(value) <= 100:
        raise GenerationHold("generation revision must be 1..100")
    return int(value)


class ProductionGenerationGuard:
    def __init__(self, *, scope: str, panel: int, prompt: str, refs: list[Path], retry_plan_id: str | None = None):
        parts = PurePosixPath(scope.replace('\\', '/')).parts
        if '..' in parts:
            raise GenerationHold('Invalid generation identity')
        # Runner checkout prefixes change; retain the stable output namespace.
        if 'output' in parts:
            scope = '/'.join(parts[parts.index('output'):])
        elif PurePosixPath(scope).is_absolute() or PureWindowsPath(scope).is_absolute():
            raise GenerationHold('Generation scope must have a stable output namespace')
        if not scope or '..' in Path(scope).parts or panel <= 0:
            raise GenerationHold('Invalid generation identity')
        try:
            ref_hashes = [hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in refs]
        except OSError as exc:
            raise GenerationHold('Mandatory reference unavailable') from exc
        self.scope, self.panel = scope, panel
        self.retry_plan_id = retry_plan_id
        self.revision = generation_revision()
        self._ref_hashes = ref_hashes
        self.fingerprint = hashlib.sha256(json.dumps(
            [prompt, ref_hashes], ensure_ascii=False, separators=(',', ':')
        ).encode()).hexdigest()

    def _rpc(self, name: str, params: dict):
        try:
            result = get_client().schema(get_schema()).rpc(name, params).execute().data
            if not isinstance(result, dict):
                raise ValueError('Invalid reservation receipt')
            if result.get('hold'):
                reason = str(result['hold'])
                if reason in {'artifact identity changed', 'revision identity changed'}:
                    reason += (
                        f'; scope={self.scope} panel={self.panel} revision={self.revision}. '
                        'Resume the original inputs/artifact, or use Run Market recovery '
                        'with a new explicit generation_revision and source_artifact_run_id.'
                    )
                raise GenerationHold(reason)
            return result
        except GenerationHold:
            raise
        except Exception as exc:
            raise GenerationHold('Durable generation ledger unavailable') from exc

    def _identity(self):
        return {'p_scope': self.scope, 'p_panel': self.panel,
                'p_fingerprint': self.fingerprint}

    def _independent_v4(self) -> bool:
        from engine.image.provider_outcome import content_isolation_v4_enabled
        return content_isolation_v4_enabled() and self.revision == 1 and not self.retry_plan_id

    def _check_independent_v4(self) -> None:
        if self._independent_v4():
            receipt = self._rpc('image_generation_content_isolation_v4_capability', {})
            if receipt.get('version') != 'image-content-isolation-4':
                raise GenerationHold('Content isolation v4 database contract unavailable; provider not called')

    def reuse(self, output_path: Path) -> bool:
        from engine.image.provider_outcome import outcome_v3_enabled
        if outcome_v3_enabled():
            capability = self._rpc('image_generation_outcome_v3_capability', {})
            if capability.get('version') != 'image-outcome-3':
                raise GenerationHold('Outcome v3 database contract unavailable; provider not called')
        name = ('image_generation_inspect_retry' if self.retry_plan_id else
                'image_generation_inspect' if self.revision == 1 else 'image_generation_inspect_v2')
        params = self._identity()
        if self.retry_plan_id:
            params["p_plan_id"] = self.retry_plan_id
        elif self.revision > 1:
            params['p_revision'] = self.revision
        self._check_independent_v4()
        if self._independent_v4():
            name = 'image_generation_inspect_independent_v4'
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
        name = ('image_generation_reserve_retry' if self.retry_plan_id else
                'image_generation_reserve' if self.revision == 1 else 'image_generation_reserve_v2')
        params = self._identity()
        if self.retry_plan_id:
            params["p_plan_id"] = self.retry_plan_id
        elif self.revision > 1:
            params['p_revision'] = self.revision
        self._check_independent_v4()
        if self._independent_v4():
            name = 'image_generation_reserve_independent_v4'
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
        from engine.image.provider_outcome import outcome_v3_enabled
        if outcome_v3_enabled():
            return self.finish_outcome(token, state=state, actual_cost=actual_cost,
                                       output_hash=output_hash)
        receipt = self._rpc('image_generation_finish', {
            **self._identity(), 'p_token': token, 'p_state': state,
            'p_actual_cost': actual_cost, 'p_output_hash': output_hash,
        })
        if receipt.get('settled') is not True:
            raise GenerationHold('Settlement not confirmed')

    def activate_prompt(self, prompt: str) -> None:
        if not self.retry_plan_id:
            raise GenerationHold("Reviewed retry plan required for changed inputs")
        self.fingerprint = hashlib.sha256(json.dumps(
            [prompt, self._ref_hashes], ensure_ascii=False, separators=(",", ":")
        ).encode()).hexdigest()

    def finish_reviewed(self, token: str, *, state: str, actual_cost: float | None,
                        reason: str | None = None, output_hash: str | None = None):
        if not self.retry_plan_id:
            raise GenerationHold("Reviewed retry ledger required")
        if state not in {"success", "failed", "terminal", "unknown"}:
            raise GenerationHold("Invalid generation outcome")
        if actual_cost is not None and (isinstance(actual_cost, bool)
                or not math.isfinite(actual_cost) or actual_cost < 0):
            raise GenerationHold("Invalid generation cost")
        from engine.image.provider_outcome import outcome_v3_enabled
        if outcome_v3_enabled():
            return self.finish_outcome(token, state=state, actual_cost=actual_cost,
                                       output_hash=output_hash, reason=reason)
        receipt = self._rpc("image_generation_finish_retry", {
            **self._identity(), "p_plan_id": self.retry_plan_id, "p_token": token,
            "p_state": state, "p_actual_cost": actual_cost,
            "p_output_hash": output_hash, "p_reason": reason,
        })
        if receipt.get("settled") is not True:
            raise GenerationHold("Settlement not confirmed")

    def finish_outcome(self, token: str, *, state: str, actual_cost: float | None,
                       output_hash: str | None = None, reason: str | None = None):
        from engine.image.provider_outcome import SettlementReceipt
        receipt = self._rpc("image_generation_finish_outcome_v3", {
            **self._identity(), "p_token": token, "p_state": state,
            "p_actual_cost": actual_cost, "p_output_hash": output_hash,
            "p_reason": reason, "p_plan_id": self.retry_plan_id,
            "p_revision": self.revision,
        })
        self.last_settlement = SettlementReceipt.parse(receipt)
        return self.last_settlement

    def select_retry_variant(self, prompts: tuple[str, ...], suffix: str) -> int:
        receipt = self._rpc('image_generation_retry_cursor', {
            'p_scope': self.scope, 'p_panel': self.panel, 'p_plan_id': self.retry_plan_id,
        })
        used = receipt.get('attempts_used')
        if type(used) is not int or not 0 <= used <= 3:
            raise GenerationHold('Invalid durable retry count')
        self.retry_attempts_used = used
        wanted = receipt.get('fingerprint')
        for i, prompt in enumerate(prompts):
            self.activate_prompt(prompt + suffix)
            if self.fingerprint == wanted:
                return i
        raise GenerationHold('Retry cursor outside reviewed inputs')

    def store_diagnostic(self, kind: str, payload: dict) -> None:
        receipt = self._rpc('image_generation_store_diagnostic', {
            'p_scope': self.scope, 'p_panel': self.panel, 'p_plan_id': self.retry_plan_id,
            'p_kind': kind, 'p_payload': payload,
        })
        if receipt.get('stored') is not True:
            raise GenerationHold('Private diagnostic persistence not confirmed')

    def store_attempt_diagnostic(self, token: str, kind: str, payload: dict) -> None:
        """Preserve exact ordinary inputs/results without requiring a retry plan."""
        receipt = self._rpc('image_generation_store_attempt_diagnostic', {
            **self._identity(), 'p_token': token, 'p_kind': kind, 'p_payload': payload,
        })
        if receipt.get('stored') is not True:
            raise GenerationHold('Private attempt diagnostic persistence not confirmed')
