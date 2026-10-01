"""Restore only the selected day's original panels, never an archived script."""
import argparse
import shutil
from datetime import date
from pathlib import Path


def restore(episode_date: str, source: Path, target: Path) -> int:
    if date.fromisoformat(episode_date).isoformat() != episode_date:
        raise ValueError("invalid episode date")
    restored = 0
    for directory in (source / episode_date / "panels", source / "episodes" / episode_date / "panels"):
        if not directory.is_dir():
            continue
        for panel in directory.glob("P*.png"):
            if not panel.stem[1:].isdigit():
                continue
            destination = target / episode_date / "panels" / panel.name
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists() and destination.read_bytes() != panel.read_bytes():
                raise ValueError("conflicting recovery panel")
            shutil.copyfile(panel, destination)
            restored += 1
    if not restored:
        raise ValueError("no panels for selected episode date")
    return restored


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True)
    args = parser.parse_args()
    print(restore(args.date, Path("output/recovery-source"), Path("output/episodes")))
