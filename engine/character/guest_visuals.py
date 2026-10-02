"""Text-only guest appearance contracts grounded in the existing design document."""
from pathlib import Path

import yaml

from engine.common.exceptions import PipelineAborted

_PATH = Path(__file__).resolve().parents[2] / "config/guest_visuals.yaml"


def guest_visual_spec(char_id: str) -> dict:
    from engine.image.ref_loader import GUEST_CHARACTER_IDS

    if char_id not in GUEST_CHARACTER_IDS:
        raise PipelineAborted("prompt", f"Unregistered guest: {char_id}")
    try:
        document = yaml.safe_load(_PATH.read_text(encoding="utf-8"))
        spec = document["characters"][char_id]
        if (document.get("version") != "guest-visuals-1"
                or not document.get("source")
                or not isinstance(spec, dict)
                or any(not isinstance(spec.get(k), str) or not spec[k].strip()
                       for k in ("name", "body", "strict"))):
            raise ValueError("incomplete guest appearance")
    except (OSError, KeyError, TypeError, ValueError, yaml.YAMLError) as exc:
        raise PipelineAborted("prompt", f"Missing guest visual contract: {char_id}") from exc
    return spec


def guest_visual_block(char_ids: list[str]) -> str:
    from engine.common.notion_loader import char_design_to_prompt_block

    return "\n\n".join(char_design_to_prompt_block(c, guest_visual_spec(c))
                       for c in dict.fromkeys(char_ids))
