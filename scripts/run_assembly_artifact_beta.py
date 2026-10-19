"""Replay a generated episode artifact without database writes or provider calls."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from engine.assembly.pil_composer import compose_episode
from scripts.run_resume import restore_panel_source


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--episode", required=True)
    parser.add_argument("--script", type=Path, required=True)
    args = parser.parse_args()
    episode = args.episode
    if not re.fullmatch(r"ICG-[0-9]{4}-[0-9]{2}-[0-9]{2}-[0-9]{3}", episode):
        raise ValueError("Invalid replay episode identity")
    date = episode[4:14]
    root = Path("output/episodes/episodes") / date
    if not root.is_dir():
        root = Path("output/episodes") / date
    script = json.loads(args.script.read_text())
    manifest = json.loads((root / f"{episode}_images.json").read_text())
    if script["episode_id"] != episode or manifest["episode_id"] != episode:
        raise ValueError("Artifact identity mismatch")
    sources = {p["panel_idx"]: p.get("path") for p in manifest["panels"]}
    expected = {p["idx"] for p in script["panels"]}
    if set(sources) != expected or len(sources) != len(manifest["panels"]):
        raise ValueError("Source image manifest coverage mismatch")
    images = [restore_panel_source(sources[p["idx"]], date) for p in script["panels"]]
    slides = compose_episode(
        script["panels"], images, Path("output/assembly-beta/slides"), strict=True
    )
    from engine.publish.telegram_publisher import _validate_slides

    _validate_slides(slides)
    report = {
        "status": "pass",
        "episode_id": episode,
        "slides": len(slides),
        "database_writes": 0,
        "paid_calls": 0,
        "publishes": 0,
        "source_images_verified": sum(p is not None for p in images),
    }
    Path("output/assembly-beta/report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report))


if __name__ == "__main__":
    main()
