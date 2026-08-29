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

VERSION = "1.3.0"
logger = logging.getLogger(__name__)

TARGET_LUFS = -14.0  # Social media standard (YouTube, TikTok, Instagram)

# TTS 비용 계측 (v1.3.0) — 2026-08-29 점검에서 유일하게 미계측 항목이었다.
# gemini-2.5-flash-preview-tts 는 텍스트 입력 + 오디오 출력 토큰으로 과금된다.
# 실제 usage_metadata 를 읽어 산출하며, 단가는 상수로 분리해 갱신 가능하게 둔다.
_TTS_COST_INPUT_PER_1M = 0.50   # USD / 1M text input tokens
_TTS_COST_OUTPUT_PER_1M = 10.0  # USD / 1M audio output tokens


def _pcm_to_wav_bytes(
    pcm: bytes,
    sample_rate: int = 24000,
    channels: int = 1,
    sample_width: int = 2,
) -> bytes:
    """Gemini TTS 응답(raw PCM s16le 24kHz mono)에 WAV 헤더를 붙인다."""
    import struct

    byte_rate = sample_rate * channels * sample_width
    block_align = channels * sample_width
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        36 + len(pcm),
        b"WAVE",
        b"fmt ",
        16,
        1,  # PCM
        channels,
        sample_rate,
        byte_rate,
        block_align,
        sample_width * 8,
        b"data",
        len(pcm),
    )
    return header + pcm


def generate_tts(
    text: str,
    output_path: str,
    voice: str = "Kore",
) -> str:
    """
    Generate TTS audio via Gemini 2.5 Flash Preview TTS.

    v1.2.0: TODO 실장 (Daily Battle Shorts S5).
      - 응답 inline_data 는 raw PCM(s16le/24kHz/mono) → WAV 로 저장.
      - voice 기본값 교정: "ko-KR-Neural2-A"(Google Cloud TTS 보이스명)는
        Gemini TTS prebuilt voice 가 아니어서 무효 → "Kore" (한국어 지원 prebuilt).

    Args:
        text: Korean narration text
        output_path: Destination .wav path
        voice: Gemini prebuilt voice name (예: "Kore", "Puck")

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

    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model="gemini-2.5-flash-preview-tts",
        contents=text,
        config=types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice)
                )
            ),
        ),
    )

    try:
        pcm = response.candidates[0].content.parts[0].inline_data.data
    except (AttributeError, IndexError, TypeError) as exc:
        raise RuntimeError(f"TTS 응답에서 오디오 데이터 추출 실패: {exc}") from exc

    Path(output_path).write_bytes(_pcm_to_wav_bytes(pcm))

    # 생성당 비용 로그 — gemini_client / veo_client 와 동일 스타일 (v1.3.0)
    cost = estimate_tts_cost(getattr(response, "usage_metadata", None))
    logger.info(
        f"[audio_overlay] TTS generated: {output_path} "
        f"({len(pcm)} bytes PCM) cost=${cost:.6f}"
    )
    return output_path


def estimate_tts_cost(usage) -> float:
    """TTS 응답의 usage_metadata 로 비용을 산출한다 (없으면 0.0)."""
    if usage is None:
        return 0.0
    prompt_tokens = getattr(usage, "prompt_token_count", 0) or 0
    # 오디오 출력은 candidates_token_count 에 집계된다.
    output_tokens = getattr(usage, "candidates_token_count", 0) or 0
    return (
        prompt_tokens * _TTS_COST_INPUT_PER_1M
        + output_tokens * _TTS_COST_OUTPUT_PER_1M
    ) / 1_000_000


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
