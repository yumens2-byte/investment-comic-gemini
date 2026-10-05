"""Panel image prompt for Zero Block side panels (P1 §3). Pure: config in, text out."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sidestory.core.script import SidePanel

ANTI_HERO_ID = "CHAR_ANTI_HERO_001"

STYLE_BLOCK = (
    "STYLE: 2D digital comic panel, bold black ink outlines, cel shading, dark neon "
    "cyber-city palette (deep purple, neon blue, cyber green, cyan white), high contrast, "
    "cinematic manhwa composition, single scene, no panel borders."
)
NEGATIVE_BLOCK = (
    "NEGATIVE: no text, no letters, no numbers, no captions, no speech bubbles, no logos, "
    "no watermarks, no real people, no celebrities, no brand marks, no gold color, no red color, "
    "no visible face under the hood, no superheroes, no villains, no other named characters, "
    "no human crowds in focus, no photorealism, no letterbox, no black bars, full-bleed image."
)


@dataclass(frozen=True)
class PanelImageSpec:
    idx: int
    prompt: str
    pose: str
    ref_path: str | None   # repo-relative REF path, None = no Zero Block REF


def _zero_block(characters: dict[str, Any]) -> dict[str, Any]:
    try:
        return characters["anti_heroes"][ANTI_HERO_ID]
    except (KeyError, TypeError) as exc:
        raise ValueError(f"{ANTI_HERO_ID} missing in characters_side.yaml") from exc


def _silhouette_text(characters: dict[str, Any], keys: list[str]) -> list[str]:
    table = {n["key"]: n["silhouette"] for n in characters.get("nodes") or []}
    missing = [k for k in keys if k not in table]
    if missing:
        raise ValueError(f"unknown silhouette keys: {missing}")
    return [table[k] for k in keys]


def build_panel_spec(panel: SidePanel, characters: dict[str, Any]) -> PanelImageSpec:
    zb = _zero_block(characters)
    lines = [STYLE_BLOCK, f"SCENE: {panel.setting.strip()}", f"ACTION: {panel.action.strip()}"]
    if panel.camera:
        lines.append(f"CAMERA: {panel.camera.strip()}")
    ref_path = None
    if panel.zero_block_pose != "none":
        ref = (zb.get("refs") or {}).get(panel.zero_block_pose) or {}
        ref_path = ref.get("path")
        if not ref_path:
            raise ValueError(f"no REF registered for pose {panel.zero_block_pose}")
        lock = "; ".join(zb.get("visual_lock") or [])
        lines.append(
            f"CHARACTER: {zb['name']} ({panel.zero_block_pose} pose), match the attached "
            f"reference image exactly. IDENTITY LOCK: {lock}. {zb.get('gdl', '')} "
            "No other people or figures besides Zero Block and the background figures listed "
            "below, if any.")
    else:
        lines.append("CHARACTER: none (environment only). No people or figures anywhere except "
                     "the background figures listed below, if any.")
    silhouettes = _silhouette_text(characters, panel.silhouettes)
    if silhouettes:
        lines.append("BACKGROUND FIGURES (unnamed, silhouette only, no details, no faces): "
                     + "; ".join(silhouettes))
    lines.append(NEGATIVE_BLOCK)
    return PanelImageSpec(idx=panel.idx, prompt="\n".join(lines),
                          pose=panel.zero_block_pose, ref_path=ref_path)


def registered_refs(characters: dict[str, Any], poses: set[str]) -> list[tuple[str, str, str]]:
    """[(pose, path, registered sha256)] for the poses used by a script."""
    refs = _zero_block(characters).get("refs") or {}
    out = []
    for pose in sorted(poses - {"none"}):
        entry = refs.get(pose) or {}
        out.append((pose, str(entry.get("path") or ""), str(entry.get("sha256") or "")))
    return out
