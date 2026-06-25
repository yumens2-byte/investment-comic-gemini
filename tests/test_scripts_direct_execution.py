from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

DIRECT_HELP_SCRIPTS = [
    "scripts/check_major_event_gate.py",
    "scripts/generate_ref_images.py",
    "scripts/resolve_episode.py",
    "scripts/run_market.py",
    "scripts/run_publish.py",
    "scripts/run_resume.py",
    "scripts/run_video_trailer.py",
]


def test_operational_scripts_support_direct_file_execution_help() -> None:
    """Operational scripts must work as `python scripts/name.py`, not only `-m`."""
    for script in DIRECT_HELP_SCRIPTS:
        proc = subprocess.run(
            [sys.executable, script, "--help"],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

        assert proc.returncode == 0, f"{script} failed\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
        assert "ModuleNotFoundError" not in proc.stderr
