"""refgen: one-off Zero Block REF generation through the API path (F3, pilot 1).

Why: REFs made in the Gemini app carry a visible watermark that the panel model reproduced
(pilot 1, S6). The API path is the same one the panels use. Output is NOT committed
automatically: the master reviews the artifact, then the files + sha256 go to the repo.

Order: front from its prompt alone (no watermarked image as input), then side/back/attack/
defense with the new front attached so identity stays consistent.
Ledger scope: output/sidestory/refs/r<N>/panels (icg_side migration 0002), panel = pose order.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sidestory.ports.image import ImageGenerator, ImageHold
from sidestory.ports.llm import LLMError, RefPromptSource
from sidestory.ports.store import SideStore

POSE_ORDER = ("front", "side", "back", "attack", "defense")
REF_ASPECT = "2:3"
MAX_REVISION = 999


@dataclass
class RefgenResult:
    revision: int
    status: str                                   # "ok" | "hold" | "error"
    files: dict[str, dict[str, Any]] = field(default_factory=dict)
    detail: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"stage": "refgen", "revision": self.revision, "status": self.status,
                "files": self.files, "detail": self.detail}


def refs_dir(output_root: Path, revision: int) -> Path:
    return output_root / "refs" / f"r{revision}"


def yaml_snippet(files: dict[str, dict[str, Any]]) -> str:
    lines = []
    for pose in POSE_ORDER:
        f = files[pose]
        path = f"sidestory/assets/refs/zero_block_{pose}.png"
        lines.append(f'      {pose + ":":<8} {{path: {path},'
                     f'{" " * (7 - len(pose))} sha256: "{f["sha256"]}"}}')
    return "\n".join(lines)


def run_refgen(revision: int, *, images: ImageGenerator, prompts: RefPromptSource,
               store: SideStore | None, output_root: Path = Path("output/sidestory")
               ) -> RefgenResult:
    result = RefgenResult(revision=revision, status="error")
    if not 1 <= revision <= MAX_REVISION:
        result.detail["reason"] = f"revision must be 1..{MAX_REVISION}"
        return result
    try:
        texts = prompts.ref_prompts()
    except LLMError as exc:
        result.detail["reason"] = f"REF prompts unavailable: {exc}"
        return result
    base = refs_dir(output_root, revision)
    panels_dir = base / "panels"
    total = 0.0
    front: Path | None = None
    for idx, pose in enumerate(POSE_ORDER, start=1):
        refs = [front] if front is not None else []
        try:
            path, cost = images.generate(idx, texts[pose], refs, panels_dir,
                                         aspect_ratio=REF_ASPECT)
        except ImageHold as exc:
            result.status = "hold"
            result.detail.update(reason=f"{pose}: {exc}", cost_usd=round(total, 4))
            break
        total += cost
        named = base / f"zero_block_{pose}.png"
        shutil.copyfile(path, named)
        if pose == "front":
            front = named
        result.files[pose] = {"path": named.as_posix(),
                              "sha256": hashlib.sha256(named.read_bytes()).hexdigest(),
                              "cost_usd": round(cost, 4)}
    else:
        result.status = "ok"
        result.detail["cost_usd"] = round(total, 4)
        result.detail["characters_side_yaml_refs"] = yaml_snippet(result.files)
        (base / "refs.json").write_text(json.dumps(result.files, indent=2), encoding="utf-8")
    if store is not None:
        store.log("refgen", result.status, {"revision": revision, **{
            k: v for k, v in result.detail.items() if k != "characters_side_yaml_refs"},
            "sha256": {p: f["sha256"] for p, f in result.files.items()}})
    return result
