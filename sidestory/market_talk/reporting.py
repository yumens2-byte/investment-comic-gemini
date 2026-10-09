"""Allowlisted GitHub summaries; never render raw exception or model text."""

import json
import os
import re
from pathlib import Path


def summary(report):
    lines = ["### Market Talk result", ""]
    for key in ("status", "phase", "slot_date", "revision", "run_id"):
        value = str(report.get(key, ""))
        if value and re.fullmatch(r"[A-Za-z0-9:_-]{1,120}", value):
            lines.append(f"- {key}: `{value}`")
    for code in report.get("blockers", []):
        if isinstance(code, str) and re.fullmatch(r"[A-Z0-9_]{2,100}", code):
            lines.append(f"- blocker: `{code}`")
    lines.append(f"- verified: `{report.get('verified') is True}`")
    return "\n".join(lines) + "\n"


def main():
    path = Path("output/market-talk-report.json")
    report = json.loads(path.read_text()) if path.is_file() else {"status": "REPORT_MISSING"}
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as output:
            output.write(summary(report))
    if report.get("status") in {
        "BLOCKED",
        "POSTED_UNVERIFIED",
        "PUBLISHED_REPORT_PENDING",
        "WATCH_ALERT",
        "REPORT_MISSING",
        "SKIPPED_OUTSIDE_WINDOW",
    }:
        print("::warning::Market Talk needs operator review; see the safe report artifact.")


if __name__ == "__main__":
    main()
