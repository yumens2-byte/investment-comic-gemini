"""DR-5: a change set that touches sidestory must not touch main paths.

Usage: python -m sidestory.tests.diff_guard <base-ref>
"""
from __future__ import annotations

import subprocess
import sys

SIDE_PREFIXES = ("sidestory/", ".github/workflows/sidestory_")


def violations(changed: list[str]) -> list[str]:
    side = [p for p in changed if p.startswith(SIDE_PREFIXES)]
    if not side:
        return []
    return sorted(p for p in changed if not p.startswith(SIDE_PREFIXES))


def main(argv: list[str]) -> int:
    base = argv[1] if len(argv) > 1 else "origin/main"
    out = subprocess.run(
        ["git", "diff", "--name-only", f"{base}...HEAD"],
        check=True, capture_output=True, text=True,
    ).stdout
    bad = violations([line.strip() for line in out.splitlines() if line.strip()])
    if bad:
        print("DR-5 FAIL — sidestory change set also modifies main paths:")
        print("\n".join(f"  {p}" for p in bad))
        return 1
    print("DR-5 PASS — main paths untouched")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
