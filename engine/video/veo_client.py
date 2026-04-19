"""
Veo 3.1 Lite API wrapper.

Model        : veo-3.1-lite-generate-preview
Resolution   : 1080p (9:16 vertical)
Duration     : 8 seconds per cut (max)
Unit price   : $0.08 per second
Extension    : Not supported → use I2V chaining instead
SynthID      : Auto-watermarked (invisible)
"""
import base64
import logging
import os
import time
from typing import Optional

VERSION = "1.0.0"
MODEL = "veo-3.1-lite-generate-preview"
DEFAULT_RESOLUTION = "1080p"
DEFAULT_ASPECT_RATIO = "9:16"
DEFAULT_DURATION_SEC = 8
UNIT_PRICE_USD_PER_SEC = 0.08

logger = logging.getLogger(__name__)


class VeoClient:
    def __init__(self):
        try:
            from google import genai
        except ImportError as e:
            raise RuntimeError(
                "google-genai package not installed. Run: pip install google-genai"
            ) from e

        api_key = os.environ.get("GEMINI_API_PAY_KEY")
        if not api_key:
            raise RuntimeError("GEMINI_API_PAY_KEY env variable not set")

        self.client = genai.Client(api_key=api_key)
        logger.info(f"[VeoClient] v{VERSION} initialized (model={MODEL})")

    def generate_text_to_video(
        self,
        prompt: str,
        duration_sec: int = DEFAULT_DURATION_SEC,
        resolution: str = DEFAULT_RESOLUTION,
        aspect_ratio: str = DEFAULT_ASPECT_RATIO,
        output_path: str = "cut.mp4",
        negative_prompt: Optional[str] = None,
    ) -> dict:
        """Text-to-Video generation (used for cut 1)."""
        logger.info(
            f"[VeoClient] T2V start: resolution={resolution} "
            f"aspect={aspect_ratio} duration={duration_sec}s"
        )
        start_ts = time.time()

        # TODO: Implement actual Veo API call via google-genai SDK
        # operation = self.client.models.generate_videos(
        #     model=MODEL,
        #     prompt=prompt,
        #     config={
        #         "aspect_ratio": aspect_ratio,
        #         "resolution": resolution,
        #         "duration_seconds": duration_sec,
        #         "negative_prompt": negative_prompt or "",
        #     },
        # )
        # while not operation.done:
        #     time.sleep(10)
        #     operation = self.client.operations.get(operation)
        # video_bytes = operation.response.generated_videos[0].video
        # with open(output_path, "wb") as f:
        #     f.write(video_bytes)

        elapsed_ms = int((time.time() - start_ts) * 1000)
        cost_usd = UNIT_PRICE_USD_PER_SEC * duration_sec
        logger.info(
            f"[VeoClient] T2V done: {output_path} "
            f"elapsed={elapsed_ms}ms cost=${cost_usd:.4f}"
        )
        return {
            "video_uri": output_path,
            "duration_sec": duration_sec,
            "cost_usd": cost_usd,
            "generation_ms": elapsed_ms,
        }

    def generate_image_to_video(
        self,
        prompt: str,
        start_frame_path: str,
        duration_sec: int = DEFAULT_DURATION_SEC,
        resolution: str = DEFAULT_RESOLUTION,
        aspect_ratio: str = DEFAULT_ASPECT_RATIO,
        output_path: str = "cut.mp4",
        negative_prompt: Optional[str] = None,
    ) -> dict:
        """Image-to-Video generation (used for cut 2, 3 in I2V chain)."""
        if not os.path.exists(start_frame_path):
            raise FileNotFoundError(f"start_frame_path not found: {start_frame_path}")

        logger.info(
            f"[VeoClient] I2V start: start_frame={start_frame_path} "
            f"resolution={resolution} duration={duration_sec}s"
        )
        start_ts = time.time()

        with open(start_frame_path, "rb") as f:
            img_b64 = base64.b64encode(f.read()).decode()
        logger.debug(
            "[VeoClient] encoded start frame: %d chars (base64)", len(img_b64)
        )

        # TODO: Implement actual Veo I2V API call with inline image (V5)
        # operation = self.client.models.generate_videos(
        #     model=MODEL,
        #     prompt=prompt,
        #     image={"image_bytes": img_b64, "mime_type": "image/png"},
        #     config={...},
        # )

        elapsed_ms = int((time.time() - start_ts) * 1000)
        cost_usd = UNIT_PRICE_USD_PER_SEC * duration_sec
        logger.info(
            f"[VeoClient] I2V done: {output_path} "
            f"elapsed={elapsed_ms}ms cost=${cost_usd:.4f}"
        )
        return {
            "video_uri": output_path,
            "duration_sec": duration_sec,
            "cost_usd": cost_usd,
            "generation_ms": elapsed_ms,
        }
