"""
Telegram Gate — Master personal approval gate (PAUSE stage).

Purpose:
  Send the final rendered 24s video to master's personal Telegram chat
  with inline buttons: [approve / regenerate / abort].
  Publishing (STEP 8V) executes ONLY after master explicit approval.

Flow:
  1. After STEP 7V (assembly), this module uploads the final mp4 to master.
  2. Master taps one of 3 buttons → Telegram callback_query triggers GitHub
     webhook (or separate workflow with manual input) → publish stage runs.
  3. If no response within 6 hours, workflow expires and logs to Supabase.

Requirements:
  TELEGRAM_BOT_TOKEN (env)  : bot token from @BotFather
  MASTER_CHAT_ID (env)      : master's personal Telegram user_id
                              (get via @userinfobot)

Telegram API:
  - sendVideo endpoint: max 50MB per bot upload (our 24s mp4 ≈ 20MB, OK)
  - inline_keyboard callback_data format: "{action}:{episode_id}"
"""
import logging
import os
from pathlib import Path

VERSION = "1.0.0"
logger = logging.getLogger(__name__)

# Telegram sendVideo body limit (bot API, standard server)
MAX_VIDEO_SIZE_MB = 50
# Caption max length
MAX_CAPTION_LEN = 1024


class TelegramGateError(Exception):
    """Raised when gate notification fails."""


def send_approval_request(
    video_path: str,
    episode_id: str,
    scenario_type: str,
    cost_usd: float,
    generation_ms: int,
) -> dict:
    """
    Send final video to master with inline approval buttons.

    Args:
        video_path       : Final rendered mp4 path
        episode_id       : icg.video_assets episode_id
        scenario_type    : e.g. "ONE_VS_ONE"
        cost_usd         : Total Veo cost for this episode
        generation_ms    : Total generation time

    Returns:
        dict with keys: message_id, chat_id, sent_at

    Raises:
        TelegramGateError on upload failure.
    """
    if not Path(video_path).exists():
        raise TelegramGateError(f"video_path not found: {video_path}")

    size_mb = Path(video_path).stat().st_size / 1024 / 1024
    if size_mb > MAX_VIDEO_SIZE_MB:
        raise TelegramGateError(
            f"Video size {size_mb:.1f}MB exceeds Telegram bot limit {MAX_VIDEO_SIZE_MB}MB"
        )

    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("MASTER_CHAT_ID")
    if not bot_token:
        raise TelegramGateError("TELEGRAM_BOT_TOKEN env not set")
    if not chat_id:
        raise TelegramGateError("MASTER_CHAT_ID env not set")

    caption = _build_caption(
        episode_id=episode_id,
        scenario_type=scenario_type,
        cost_usd=cost_usd,
        generation_ms=generation_ms,
        size_mb=size_mb,
    )
    reply_markup = _build_approval_keyboard(episode_id)

    logger.info(
        f"[telegram_gate] v{VERSION} sending approval request: "
        f"episode={episode_id} size={size_mb:.1f}MB"
    )
    logger.debug(
        "[telegram_gate] prepared payload: caption_len=%d, buttons=%d",
        len(caption),
        len(reply_markup["inline_keyboard"]),
    )

    # TODO: actual Telegram sendVideo API call (V5)
    # from telegram import Bot
    # bot = Bot(token=bot_token)
    # with open(video_path, "rb") as f:
    #     msg = bot.send_video(
    #         chat_id=chat_id,
    #         video=f,
    #         caption=caption,
    #         parse_mode="HTML",
    #         reply_markup=reply_markup,
    #         supports_streaming=True,
    #     )
    # return {"message_id": msg.message_id, "chat_id": chat_id, "sent_at": msg.date.isoformat()}

    logger.info("[telegram_gate] approval request sent (SKELETON — implement in V5)")
    return {
        "message_id": None,
        "chat_id": chat_id,
        "sent_at": None,
        "status": "skeleton",
    }


def _build_caption(
    episode_id: str,
    scenario_type: str,
    cost_usd: float,
    generation_ms: int,
    size_mb: float,
) -> str:
    """Build the master-facing caption with metadata."""
    caption = (
        f"🎬 <b>ICG Video Trailer — 승인 대기</b>\n\n"
        f"<b>Episode</b>: <code>{episode_id}</code>\n"
        f"<b>Scenario</b>: {scenario_type}\n"
        f"<b>Cost</b>: ${cost_usd:.4f}\n"
        f"<b>Time</b>: {generation_ms / 1000:.1f}s\n"
        f"<b>Size</b>: {size_mb:.2f} MB\n\n"
        f"아래 버튼을 선택해주세요."
    )
    if len(caption) > MAX_CAPTION_LEN:
        caption = caption[: MAX_CAPTION_LEN - 3] + "..."
    return caption


def _build_approval_keyboard(episode_id: str) -> dict:
    """Build inline keyboard with 3 buttons: approve / regenerate / abort."""
    return {
        "inline_keyboard": [
            [
                {"text": "✅ 승인 → 발행", "callback_data": f"approve:{episode_id}"},
            ],
            [
                {"text": "🔄 재생성", "callback_data": f"regenerate:{episode_id}"},
                {"text": "🚫 폐기", "callback_data": f"abort:{episode_id}"},
            ],
        ]
    }


def handle_callback(callback_data: str) -> dict:
    """
    Parse callback_data from master tap.

    Args:
        callback_data: "approve:ICG-V-2026-04-19-001" style string

    Returns:
        dict with keys: action, episode_id, is_valid
    """
    try:
        action, episode_id = callback_data.split(":", 1)
    except ValueError:
        return {"action": None, "episode_id": None, "is_valid": False}

    if action not in ("approve", "regenerate", "abort"):
        return {"action": action, "episode_id": episode_id, "is_valid": False}

    return {"action": action, "episode_id": episode_id, "is_valid": True}
