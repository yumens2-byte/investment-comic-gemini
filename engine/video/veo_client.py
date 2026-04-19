"""
Veo 3.1 Fast API wrapper.

Model        : veo-3.1-fast-generate-preview
Resolution   : 720p (9:16 vertical) — B-2 conservative option
Duration     : 4/6/8 seconds per cut
Pricing (2026-04-19, Google official Gemini API):
  - 720p with audio    : $0.15/s
  - 720p without audio : $0.10/s  (33% savings)
  - 1080p with audio   : $0.15/s  (same price as 720p)
  - 1080p without audio: $0.10/s

Why Fast + 720p (B-2):
  - Lite model does NOT support `negative_prompt` (confirmed 2026-04-19 via 400 error)
  - Fast supports negative_prompt (MARVEL 3-layer defense)
  - 720p + 9:16 is the safest combo (no reported 1080p+9:16 compatibility issues)
  - ICG final distribution is Shorts/Reels — 720p is sufficient

Extension    : Not supported → use I2V chaining instead
SynthID      : Auto-watermarked (invisible)
Audio OFF    : We disable Veo audio; own TTS+BGM mixing in Phase V4

IMPORTANT: Veo retains generated videos on Google servers for 2 days only.
           Download immediately after generation.

Reference:
  - https://ai.google.dev/gemini-api/docs/video
  - https://ai.google.dev/gemini-api/docs/pricing
"""
import logging
import os
import time
from pathlib import Path
from typing import Optional

VERSION = "1.3.0"
MODEL = "veo-3.1-fast-generate-preview"
DEFAULT_RESOLUTION = "720p"
DEFAULT_ASPECT_RATIO = "9:16"
DEFAULT_DURATION_SEC = 8
DEFAULT_PERSON_GENERATION = "allow_adult"
DEFAULT_GENERATE_AUDIO = False  # ICG uses own TTS+BGM in Phase V4

# Pricing (USD per second, 2026-04-19 rates for Veo 3.1 Fast)
UNIT_PRICE_AUDIO_ON = 0.15   # Same for 720p and 1080p
UNIT_PRICE_AUDIO_OFF = 0.10  # Same for 720p and 1080p

# Polling configuration
POLL_INTERVAL_SEC = 15
POLL_TIMEOUT_SEC = 600  # 10 minutes — Veo typically takes 30~120s

logger = logging.getLogger(__name__)


class VeoGenerationError(RuntimeError):
    """Raised when Veo video generation fails (API error, timeout, policy violation)."""


class VeoTimeoutError(VeoGenerationError):
    """Raised when Veo operation polling exceeds POLL_TIMEOUT_SEC."""


def _unit_price(generate_audio: bool) -> float:
    """Return per-second cost based on audio setting.

    Resolution (720p/1080p) has no price impact for Fast tier.
    Audio inclusion is the only cost differentiator.
    """
    return UNIT_PRICE_AUDIO_ON if generate_audio else UNIT_PRICE_AUDIO_OFF


def _is_unknown_param_error(err: Exception, param_name: str) -> bool:
    """Detect the 'parameter isn't supported by this model' 400 error pattern."""
    msg = str(err).lower()
    return (
        "400" in msg
        and param_name.lower() in msg
        and ("not supported" in msg or "isn't supported" in msg or "invalid_argument" in msg)
    )


