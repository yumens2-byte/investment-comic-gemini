"""
FFmpeg composer: concat 3 cuts + final render (1080x1920, 24fps, H.264).

Workflow:
  1. concat_cuts()    : Lossless concat of 3 mp4 files (same codec required)
  2. mix_audio()      : Overlay narration + BGM + SFX (audio_overlay.py)
  3. burn_in()        : Burn-in ASS subtitles (subtitle_renderer.py)
  4. compose_final()  : Final render with target resolution + normalization
"""
import logging
import subprocess
from pathlib import Path

VERSION = "1.0.0"
logger = logging.getLogger(__name__)

TARGET_WIDTH = 1080
TARGET_HEIGHT = 1920
TARGET_FPS = 24
TARGET_CRF = 18
TARGET_AUDIO_LUFS = -14


def concat_cuts(cut_paths: list, output_path: str) -> str:
    """
    Concat multiple cuts losslessly using FFmpeg concat demuxer.

    Requirement: All cuts must have identical codec, resolution, framerate.
    Use this BEFORE audio mixing or subtitle burn-in.

    Args:
        cut_paths: List of mp4 file paths in order
        output_path: Destination mp4 file path

    Returns:
        output_path
    """
    for p in cut_paths:
        if not Path(p).exists():
            raise FileNotFoundError(f"cut not found: {p}")

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    list_file = Path(output_path).parent / "concat_list.txt"
    with open(list_file, "w") as f:
        for p in cut_paths:
            f.write(f"file '{Path(p).resolve()}'\n")

    logger.info(f"[ffmpeg_composer] v{VERSION} concat {len(cut_paths)} cuts -> {output_path}")

    try:
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(list_file),
                "-c",
                "copy",
                output_path,
            ],
            check=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError as e:
        logger.error(
            f"[ffmpeg_composer] concat failed: "
            f"stderr={e.stderr.decode('utf-8', errors='ignore')[:500]}"
        )
        raise

    list_file.unlink(missing_ok=True)
    logger.info(f"[ffmpeg_composer] concat done: {output_path}")
    return output_path


def compose_final(
    input_mp4: str,
    output_path: str,
    target_width: int = TARGET_WIDTH,
    target_height: int = TARGET_HEIGHT,
    target_fps: int = TARGET_FPS,
    crf: int = TARGET_CRF,
) -> str:
    """
    Final render pass:
      - Scale/pad to 1080x1920 (9:16) vertical
      - Framerate to 24fps
      - H.264 encoding with CRF 18 (high quality)
      - AAC 192kbps audio, 48kHz sample rate
      - faststart flag for web playback optimization

    Args:
        input_mp4: Source mp4 (after concat + audio + subtitle stages)
        output_path: Final output mp4

    Returns:
        output_path
    """
    if not Path(input_mp4).exists():
        raise FileNotFoundError(f"input_mp4 not found: {input_mp4}")

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    vf_chain = (
        f"scale={target_width}:{target_height}:force_original_aspect_ratio=decrease,"
        f"pad={target_width}:{target_height}:(ow-iw)/2:(oh-ih)/2:black,"
        f"fps={target_fps}"
    )

    logger.info(
        f"[ffmpeg_composer] final render: {target_width}x{target_height} @ {target_fps}fps -> {output_path}"
    )

    try:
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                input_mp4,
                "-vf",
                vf_chain,
                "-c:v",
                "libx264",
                "-preset",
                "slow",
                "-crf",
                str(crf),
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-ar",
                "48000",
                "-movflags",
                "+faststart",
                output_path,
            ],
            check=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError as e:
        logger.error(
            f"[ffmpeg_composer] final render failed: "
            f"stderr={e.stderr.decode('utf-8', errors='ignore')[:500]}"
        )
        raise

    size_mb = Path(output_path).stat().st_size / 1024 / 1024
    logger.info(f"[ffmpeg_composer] final done: {output_path} ({size_mb:.2f} MB)")
    return output_path
