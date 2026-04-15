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

import os
import sys

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


def main() -> None:
    """파이프라인 실패 알림 메인 로직."""
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

    success = _send_telegram(token, channel_id, message)
    if success:
        print(f"[notify_failure] 알림 전송 완료 (run_id={run_id})")
    else:
        print("[notify_failure] 알림 전송 실패 (무시)", file=sys.stderr)

    # 알림 실패 여부와 무관하게 exit 0 (파이프라인 상태 보존)
    sys.exit(0)


if __name__ == "__main__":
    main()
