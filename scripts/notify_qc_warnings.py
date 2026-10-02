"""Send one advisory Telegram summary without changing the pipeline result."""
from __future__ import annotations

import html
import json
import os
from pathlib import Path

from scripts.notify_failure import _send_telegram


def main() -> int:
    if os.environ.get("DRY_RUN", "false").strip().lower() == "true":
        return 0
    run_id = os.environ.get("GITHUB_RUN_ID", "local")
    findings = []
    try:
        journal = Path("output/qc_warnings.jsonl")
        for line in (journal.read_text(encoding="utf-8").splitlines() if journal.exists() else []):
            row = json.loads(line)
            if row.get("run_id") == run_id:
                item = f"{row['gate']}: {row['message']}"
                if item not in findings:
                    findings.append(item)
        preflight = Path("output/publish-preflight.json")
        if preflight.is_file():
            report = json.loads(preflight.read_text(encoding="utf-8"))
            if report.get("mode") == "live_preflight" and report.get("run_id") == run_id:
                for finding in report.get("qc_warnings", []):
                    item = f"publish_preflight: {finding}"
                    if item not in findings:
                        findings.append(item)
    except FileNotFoundError:
        return 0
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        print("[QC_WARNING] Could not read warning journal; see execution log")
        return 0
    if not findings:
        return 0
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    channel = os.environ.get("TELEGRAM_FREE_CHANNEL_ID")
    if not token or not channel:
        print("[QC_WARNING] Telegram configuration absent; see execution log")
        return 0
    # Bound plain text before HTML escaping; never include prompts or credentials.
    # HTML entities can expand one character sixfold; stay below Telegram's limit.
    details = "\n".join(findings[:8])[:500]
    workflow = html.escape(os.environ.get("GITHUB_WORKFLOW", "ICG")[:80])
    repo = os.environ.get("GITHUB_REPOSITORY", "yumens2-byte/investment-comic-gemini")
    url = html.escape(f"https://github.com/{repo}/actions/runs/{run_id}", quote=True)
    message = (f"⚠️ <b>ICG QC 경고 — 작업 계속 진행</b>\n{workflow}\n"
               f"QC 경고 {len(findings)}건\n{html.escape(details)}\n"
               f"<a href='{url}'>Actions 로그 확인</a>\n"
               "QC 경고는 중단 사유가 아닙니다. 실제 수행 결과는 로그에서 확인하세요.")
    _send_telegram(token, channel, message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
