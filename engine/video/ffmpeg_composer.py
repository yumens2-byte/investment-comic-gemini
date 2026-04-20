"""
FFmpeg composer: concat 3 cuts + final render (1080x1920, 24fps, H.264).

Workflow:
  1. concat_cuts()             : Lossless concat of 3 mp4 files (same codec required)
  2. crop_bottom_banner()      : 단일 mp4 하단 banner crop (Phase V3)
  3. concat_cuts_with_crop()   : 3컷 crop 후 concat (Phase V3)
  4. mix_audio()               : Overlay narration + BGM + SFX (audio_overlay.py)
  5. burn_in()                 : Burn-in ASS subtitles (subtitle_renderer.py)
  6. compose_final()           : Final render with target resolution + normalization
"""
import logging
import subprocess
from pathlib import Path

VERSION = "1.1.0"
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


def crop_bottom_banner(
    input_mp4: str,
    output_mp4: str,
    crop_height: int = 150,
    mode: str = "pad",   # "pad" | "scale"
) -> str:
    """
    하단 banner 영역을 crop하여 제거 (Phase V3).

    Args:
        input_mp4: 원본 mp4 (720×1280)
        output_mp4: 출력 mp4 (720×1280)
        crop_height: 하단에서 제거할 픽셀 높이 (기본 150px)
        mode:
            "pad"   — crop 후 검은 pad로 원본 높이 복원 (Phase V4 자막용)
            "scale" — crop 후 원본 높이로 vertical stretch

    Returns:
        output_mp4 경로
    """
    if not Path(input_mp4).exists():
        raise FileNotFoundError(f"input_mp4 not found: {input_mp4}")

    Path(output_mp4).parent.mkdir(parents=True, exist_ok=True)

    new_h = 1280 - crop_height
    if mode == "pad":
        vf = f"crop=720:{new_h}:0:0,pad=720:1280:(ow-iw)/2:0:black"
    elif mode == "scale":
        vf = f"crop=720:{new_h}:0:0,scale=720:1280"
    else:
        raise ValueError(f"Unknown mode: {mode}")

    logger.info(
        f"[ffmpeg_composer] v{VERSION} crop_bottom_banner "
        f"mode={mode} crop={crop_height}px {input_mp4} -> {output_mp4}"
    )

    try:
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                input_mp4,
                "-vf",
                vf,
                "-c:v",
                "libx264",
                "-preset",
                "slow",
                "-crf",
                str(TARGET_CRF),
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "copy",
                output_mp4,
            ],
            check=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError as e:
        logger.error(
            f"[ffmpeg_composer] crop_bottom_banner failed: "
            f"stderr={e.stderr.decode('utf-8', errors='ignore')[:500]}"
        )
        raise

    logger.info(f"[ffmpeg_composer] crop done: {output_mp4}")
    return output_mp4


def concat_cuts_with_crop(
    cut_paths: list,
    output_path: str,
    crop_height: int = 150,
    mode: str = "pad",
) -> str:
    """
    3컷 mp4를 crop 후 concat (Phase V3).

    순서:
      1. 각 cut별 crop_bottom_banner() 적용 → _crop_0_*, _crop_1_*, _crop_2_*
      2. concat_cuts() 호출로 3개 crop 결과물 결합
      3. 임시 crop 파일 cleanup (성공/실패 무관)

    Args:
        cut_paths: List of mp4 file paths in order (720×1280)
        output_path: 최종 concat mp4 경로
        crop_height: 하단에서 제거할 픽셀 높이 (기본 150px)
        mode: "pad" | "scale"

    Returns:
        최종 concat mp4 경로 (720×1280)
    """
    for p in cut_paths:
        if not Path(p).exists():
            raise FileNotFoundError(f"cut not found: {p}")

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    logger.info(
        f"[ffmpeg_composer] v{VERSION} concat_cuts_with_crop "
        f"cuts={len(cut_paths)} mode={mode} crop={crop_height}px -> {output_path}"
    )

    cropped_paths = []
    try:
        for idx, p in enumerate(cut_paths):
            tmp = Path(output_path).parent / f"_crop_{idx}_{Path(p).name}"
            crop_bottom_banner(
                input_mp4=p,
                output_mp4=str(tmp),
                crop_height=crop_height,
                mode=mode,
            )
            cropped_paths.append(str(tmp))

        result = concat_cuts(cropped_paths, output_path)
        logger.info(f"[ffmpeg_composer] concat_cuts_with_crop done: {result}")
        return result
    finally:
        for tmp in cropped_paths:
            Path(tmp).unlink(missing_ok=True)
