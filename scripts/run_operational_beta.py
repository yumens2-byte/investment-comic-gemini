"""Read-only checks of production configuration and episode metadata.

No generation, publication, claims or database writes are performed.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from engine.publish.claim_guard import PREFIX

REQUIRED_ENV = (
    "SUPABASE_URL", "SUPABASE_KEY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_FREE_CHANNEL_ID",
    "X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_TOKEN_SECRET",
)


def inspect_production(table, environment: dict) -> dict:
    report = {
        "mode": "read_only", "status": "failed",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "missing_configuration": [name for name in REQUIRED_ENV if not environment.get(name)],
        "episodes": [], "database_read": "unverified",
        "unverified": ["provider_auth", "database_claim_write", "actual_image_qc",
                       "new_quality_live_publisher", "live_delivery"],
    }
    if report["missing_configuration"]:
        return report
    try:
        rows = table("episode_assets").select(
            "episode_date,episode_no,status,error_message,script_json,slides_json"
        ).order("episode_date", desc=True).order("episode_no", desc=True).limit(10).execute().data
        history = table("published_comics").select(
            "publish_date,episode_no,status"
        ).order("publish_date", desc=True).limit(20).execute().data
        if not isinstance(rows, list) or not rows or not isinstance(history, list):
            raise ValueError("episode or history metadata unavailable")
        identities = set()
        for row in rows:
            identity = (row["episode_date"], row["episode_no"])
            if identity in identities or not identity[0] or not isinstance(identity[1], int):
                raise ValueError("invalid or duplicate episode identity")
            identities.add(identity)
            script = row.get("script_json")
            if not isinstance(script, dict):
                raise ValueError("episode script missing")
            hold = str(row.get("error_message") or "").startswith(PREFIX)
            found = any(
                h.get("publish_date") == identity[0] and h.get("episode_no") == identity[1]
                and h.get("status") == "published" for h in history
            )
            report["episodes"].append({
                "episode_date": identity[0], "episode_no": identity[1],
                "status": row.get("status"), "publication_hold": hold,
                "quality_track": "_webtoon_quality" in script or "quality_release" in script,
                "slide_metadata_present": bool(row.get("slides_json")),
                "history_in_recent_window": found,
            })
        report["database_read"] = "pass"
        latest = report["episodes"][0]
        report["status"] = "hold" if latest["publication_hold"] else "pass"
    except Exception as exc:
        # Error text from a provider can contain URLs/credentials. Emit its type only.
        report["error_type"] = type(exc).__name__
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("output/operational-beta.json"))
    args = parser.parse_args()
    from engine.common.supabase_client import icg_table

    report = inspect_production(icg_table, dict(os.environ))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
