"""
Veo 3.1 Fast API wrapper.

Model        : veo-3.1-fast-generate-preview
Resolution   : 720p (9:16 vertical) — B-2 conservative option
Duration     : 4/6/8 seconds per cut
Pricing (2026-04-19, Google official Gemini API):
  - Veo 3.1 Fast (720p or 1080p, with audio) : $0.15/s
  - Veo 3.1 Fast (720p or 1080p, audio off)  : $0.10/s (Vertex AI only — Gemini API does NOT honor)

Why `generate_audio` parameter removed in v1.3.1:
  - GenerateVideosConfig SDK field exists (GitHub Issue #1559) but
    `veo-3.1-fast-generate-preview` Gemini API returned 400 on 2026-04-20 run #6.
  - A1 decision: remove param entirely, let Veo default (audio ON) apply.
  - Phase V4 will strip audio via ffmpeg -an during assembly.
  - Cost locked at $0.15/s × 8s = $1.20 per cut.

Extension    : Not supported → use I2V chaining instead
SynthID      : Auto-watermarked (invisible)

IMPORTANT: Veo retains generated videos on Google servers for 2 days only.
           Download immediately after generation.

Reference:
  - https://ai.google.dev/gemini-api/docs/video
  - https://ai.google.dev/gemini-api/docs/pricing
  - https://github.com/googleapis/python-genai (official SDK)
"""
import logging
import os
import time
from pathlib import Path
from typing import Optional

VERSION = "1.3.1"
MODEL = "veo-3.1-fast-generate-preview"
DEFAULT_RESOLUTION = "720p"
DEFAULT_ASPECT_RATIO = "9:16"
DEFAULT_DURATION_SEC = 8
DEFAULT_PERSON_GENERATION = "allow_adult"

# Pricing (USD per second, 2026-04-19 rates for Veo 3.1 Fast via Gemini API)
# NOTE: Audio-off discount ($0.10/s) is Vertex AI only; Gemini API charges $0.15/s regardless.
UNIT_PRICE = 0.15

# Polling configuration
POLL_INTERVAL_SEC = 15
POLL_TIMEOUT_SEC = 600  # 10 minutes — Veo typically takes 30~120s

logger = logging.getLogger(__name__)


class VeoGenerationError(RuntimeError):
    """Raised when Veo video generation fails (API error, timeout, policy violation)."""


class VeoTimeoutError(VeoGenerationError):
    """Raised when Veo operation polling exceeds POLL_TIMEOUT_SEC."""


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

    def generate_text_to_video(
        self,
        prompt: str,
        output_path: str,
        duration_sec: int = DEFAULT_DURATION_SEC,
        resolution: str = DEFAULT_RESOLUTION,
        aspect_ratio: str = DEFAULT_ASPECT_RATIO,
        negative_prompt: Optional[str] = None,
        person_generation: str = DEFAULT_PERSON_GENERATION,
        generate_audio: bool = False,
    ) -> dict:
        """
        Text-to-Video generation (used for cut 1 in the ICG trailer pipeline).

        Args:
            prompt           : Scene description text
            output_path      : Local path to save the resulting mp4
            duration_sec     : 4, 6, or 8
            resolution       : "720p" or "1080p"
            aspect_ratio     : "9:16" (vertical) or "16:9" (landscape)
            negative_prompt  : What NOT to generate (Fast officially supports)
            person_generation: "allow_adult" | "allow_all" | "dont_allow"
            generate_audio   : PARAMETER DEPRECATED AT API LEVEL. Kept for API compatibility.
                               Veo default (audio ON) is applied regardless of this value.
                               Audio will be stripped in Phase V4 ffmpeg assembly if needed.

        Returns:
            dict with video_uri, duration_sec, cost_usd, generation_ms, file_size_mb,
                 resolution, aspect_ratio, audio_generated

        Raises:
            VeoGenerationError on API errors
            VeoTimeoutError on polling timeout
        """
        from google.genai import types

        # Honor the interface but warn if caller expected audio-off behavior
        if generate_audio is False:
            logger.warning(
                "[VeoClient] generate_audio=False requested but NOT applied — "
                "Gemini API charges $0.15/s for Fast regardless. "
                "Audio track will be included in output mp4; strip via ffmpeg -an if needed."
            )

        logger.info(
            f"[VeoClient] T2V start: model={MODEL} resolution={resolution} "
            f"aspect={aspect_ratio} duration={duration_sec}s "
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
        }
        if negative_prompt:
            config_kwargs["negative_prompt"] = negative_prompt

        # Submit operation (no fallback logic — param set is minimal and SDK-verified)
        try:
            operation = self.client.models.generate_videos(
                model=MODEL,
                prompt=prompt,
                config=types.GenerateVideosConfig(**config_kwargs),
            )
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
        cost_usd = UNIT_PRICE * duration_sec
        file_size_mb = out.stat().st_size / 1024 / 1024
        logger.info(
            f"[VeoClient] T2V done: path={out} size={file_size_mb:.2f}MB "
            f"elapsed={elapsed_ms}ms cost=${cost_usd:.4f}"
        )
        return {
            "video_uri": str(out),
            "duration_sec": duration_sec,
            "cost_usd": round(cost_usd, 4),
            "generation_ms": elapsed_ms,
            "file_size_mb": round(file_size_mb, 2),
            "resolution": resolution,
            "aspect_ratio": aspect_ratio,
            "audio_generated": True,  # Veo default ON — strip via ffmpeg in Phase V4
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
        generate_audio: bool = False,
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
