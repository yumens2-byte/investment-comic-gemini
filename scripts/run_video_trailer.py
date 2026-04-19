"""
ICG Video Track — main runner
Strict Isolation from image track (run_market.py).

Stages:
  data              : STEP 1V-2V — scheduler check + DB read (read-only)
  scenario          : STEP 3V — scenario selection (reuses v2.0)
  narrative         : STEP 4V — Claude video script generation
  persist_init      : STEP 5V — icg.video_assets INSERT (generating)
  veo               : STEP 6V — Veo 3.1 Lite x 3 cuts (I2V chaining)
  assembly          : STEP 7V — FFmpeg concat + audio + subtitle + render
  gate_notify       : PAUSE   — Telegram approval request to master
  publish_telegram  : STEP 8V-a — TG free + paid channel video publish
  publish_x         : STEP 8V-b — X (Twitter) chunked video upload
  publish_shorts    : STEP 8V-c — YouTube Shorts API upload
  persist_final     : STEP 8V-d — icg.video_assets status='published' update

Note on publish stages:
  publish_* and persist_final stages run ONLY after master approval
  (via callback or separate workflow trigger). The gate_notify stage
  is the last step of the main scheduled run.
"""
import argparse
import logging
import os
import platform
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

VERSION = "1.2.0"

logger = logging.getLogger("run_video_trailer")

# Environment variables tracked for presence on every run (masked in logs).
# These follow the existing ICG repository Secret naming convention.
# Not all are required — missing ones are logged but don't fail execution.
_TRACKED_ENV_VARS = [
    # Core APIs (ICG 규약 준수)
    "ANTHROPIC_API_KEY",
    "GEMINI_API_SUB_PAY_KEY",  # Veo + TTS 공용 Paid 키
    "FRED_API_KEY",
    "NOTION_API_KEY",
    # Supabase
    "SUPABASE_URL",
    "SUPABASE_KEY",
    # X (Twitter)
    "X_API_KEY",
    "X_API_SECRET",
    "X_ACCESS_TOKEN",
    "X_ACCESS_TOKEN_SECRET",
    # Telegram (게이트 + 채널)
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_FREE_CHANNEL_ID",
    "TELEGRAM_PAID_CHANNEL_ID",
    "MASTER_CHAT_ID",  # Phase V5 게이트 전 등록 필요
    # Budget cap
    "VIDEO_BUDGET_USD_MONTHLY",
]


def _mask_secret(value: str, env_name: str) -> str:
    """Mask sensitive env values for logging. Show first 4 chars + **** for tokens."""
    if not value:
        return "(empty)"
    # Non-sensitive values display as-is (truncated if too long)
    non_sensitive = {"MASTER_CHAT_ID", "SUPABASE_URL", "VIDEO_BUDGET_USD_MONTHLY"}
    if env_name in non_sensitive or env_name.endswith("_ID") or env_name.endswith("_URL"):
        return value if len(value) <= 40 else value[:37] + "..."
    # Sensitive values: show prefix only
    return value[:4] + "****" if len(value) > 4 else "****"


def _setup_logging(stage: str) -> Path:
    """
    Configure root logger with Console (INFO) + File (DEBUG) handlers.

    Returns:
        Path to the log file written for this stage.
    """
    log_level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
    console_level = getattr(logging, log_level_name, logging.INFO)

    root = logging.getLogger()
    # Remove any pre-existing handlers (e.g., from prior basicConfig)
    for h in root.handlers[:]:
        root.removeHandler(h)
    root.setLevel(logging.DEBUG)  # capture everything; handlers filter

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Console handler (stdout; GitHub Actions captures this)
    console_handler = logging.StreamHandler(stream=sys.stdout)
    console_handler.setLevel(console_level)
    console_handler.setFormatter(fmt)
    root.addHandler(console_handler)

    # File handler (always DEBUG for full detail)
    run_id = os.environ.get("GITHUB_RUN_ID", "local")
    log_dir = Path("logs") / str(run_id)
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"{stage}.log"

    file_handler = logging.FileHandler(log_file, mode="w", encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)

    return log_file


