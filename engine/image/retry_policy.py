"""Bounded retry policy. Reviewed variants never relax provider safety settings."""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path

from engine.image.generation_guard import GenerationHold

CONTENT_REASONS = frozenset({'PROHIBITED_CONTENT', 'SAFETY', 'IMAGE_SAFETY'})
REVIEW_REASONS = frozenset({'BLOCKLIST', 'RECITATION', 'IMAGE_RECITATION', 'SPII',
                           'IMAGE_PROHIBITED_CONTENT', 'ESCALATION', 'PUP_LIMITED_DISABLED'})


def normalized_reason(reason: object) -> str:
    return str(getattr(reason, 'name', reason)).rsplit('.', 1)[-1].upper()


def retry_enabled() -> bool:
    value = os.environ.get('ICG_IMAGE_RETRY_V2_ENABLED', 'false').lower()
    if value not in {'true', 'false'}:
        raise GenerationHold('Invalid image retry feature flag')
    return value == 'true'


def max_retries() -> int:
    value = os.environ.get('ICG_IMAGE_MAX_RETRIES', '2')
    if value not in {'0', '1', '2'}:
        raise GenerationHold('Image max retries must be 0..2')
    return int(value)


@dataclass(frozen=True)
class ReviewedRetryPlan:
    plan_id: str
    prompts: tuple[str, ...]

    @classmethod
    def from_bundle(cls, bundle: dict, original: str, refs: list[Path]):
        if not isinstance(bundle, dict) or bundle.get('version') != 'image-retry-plan-1':
            raise GenerationHold('Reviewed retry plan required')
        plan_id, prompts = bundle.get('plan_id'), bundle.get('prompts')
        if (not isinstance(plan_id, str) or len(plan_id) != 64
                or any(c not in '0123456789abcdef' for c in plan_id)
                or not isinstance(prompts, list) or not 1 <= len(prompts) <= 3
                or any(not isinstance(p, str) or not p.strip() for p in prompts)
                or prompts[0] != original or len(set(prompts)) != len(prompts)):
            raise GenerationHold('Invalid reviewed retry variants')
        ref_hashes = [hashlib.sha256(p.read_bytes()).hexdigest() for p in refs]
        if bundle.get('ref_sha256') != ref_hashes:
            raise GenerationHold('Reviewed retry references changed')
        content = {'version': bundle['version'], 'prompts': prompts, 'ref_sha256': ref_hashes}
        digest = hashlib.sha256(json.dumps(content, ensure_ascii=False,
                               sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        if digest != plan_id:
            raise GenerationHold('Reviewed retry plan hash changed')
        return cls(plan_id, tuple(prompts))


def retry_delay(retry_no: int) -> float:
    # Caller injects sleep in tests. No hidden SDK retries.
    import random
    return (5 if retry_no == 1 else 15) + random.uniform(0, 2)
