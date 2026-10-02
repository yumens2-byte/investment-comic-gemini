"""
scripts/notify_failure.py
GitHub Actions 파이프라인 실패 시 마스터 Telegram 알림 발송.

호출 방식:
  python -m scripts.notify_failure
  (GitHub Actions의 `if: failure()` step에서 호출)

환경변수:
  TELEGRAM_BOT_TOKEN — 봇 토큰
  TELEGRAM_FREE_CHANNEL_ID — 알림 수신 채널 ID
  GITHUB_RUN_ID — Actions run ID (GitHub 자동 주입)
  GITHUB_WORKFLOW — 워크플로우 이름 (GitHub 자동 주입)
  GITHUB_REPOSITORY — 레포 이름 (GitHub 자동 주입)
"""

from __future__ import annotations

import argparse
import html
import json
import os
import sys
from pathlib import Path

import requests


def _send_telegram(token: str, channel_id: str, text: str) -> bool:
    """Telegram Bot API sendMessage 호출."""
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": channel_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    try:
        resp = requests.post(url, json=payload, timeout=10)
        resp.raise_for_status()
        return True
    except Exception as exc:
        print(f"[notify_failure] Telegram 전송 실패: {exc}", file=sys.stderr)
        return False


def _provider_refusals() -> list[dict]:
    """Read provider refusal evidence written by the image client in this run."""
    from engine.image.gemini_client import PROVIDER_REFUSAL_PATH

    run_id = os.environ.get("GITHUB_RUN_ID", "local")
    found = []
    try:
        lines = Path(PROVIDER_REFUSAL_PATH).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    for line in lines:
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if isinstance(item, dict) and item.get("code") == "PROVIDER_REFUSAL" and (
                item.get("run_id") == run_id):
            found.append(item)
    return found


def main() -> None:
    """파이프라인 실패 알림 메인 로직."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--qc-warnings", action="store_true")
    args = parser.parse_args()
    findings = []
    if args.qc_warnings:
        from engine.quality.content_qc import WARNING_PATH

        try:
            for line in Path(WARNING_PATH).read_text(encoding="utf-8").splitlines():
                try:
                    finding = json.loads(line)
                    if isinstance(finding, dict) and finding.get("code") == "CONTENT_QC_WARNING":
                        findings.append(str(finding.get("message", "content review warning")))
                except (ValueError, TypeError):
                    continue
        except OSError:
            return
        if not findings:
            return
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    channel_id = os.environ.get("TELEGRAM_FREE_CHANNEL_ID", "")

    if not token or not channel_id:
        print(
            "[notify_failure] TELEGRAM_BOT_TOKEN 또는 TELEGRAM_FREE_CHANNEL_ID 없음. " "알림 생략.",
            file=sys.stderr,
        )
        # 알림 실패가 파이프라인 전체 실패를 가중시키지 않도록 exit 0
        sys.exit(0)

    run_id = os.environ.get("GITHUB_RUN_ID", "unknown")
    workflow = os.environ.get("GITHUB_WORKFLOW", "unknown")
    repo = os.environ.get("GITHUB_REPOSITORY", "investment-comic-gemini")
    run_url = f"https://github.com/{repo}/actions/runs/{run_id}"

    message = (
        "⚠️ <b>ICG 파이프라인 실패</b>\n\n"
        f"📋 워크플로우: <code>{workflow}</code>\n"
        f"🔢 Run ID: <code>{run_id}</code>\n"
        f"🔗 <a href='{run_url}'>Actions 로그 확인</a>\n\n"
        "수동 확인 후 재실행하거나 Supabase icg.episode_assets.status 점검 필요."
    )

    refusals = _provider_refusals()
    if refusals and not args.qc_warnings:
        message += "\n\n<b>Gemini 이미지 거절</b>\n" + "\n".join(
            html.escape(f"P{r.get('panel')}: {r.get('finish_reason')}") for r in refusals[:5]
        )

    if args.qc_warnings:
        details = "\n".join(html.escape(value[:100]) for value in list(dict.fromkeys(findings))[:5])
        message = (
            "⚠️ <b>ICG 콘텐츠 QC 경고 — 작업 계속 진행</b>\n\n"
            f"워크플로우: <code>{html.escape(workflow)}</code>\n"
            f"Run ID: <code>{html.escape(run_id)}</code>\n"
            f"{details}\n\n"
            f"<a href='{html.escape(run_url, quote=True)}'>Actions 로그 확인</a>"
        )
    success = _send_telegram(token, channel_id, message)
    if success:
        print(f"[notify_failure] 알림 전송 완료 (run_id={run_id})")
    else:
        print("[notify_failure] 알림 전송 실패 (무시)", file=sys.stderr)

    # 알림 실패 여부와 무관하게 exit 0 (파이프라인 상태 보존)
    sys.exit(0)


if __name__ == "__main__":
    main()