def _log_environment_info(stage: str, log_file: Path) -> None:
    """Dump runtime context at the start of each stage for easier debugging."""
    logger.info("=" * 72)
    logger.info(f"STAGE START: {stage}")
    logger.info("=" * 72)
    logger.info(f"run_video_trailer v{VERSION}")
    logger.info(
        f"Python {platform.python_version()} on "
        f"{platform.system()} {platform.release()} ({platform.machine()})"
    )
    logger.info(f"Working directory: {Path.cwd()}")
    logger.info(f"Log file: {log_file.resolve()}")

    # GitHub Actions context
    gh_run_id = os.environ.get("GITHUB_RUN_ID", "N/A")
    gh_workflow = os.environ.get("GITHUB_WORKFLOW", "N/A")
    gh_ref = os.environ.get("GITHUB_REF_NAME", "N/A")
    gh_sha = os.environ.get("GITHUB_SHA", "N/A")
    logger.info(
        f"GitHub: workflow={gh_workflow} run_id={gh_run_id} "
        f"ref={gh_ref} sha={gh_sha[:8] if gh_sha != 'N/A' else gh_sha}"
    )

    # Runtime flags
    dry_run = os.environ.get("DRY_RUN", "false")
    log_level = os.environ.get("LOG_LEVEL", "INFO")
    logger.info(f"Flags: DRY_RUN={dry_run} LOG_LEVEL={log_level}")

    # Environment variables check (masked)
    present = []
    missing = []
    for env in _TRACKED_ENV_VARS:
        val = os.environ.get(env, "")
        if val:
            present.append(env)
            logger.debug(f"  ENV {env}={_mask_secret(val, env)} (set)")
        else:
            missing.append(env)

    logger.info(
        f"Env vars: {len(present)}/{len(_TRACKED_ENV_VARS)} set"
        + (f", missing={missing}" if missing else "")
    )
    logger.info("-" * 72)


def stage_data():
    """STEP 1V-2V: scheduler check + DB read (read-only)."""
    logger.info("[1V] scheduler / holiday / budget check")
    # TODO: US market holiday check
    # TODO: Budget Cap check (icg.video_assets.veo_cost_usd monthly sum vs VIDEO_BUDGET_USD_MONTHLY)

    logger.info("[2V] load snapshot + analysis (read-only)")
    today = datetime.now(ZoneInfo("Asia/Seoul")).date()
    # TODO: Reuse existing image track modules (Strict Isolation compatible — common/data OK):
    #   from engine.common.supabase_client import get_supabase_client
    #   from engine.analysis.reader import read_snapshot, read_analysis
    #   sb = get_supabase_client()
    #   snapshot = read_snapshot(sb, today)
    #   analysis = read_analysis(sb, today)
    logger.info(f"[2V] target date: {today}")
    return {"snapshot_date": str(today)}


def stage_scenario():
    """STEP 3V: scenario selection (reuses ICG image track v2.0 selector)."""
    logger.info("[3V] scenario selection")
    # TODO: from engine.narrative.scenario_selector import select_scenario
    #       (existing module path in repo; NOT engine.analysis.scenario_selector)
    #       scenario = select_scenario(risk_level=..., event_type=...)
    # NO_BATTLE is not suitable for news-format trailer → skip
    scenario = "ONE_VS_ONE"  # placeholder
    logger.info(f"[3V] scenario: {scenario}")
    if scenario == "NO_BATTLE":
        logger.warning("[3V] NO_BATTLE scenario — video track skips this episode")
        sys.exit(0)
    return scenario


def stage_narrative():
    """STEP 4V: Claude video scenario generation (3 cuts x 8s)."""
    logger.info("[4V] Claude video script generation")
    # TODO: Render config/prompts/video_scenario.j2
    # TODO: Call Claude API → VideoEpisodeScript JSON
    # TODO: Validate 3 cuts x 8s, character lock, title card no-text rule
    logger.info("[4V] video script generated")


def stage_persist_init():
    """STEP 5V: icg.video_assets INSERT (status='generating')."""
    logger.info("[5V] persist init to icg.video_assets")
    # TODO: INSERT INTO icg.video_assets
    #       (episode_id, episode_date, scenario_type, status, created_at)
    #       VALUES (...) ON CONFLICT (episode_id) DO UPDATE SET status='generating';
    logger.info("[5V] record initialized")


def stage_veo():
    """STEP 6V: Veo 3.1 Lite 3-cut generation with I2V chaining."""
    logger.info("[6V] Veo 3-cut generation start")
    # TODO: from engine.video.i2v_chain import run_i2v_chain
    #       run_i2v_chain(cut_prompts=[...], output_dir="output/videos/today")
    logger.info("[6V] Veo 3 cuts generated")


def stage_assembly():
    """STEP 7V: FFmpeg concat + audio overlay + subtitle burn-in + final render."""
    logger.info("[7V] FFmpeg assembly start")
    # TODO: from engine.video.ffmpeg_composer import concat_cuts, compose_final
    # TODO: from engine.video.audio_overlay import mix_audio
    # TODO: from engine.video.subtitle_renderer import build_ass, burn_in
    logger.info("[7V] final mp4 rendered to output/videos/today/final.mp4")


def stage_gate_notify():
    """PAUSE: Telegram master approval request (sends final mp4 to master personal chat)."""
    logger.info("[PAUSE] Telegram master approval request")

    # TODO: Load final mp4 path + metadata from icg.video_assets (status='assembled')
    # TODO: Call engine.publish.telegram_gate.send_approval_request()
    # from engine.publish.telegram_gate import send_approval_request
    # send_approval_request(
    #     video_path=final_mp4_path,
    #     episode_id=episode_id,
    #     scenario_type=scenario_type,
    #     cost_usd=total_cost,
    #     generation_ms=total_ms,
    # )
    # Update icg.video_assets status='pending_approval'

    logger.info("[PAUSE] awaiting master approval — workflow ends here")


