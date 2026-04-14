"""
engine/publish/telegram_publisher.py
Telegram Bot API — 슬라이드 + 캡션 발행.

무료/유료 채널 분리 발행.
슬라이드는 media group (앨범)으로 전송.
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

_TG_API_BASE = "https://api.telegram.org"
_DISCLAIMER_REQUIRED = "본 콘텐츠는 투자 참고 정보이며, 투자 권유가 아닙니다"


def _get_bot_token() -> str:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN 환경변수 누락")
    return token


def _send_media_group(
    token: str,
    channel_id: str,
    slides: list[Path],
    caption: str,
) -> dict | None:
    """슬라이드를 media group(앨범)으로 전송."""
    if not slides:
        return None

    url = f"{_TG_API_BASE}/bot{token}/sendMediaGroup"
    media = []
    files = {}

    for i, slide in enumerate(slides[:10]):  # TG 최대 10장
        if not slide.exists():
            continue
        key = f"photo{i}"
        files[key] = open(slide, "rb")
        item = {"type": "photo", "media": f"attach://{key}"}
        if i == 0 and caption:
            item["caption"] = caption[:1024]  # TG 최대 1024자
            item["parse_mode"] = "HTML"
        media.append(item)

    if not media:
        return None

    try:
        import json
        resp = requests.post(
            url,
            data={"chat_id": channel_id, "media": json.dumps(media)},
            files=files,
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        logger.error("[telegram] media group 전송 실패: %s", exc)
        return None
    finally:
        for f in files.values():
            f.close()


def _send_text(token: str, channel_id: str, text: str) -> dict | None:
    """텍스트 메시지 전송."""
    url = f"{_TG_API_BASE}/bot{token}/sendMessage"
    try:
        resp = requests.post(
            url,
            json={
                "chat_id": channel_id,
                "text": text[:4096],
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        logger.error("[telegram] 텍스트 전송 실패: %s", exc)
        return None


def publish_episode_telegram(
    script_dict: dict,
    slides: list[Path],
    channels: list[str] | None = None,
    dry_run: bool = True,
) -> dict[str, bool]:
    """
    에피소드를 Telegram에 발행.

    Args:
        script_dict: EpisodeScript.model_dump().
        slides: 슬라이드 경로 목록.
        channels: 발행할 채널 ID 목록 (None이면 무료 채널만).
        dry_run: True이면 실제 발행 없이 로그만.

    Returns:
        {channel_id: 성공 여부} 딕셔너리.
    """
    caption = script_dict.get("caption_telegram", "")

    if _DISCLAIMER_REQUIRED not in caption:
        # TG 캡션에도 면책 고지 추가
        caption += f"\n\n⚠️ {_DISCLAIMER_REQUIRED}"

    # 기본 채널
    if channels is None:
        free_id = os.environ.get("TELEGRAM_FREE_CHANNEL_ID", "")
        channels = [free_id] if free_id else []

    results: dict[str, bool] = {}

    for channel_id in channels:
        if not channel_id:
            continue

        if dry_run:
            logger.info(
                "[telegram] DRY_RUN — 채널 %s에 슬라이드 %d장 발행 시뮬레이션",
                channel_id, len(slides)
            )
            results[channel_id] = True
            continue

        try:
            token = _get_bot_token()

            # 슬라이드 10장씩 분할 전송 (TG 앨범 최대 10장)
            for batch_start in range(0, len(slides), 10):
                batch = slides[batch_start : batch_start + 10]
                cap = caption if batch_start == 0 else ""
                resp = _send_media_group(token, channel_id, batch, cap)
                if resp:
                    logger.info(
                        "[telegram] 채널 %s 슬라이드 %d~%d 발행 완료",
                        channel_id, batch_start + 1, batch_start + len(batch)
                    )
                    results[channel_id] = True
                else:
                    results[channel_id] = False

                if batch_start + 10 < len(slides):
                    time.sleep(2)

        except Exception as exc:
            logger.error("[telegram] 채널 %s 발행 실패: %s", channel_id, exc)
            results[channel_id] = False

    return results
