"""
Subtitle renderer: ASS format generation + FFmpeg burn-in.

Why ASS (Advanced SubStation Alpha)?
  - Precise positioning (vertical 9:16 safe area)
  - Outline/shadow control for readability on busy backgrounds
  - Korean font rendering stability (NotoSansCJK)
"""
import logging
import subprocess
from pathlib import Path

VERSION = "1.0.0"
logger = logging.getLogger(__name__)

ASS_HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Noto Sans CJK KR,52,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,1,0,0,0,100,100,0,0,1,3,2,2,50,50,200,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def _format_ass_time(seconds: float) -> str:
    """Convert float seconds to ASS time format: H:MM:SS.cs"""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def build_ass(subtitle_items: list, output_path: str) -> str:
    """
    Build ASS subtitle file from timed items.

    Args:
        subtitle_items: List of dicts with keys: start_sec, end_sec, text
        output_path: Destination .ass file path

    Example item:
        {"start_sec": 0.5, "end_sec": 3.0, "text": "긴급 속보입니다"}

    Returns:
        output_path
    """
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    events_lines = []
    for item in subtitle_items:
        start = _format_ass_time(item["start_sec"])
        end = _format_ass_time(item["end_sec"])
        text = item["text"].replace("\n", "\\N")
        events_lines.append(
            f"Dialogue: 0,{start},{end},Default,,0,0,0,,{text}"
        )

    content = ASS_HEADER + "\n".join(events_lines) + "\n"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(content)

    logger.info(
        f"[subtitle_renderer] v{VERSION} ASS built: {output_path} "
        f"({len(subtitle_items)} lines)"
    )
    return output_path


def burn_in(video_path: str, ass_path: str, output_path: str) -> str:
    """
    Burn-in ASS subtitles into video (permanent, not switchable).

    Args:
        video_path: Source video
        ass_path: ASS subtitle file
        output_path: Destination mp4

    Returns:
        output_path
    """
    if not Path(video_path).exists():
        raise FileNotFoundError(f"video_path not found: {video_path}")
    if not Path(ass_path).exists():
        raise FileNotFoundError(f"ass_path not found: {ass_path}")

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    logger.info(f"[subtitle_renderer] burn-in start: {video_path} + {ass_path}")

    # Note: Using subtitles filter requires escaping ass_path on Windows.
    # For Linux (GitHub Actions), forward slash works.
    try:
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                video_path,
                "-vf",
                f"ass={ass_path}",
                "-c:a",
                "copy",
                output_path,
            ],
            check=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError as e:
        logger.error(
            f"[subtitle_renderer] burn-in failed: "
            f"stderr={e.stderr.decode('utf-8', errors='ignore')[:500]}"
        )
        raise

    logger.info(f"[subtitle_renderer] burn-in done: {output_path}")
    return output_path
