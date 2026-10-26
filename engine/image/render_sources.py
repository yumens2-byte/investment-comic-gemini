"""Explicit appearance/technique projections for newly built v2 prompts only."""
from __future__ import annotations

import re

from engine.image.scene_performance import payload_hash, text_hash


def project_sources(canon: str, style: str) -> tuple[str, str, dict]:
    """Remove named non-appearance roles, recording exclusions instead of rewriting canon.

    Unknown or mixed instructions remain in the projection and are checked by the
    renderer. This is not a catch-all natural-language sanitizer.
    """
    exclusions = []
    projected = {}
    for role, source in [('canon', canon), ('style', style)]:
        lines = []
        for line in source.splitlines():
            reason = None
            if re.match(r'^\s*(?:Role:|Signature Action:|Entrance Cue:|Panel Rules:|Market Metaphor:|Identity:)', line, re.I):
                reason = 'STORY_OR_PLACEMENT_OWNED_BY_SCENE'
            elif re.match(r'^\s*Identifier\b', line, re.I):
                reason = 'REFERENCE_GLYPHS_EXCLUDED'
            elif role == 'style' and re.match(r'^\s*(?:POSE|DYNAMIC ACTION|COMPOSITION|CAMERA)(?:\s+RULE)?\s*:', line, re.I):
                reason = 'CAMERA_OR_MOTION_OWNED_BY_SCENE'
            elif role == 'style' and re.fullmatch(r'\s*Bodies angled toward (?:the )?center contact point[.]?\s*', line, re.I):
                reason = 'CONTACT_STAGING_EXCLUDED'
            if reason:
                exclusions.append({'role': role, 'source_line_sha256': text_hash(line), 'reason': reason})
            else:
                lines.append(line)
        projected[role] = '\n'.join(lines)
    report = {'version': 'render-source-projection-1',
        'source_sha256': {'canon': text_hash(canon), 'style': text_hash(style)},
        'projection_sha256': payload_hash(projected), 'exclusions': exclusions}
    return projected['canon'], projected['style'], report
