"""
FFmpeg wrapper: extract last frame from mp4.

Used for I2V chaining: extract the last frame of cut N and use it
as the start frame for cut N+1 to maintain visual continuity.
"""
import logging
import subprocess
from pathlib import Path

VERSION = "1.0.0"
logger = logging.getLogger(__name__)


def extract_last_frame(video_path: str, output_path: str) -> str:
    """
    Extract the last frame of a video as PNG.

    Uses `-sseof -0.04` to seek to approximately the last frame
    (assumes 24fps → 1 frame ≈ 41.67ms).

    Args:
        video_path: Source mp4 file path
        output_path: Destination PNG file path

    Returns:
        output_path on success

    Raises:
        subprocess.CalledProcessError if ffmpeg fails
        FileNotFoundError if video_path does not exist
    """
    if not Path(video_path).exists():
        raise FileNotFoundError(f"video_path not found: {video_path}")

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    logger.info(f"[frame_extractor] v{VERSION} {video_path} -> {output_path}")

    try:
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-sseof",
                "-0.04",
                "-i",
                video_path,
                "-frames:v",
                "1",
                "-q:v",
                "2",
                output_path,
            ],
            check=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError as e:
        logger.error(
            f"[frame_extractor] ffmpeg failed: returncode={e.returncode} "
            f"stderr={e.stderr.decode('utf-8', errors='ignore')[:500]}"
        )
        raise

    if not Path(output_path).exists():
        raise RuntimeError(f"Extraction succeeded but output not found: {output_path}")

    size_kb = Path(output_path).stat().st_size / 1024
    logger.info(f"[frame_extractor] extracted: {output_path} ({size_kb:.1f} KB)")
    return output_path


def extract_first_frame(video_path: str, output_path: str) -> str:
    """Extract the first frame of a video as PNG (for debugging/preview)."""
    if not Path(video_path).exists():
        raise FileNotFoundError(f"video_path not found: {video_path}")

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-ss",
            "0.0",
            "-i",
            video_path,
            "-frames:v",
            "1",
            "-q:v",
            "2",
            output_path,
        ],
        check=True,
        capture_output=True,
    )
    return output_path
