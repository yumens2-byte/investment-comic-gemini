"""Block scheduled publication when publish-path code changed since the last confirmed post.

The first live publication after such a change must be a manual, attended dispatch
(confirm=YES). Missing evidence (no recorded commit, unreadable history) also blocks.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys

GUARDED_PATHS = (
    "engine/publish/",
    "scripts/run_publish.py",
    "scripts/publish_preflight.py",
    "docs/sql/narrative-publication-state.sql",
)
_SHA = re.compile(r"^[0-9a-f]{40}$")


def schedule_publish_allowed(last_sha: str | None, changed_files: list[str] | None
                             ) -> tuple[bool, str]:
    if not last_sha or not _SHA.match(last_sha):
        return False, "no_recorded_publication_commit"
    if changed_files is None:
        return False, "commit_history_unavailable"
    touched = sorted(f for f in changed_files if f.startswith(GUARDED_PATHS))
    if touched:
        return False, "publish_code_changed:" + ",".join(touched[:5])
    return True, "unchanged_since:" + last_sha[:12]


def last_publication_sha() -> str | None:
    from engine.common.supabase_client import icg_table

    rows = (icg_table("published_comics").select("code_sha,created_at")
            .not_.is_("code_sha", "null").order("created_at", desc=True).limit(1)
            .execute().data)
    return rows[0].get("code_sha") if isinstance(rows, list) and rows else None


def changed_since(sha: str) -> list[str] | None:
    head = os.environ.get("GITHUB_SHA", "HEAD")
    result = subprocess.run(["git", "diff", "--name-only", f"{sha}..{head}"],
                            capture_output=True, text=True, check=False)
    if result.returncode != 0:
        return None
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def main() -> int:
    try:
        sha = last_publication_sha()
    except Exception as exc:
        print(f"[publish_code_guard] history lookup failed: {type(exc).__name__}")
        sha = None
    allowed, reason = schedule_publish_allowed(sha, changed_since(sha) if sha else None)
    print(f"[publish_code_guard] allowed={allowed} reason={reason}")
    if not allowed:
        print("❌ Scheduled publication blocked: run Publish SNS manually with confirm=YES.")
    return 0 if allowed else 1


if __name__ == "__main__":
    sys.exit(main())
