"""Publish-time reference verification; legacy development waivers do not apply."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from pydantic import Field

from engine.quality.contracts import QualityHold, StrictModel


class CanonEntry(StrictModel):
    char_id: str
    form: str
    ref_path: str
    ref_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    required_props: tuple[str, ...]
    hand_rules: tuple[str, ...]
    direction_rules: tuple[str, ...]
    forbidden: tuple[str, ...]
    approval_id: str = Field(min_length=1)


class CanonManifest(StrictModel):
    registry_version: str = Field(min_length=1)
    approved_by: str = Field(min_length=1)
    entries: tuple[CanonEntry, ...] = Field(min_length=1)


def safe_asset(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    if Path(relative).is_absolute() or not path.is_relative_to(root.resolve()):
        raise QualityHold("asset path escapes artifact root")
    if not path.is_file():
        raise QualityHold(f"asset missing: {relative}")
    return path


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_manifest(manifest: CanonManifest, script: dict, root: Path) -> None:
    entries = {(e.char_id, e.form): e for e in manifest.entries}
    if len(entries) != len(manifest.entries):
        raise QualityHold("duplicate approved canon entry")
    for entry in manifest.entries:
        if not re.fullmatch(r"[a-f0-9]{64}", entry.ref_sha256):
            raise QualityHold("unverified canon hash")
        if file_hash(safe_asset(root, entry.ref_path)) != entry.ref_sha256:
            raise QualityHold(f"REF hash mismatch: {entry.char_id}")
    for panel in script.get("panels", []):
        cast = panel.get("characters", [])
        ids = [c["char_id"] for c in cast]
        if len(ids) != len(set(ids)):
            raise QualityHold("duplicate character in panel")
        for c in cast:
            # Explicit form required. Never silently substitute form1.
            if (c["char_id"], c.get("form")) not in entries:
                raise QualityHold(f"unapproved character/form: {c['char_id']}")


def repair_prompt(original: str, required_cast: tuple[str, ...], findings: list[str]) -> str:
    if not required_cast or not original.strip():
        raise QualityHold("repair needs an original prompt and required cast")
    feedback = "\n".join(s.replace("<", "\\u003c")[:400] for s in findings[:8])
    return (
        "REPAIR CONTRACT: Preserve every required character, reference, prop, hand, "
        "direction and fixed outcome. Simplify OPTIONAL background/effects only.\n"
        f"Required cast: {', '.join(required_cast)}\n"
        f"<repair_findings>{feedback}</repair_findings>\n{original}"
    )
