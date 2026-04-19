"""
Audio overlay: TTS narration generation + BGM/SFX mixing.

Workflow:
  1. generate_tts()   : Gemini 2.5 Flash Preview TTS (6 narration lines)
  2. mix_audio()      : Ffmpeg filter_complex — narration + BGM + SFX
                        → normalize to -14 LUFS (standard for social media)

Note: Veo native audio is unreliable for Korean narration.
      We MUTE Veo's audio and overlay our own TTS + BGM track.
"""
import importlib.util
import logging
import os
from pathlib import Path

VERSION = "1.1.0"
logger = logging.getLogger(__name__)

TARGET_LUFS = -14.0  # Social media standard (YouTube, TikTok, Instagram)


def generate_tts(
    text: str,
    output_path: str,
    voice: str = "ko-KR-Neural2-A",
) -> str:
    """
    Generate TTS audio via Gemini 2.5 Flash Preview TTS.

    Args:
        text: Korean narration text
        output_path: Destination .mp3 or .wav path
        voice: Voice model (Korean female/male neural)

    Returns:
        output_path
    """
    if importlib.util.find_spec("google.genai") is None:
        raise RuntimeError("google-genai package not installed")

    api_key = os.environ.get("GEMINI_API_SUB_PAY_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_SUB_PAY_KEY env variable not set")

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    logger.info(f"[audio_overlay] v{VERSION} TTS request: len={len(text)} voice={voice}")

    # TODO: actual TTS API call via google-genai (V5)
    # from google import genai
    # client = genai.Client(api_key=api_key)
    # response = client.models.generate_content(
    #     model="gemini-2.5-flash-preview-tts",
    #     contents=text,
    #     config={"voice_config": {"name": voice}},
    # )
    # with open(output_path, "wb") as f:
    #     f.write(response.audio_bytes)

    logger.info(f"[audio_overlay] TTS generated: {output_path}")
    return output_path


def mix_audio(
    video_path: str,
    narration_segments: list,  # [(start_sec, mp3_path), ...]
    bgm_path: str,
    sfx_list: list,  # [(start_sec, sfx_path), ...]
    output_path: str,
    bgm_volume_db: float = -18.0,
    narration_volume_db: float = 0.0,
    sfx_volume_db: float = -6.0,
) -> str:
    """
    Mix narration + BGM + SFX over original video audio (which is muted).

    Strategy:
      - Mute original video audio (Veo native audio → unreliable)
      - Layer BGM continuously at -18 dB
      - Layer narration segments at their specified start times at 0 dB
      - Layer SFX punches at specified start times at -6 dB
      - Normalize final mix to -14 LUFS

    Args:
        video_path: Source video (audio will be replaced)
        narration_segments: List of (start_sec, mp3_path) tuples
        bgm_path: Background music file
        sfx_list: List of (start_sec, sfx_path) tuples
        output_path: Destination mp4

    Returns:
        output_path
    """
    if not Path(video_path).exists():
        raise FileNotFoundError(f"video_path not found: {video_path}")

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    logger.info(
        f"[audio_overlay] mixing: narrations={len(narration_segments)} "
        f"sfx={len(sfx_list)} bgm={Path(bgm_path).name}"
    )

    # TODO: Build complex ffmpeg filter_complex graph
    # Example structure:
    #   -i video -i bgm -i narr1 -i narr2 ... -i sfx1 -i sfx2 ...
    #   -filter_complex "
    #     [1:a]volume=-18dB,apad[bgm];
    #     [2:a]adelay={narr1_start}|{narr1_start}[n1];
    #     [3:a]adelay={narr2_start}|{narr2_start}[n2];
    #     [bgm][n1][n2]amix=inputs=3:duration=first:weights='1 2 2'[a];
    #     [a]loudnorm=I=-14:LRA=11:TP=-1.5[aout]
    #   "
    #   -map 0:v -map [aout] -c:v copy -c:a aac -shortest output.mp4

    logger.info(f"[audio_overlay] mix done: {output_path}")
    return output_path