class VeoClient:
    """Thin wrapper around google-genai's generate_videos operation."""

    def __init__(self):
        try:
            from google import genai
        except ImportError as e:
            raise RuntimeError(
                "google-genai package not installed. Run: pip install google-genai"
            ) from e

        api_key = os.environ.get("GEMINI_API_SUB_PAY_KEY")
        if not api_key:
            raise RuntimeError("GEMINI_API_SUB_PAY_KEY env variable not set")

        self._genai = genai
        self.client = genai.Client(api_key=api_key)
        logger.info(f"[VeoClient] v{VERSION} initialized (model={MODEL})")

    def _submit_operation(self, prompt: str, config_kwargs: dict):
        """Submit the generate_videos operation with graceful fallback for unsupported params.

        If the API rejects `generate_audio` (e.g., Gemini SDK param name mismatch or model
        not honoring it), remove the param and retry once. Same for any other optional param
        that might not be supported.
        """
        from google.genai import types

        # First attempt: full config
        try:
            op = self.client.models.generate_videos(
                model=MODEL,
                prompt=prompt,
                config=types.GenerateVideosConfig(**config_kwargs),
            )
            return op
        except Exception as e:
            # Check if the error is about `generate_audio` specifically
            if "generate_audio" in config_kwargs and _is_unknown_param_error(e, "generate_audio"):
                logger.warning(
                    f"[VeoClient] `generate_audio` not supported — removing and retrying. "
                    f"Cost will be $0.15/s instead of $0.10/s. Error: {e}"
                )
                fallback_config = {k: v for k, v in config_kwargs.items() if k != "generate_audio"}
                op = self.client.models.generate_videos(
                    model=MODEL,
                    prompt=prompt,
                    config=types.GenerateVideosConfig(**fallback_config),
                )
                return op
            # Any other error: re-raise
            raise

    def generate_text_to_video(
        self,
        prompt: str,
        output_path: str,
        duration_sec: int = DEFAULT_DURATION_SEC,
        resolution: str = DEFAULT_RESOLUTION,
        aspect_ratio: str = DEFAULT_ASPECT_RATIO,
        negative_prompt: Optional[str] = None,
        person_generation: str = DEFAULT_PERSON_GENERATION,
        generate_audio: bool = DEFAULT_GENERATE_AUDIO,
    ) -> dict:
        """
        Text-to-Video generation (used for cut 1 in the ICG trailer pipeline).

        Args:
            prompt           : Scene description text
            output_path      : Local path to save the resulting mp4
            duration_sec     : 4, 6, or 8
            resolution       : "720p" or "1080p"
            aspect_ratio     : "9:16" (vertical) or "16:9" (landscape)
            negative_prompt  : Text describing what NOT to generate (MARVEL defense — Fast公式 supported)
            person_generation: "allow_adult" | "allow_all" | "dont_allow"
            generate_audio   : False = $0.10/s, True = $0.15/s (ICG default False)

        Returns:
            dict with video_uri, duration_sec, cost_usd, generation_ms, file_size_mb,
                 resolution, aspect_ratio, audio_generated

        Raises:
            VeoGenerationError on API errors
            VeoTimeoutError on polling timeout
        """
        logger.info(
            f"[VeoClient] T2V start: model={MODEL} resolution={resolution} "
            f"aspect={aspect_ratio} duration={duration_sec}s audio={generate_audio} "
            f"prompt_len={len(prompt)}"
        )
        if negative_prompt:
            logger.debug(
                f"[VeoClient] negative_prompt length: {len(negative_prompt)}"
            )

        start_ts = time.time()
        config_kwargs = {
            "aspect_ratio": aspect_ratio,
            "resolution": resolution,
            "duration_seconds": duration_sec,
            "person_generation": person_generation,
            "number_of_videos": 1,
            "generate_audio": generate_audio,
        }
        if negative_prompt:
            config_kwargs["negative_prompt"] = negative_prompt

        # Submit with fallback for unsupported params
        try:
            operation = self._submit_operation(prompt, config_kwargs)
        except Exception as e:
            raise VeoGenerationError(f"Veo API call failed: {e}") from e

        # Poll for completion
        poll_count = 0
        while not operation.done:
            if (time.time() - start_ts) > POLL_TIMEOUT_SEC:
                raise VeoTimeoutError(
                    f"Veo operation did not complete within {POLL_TIMEOUT_SEC}s"
                )
            poll_count += 1
            logger.info(
                f"[VeoClient] polling ({poll_count}x, elapsed={int(time.time() - start_ts)}s)..."
            )
            time.sleep(POLL_INTERVAL_SEC)
            try:
                operation = self.client.operations.get(operation)
            except Exception as e:
                raise VeoGenerationError(f"Operation polling failed: {e}") from e

        # Check for response/error
        if not getattr(operation, "response", None):
            err = getattr(operation, "error", None)
            raise VeoGenerationError(
                f"Veo generation failed without response. error={err}"
            )

        # Extract video
        try:
            generated_video = operation.response.generated_videos[0]
        except (AttributeError, IndexError) as e:
            raise VeoGenerationError(f"No generated_videos in response: {e}") from e

        # Download
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.client.files.download(file=generated_video.video)
            generated_video.video.save(str(out))
        except Exception as e:
            raise VeoGenerationError(f"Video download/save failed: {e}") from e

        if not out.exists() or out.stat().st_size == 0:
            raise VeoGenerationError(f"Downloaded file empty or missing: {out}")

        elapsed_ms = int((time.time() - start_ts) * 1000)
        cost_usd = _unit_price(generate_audio) * duration_sec
        file_size_mb = out.stat().st_size / 1024 / 1024
        logger.info(
            f"[VeoClient] T2V done: path={out} size={file_size_mb:.2f}MB "
            f"elapsed={elapsed_ms}ms cost=${cost_usd:.4f} audio={generate_audio}"
        )
        return {
            "video_uri": str(out),
            "duration_sec": duration_sec,
            "cost_usd": round(cost_usd, 4),
            "generation_ms": elapsed_ms,
            "file_size_mb": round(file_size_mb, 2),
            "resolution": resolution,
            "aspect_ratio": aspect_ratio,
            "audio_generated": generate_audio,
        }

    def generate_image_to_video(
        self,
        prompt: str,
        start_frame_path: str,
        output_path: str,
        duration_sec: int = DEFAULT_DURATION_SEC,
        resolution: str = DEFAULT_RESOLUTION,
        aspect_ratio: str = DEFAULT_ASPECT_RATIO,
        negative_prompt: Optional[str] = None,
        person_generation: str = DEFAULT_PERSON_GENERATION,
        generate_audio: bool = DEFAULT_GENERATE_AUDIO,
    ) -> dict:
        """
        Image-to-Video generation (used for cut 2, 3 in I2V chain).

        Phase V2 MVP Phase 1 scope: T2V only.
        I2V implementation deferred to Phase V2 MVP Phase 2.
        """
        raise NotImplementedError(
            "I2V is deferred to V2 MVP Phase 2. "
            "Phase 1 scope: T2V cut1 only."
        )