def stage_publish_telegram():
    """STEP 8V-a: Publish to TG free + paid channels (runs AFTER master approval)."""
    logger.info("[8V-a] Telegram channels publish start")

    # TODO: Load episode metadata (approved=True) from icg.video_assets
    # TODO: Call video publisher (NOT the existing telegram_publisher.py which is for images)
    # from engine.publish.telegram_video_publisher import (
    #     publish_to_free_channel, publish_to_paid_channel
    # )
    #
    # free_result = publish_to_free_channel(
    #     video_path=final_mp4_path,
    #     episode_id=episode_id,
    #     title=title,
    #     hashtags=hashtags,
    #     teaser_line=teaser_line,
    #     paid_channel_invite_link=PAID_INVITE_URL,
    # )
    # paid_result = publish_to_paid_channel(
    #     video_path=final_mp4_path,
    #     episode_id=episode_id,
    #     title=title,
    #     hashtags=hashtags,
    #     full_narrative=full_narrative,
    #     market_context=market_context,
    # )
    # Update icg.video_assets.published_tg = NOW()

    logger.info("[8V-a] Telegram publish done")


def stage_publish_x():
    """STEP 8V-b: Publish to X (Twitter) via chunked upload."""
    logger.info("[8V-b] X video publish start")

    # TODO: from engine.publish.x_video_publisher import publish_video_to_x
    # result = publish_video_to_x(
    #     video_path=final_mp4_path,
    #     caption=x_caption,  # ≤280 chars
    #     episode_id=episode_id,
    # )
    # Update icg.video_assets.tweet_id = result["tweet_id"],
    #                       .published_x = NOW()

    logger.info("[8V-b] X publish done")


def stage_publish_shorts():
    """STEP 8V-c: Publish to YouTube Shorts."""
    logger.info("[8V-c] YouTube Shorts publish start")

    # TODO: from engine.publish.youtube_shorts_publisher import publish_to_youtube_shorts
    # result = publish_to_youtube_shorts(
    #     video_path=final_mp4_path,
    #     title=yt_title,
    #     description=yt_description,
    #     episode_id=episode_id,
    #     tags=["미주투자", "시장분석", "ICG"],
    # )
    # Update icg.video_assets.youtube_video_id = result["youtube_video_id"],
    #                       .published_shorts = NOW()

    logger.info("[8V-c] Shorts publish done")


def stage_persist_final():
    """STEP 8V-d: Finalize icg.video_assets status='published' + Notion tracker."""
    logger.info("[8V-d] persist final status")

    # TODO: UPDATE icg.video_assets SET status='published', updated_at=NOW()
    # WHERE episode_id = %s
    # TODO: Create/update Notion EpisodeTracker page with final URLs

    logger.info("[8V-d] persist final done")


STAGES = {
    "data": stage_data,
    "scenario": stage_scenario,
    "narrative": stage_narrative,
    "persist_init": stage_persist_init,
    "veo": stage_veo,
    "assembly": stage_assembly,
    "gate_notify": stage_gate_notify,
    "publish_telegram": stage_publish_telegram,
    "publish_x": stage_publish_x,
    "publish_shorts": stage_publish_shorts,
    "persist_final": stage_persist_final,
}


def main():
    parser = argparse.ArgumentParser(description="ICG Video Track runner")
    parser.add_argument(
        "--stage",
        required=True,
        choices=list(STAGES.keys()),
        help="Pipeline stage to execute",
    )
    args = parser.parse_args()

    # Setup logging FIRST (console + file)
    log_file = _setup_logging(args.stage)

    # Dump environment / runtime context
    _log_environment_info(args.stage, log_file)

    # Execute the stage with timing
    start_ts = time.monotonic()
    exit_code = 0
    try:
        STAGES[args.stage]()
    except SystemExit as exc:
        # stage_scenario raises SystemExit(0) on NO_BATTLE; preserve code
        exit_code = exc.code if isinstance(exc.code, int) else 1
        logger.info(f"[run_video_trailer] stage={args.stage} exited with code={exit_code}")
    except Exception:
        exit_code = 1
        logger.exception(f"[run_video_trailer] stage={args.stage} failed with exception")
    finally:
        elapsed = time.monotonic() - start_ts
        logger.info("-" * 72)
        logger.info(
            f"STAGE END: {args.stage} | elapsed={elapsed:.3f}s | exit_code={exit_code}"
        )
        logger.info(f"Log file saved: {log_file.resolve()}")
        logger.info("=" * 72)
        # Ensure file handler flushes before exit
        logging.shutdown()

    if exit_code != 0:
        sys.exit(exit_code)
    logger.info(f"[run_video_trailer] stage={args.stage} 완료")


if __name__ == "__main__":
    main()
