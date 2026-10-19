"""Download only registered, selected Actions artifacts for explicit reassembly."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
from pathlib import Path

from engine.image.generation_guard import GenerationHold
from engine.image.quality_candidates import load_selection


def download(episode_date: str, version: int, root: Path) -> None:
    marker = load_selection(episode_date, version)
    repo = os.environ["GITHUB_REPOSITORY"]
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
        raise GenerationHold("Invalid Actions repository")
    sources = {(str(m["artifact_run_id"]), m["artifact_name"]) for m in marker["manifest"]}
    for run_id, name in sorted(sources):
        if not re.fullmatch(r"[0-9]+", run_id) or not re.fullmatch(
            r"(episode-[0-9]+|image-quality-[a-f0-9-]{36})", name
        ):
            raise GenerationHold("Invalid selected artifact identity")
        dest = root / run_id / name
        dest.mkdir(parents=True, exist_ok=False)
        subprocess.run(
            ["gh", "run", "download", run_id, "--repo", repo, "--name", name, "--dir", str(dest)],
            check=True,
        )


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--date", required=True)
    p.add_argument("--version", type=int, required=True)
    p.add_argument("--root", type=Path, required=True)
    a = p.parse_args()
    download(a.date, a.version, a.root)
