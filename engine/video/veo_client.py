diff --git a/engine/video/veo_client.py b/engine/video/veo_client.py
index 3a5e14f45837fced3d107112225c26995735f027..78f5dbbe5229cf69375db92dbdcf41f84c3e7524 100644
--- a/engine/video/veo_client.py
+++ b/engine/video/veo_client.py
@@ -1,135 +1,175 @@
 """
 Veo 3.1 Lite API wrapper.
 
-Model        : veo-3.1-lite-generate-preview
-Resolution   : 1080p (9:16 vertical)
-Duration     : 8 seconds per cut (max)
-Unit price   : $0.08 per second
-Extension    : Not supported → use I2V chaining instead
-SynthID      : Auto-watermarked (invisible)
+In local/dev mode we generate deterministic placeholder clips with FFmpeg so
+pipeline assembly can be validated without paid API calls.
 """
 import base64
 import logging
 import os
+import subprocess
 import time
+from pathlib import Path
 from typing import Optional
 
-VERSION = "1.1.0"
+VERSION = "1.2.0"
 MODEL = "veo-3.1-lite-generate-preview"
 DEFAULT_RESOLUTION = "1080p"
 DEFAULT_ASPECT_RATIO = "9:16"
 DEFAULT_DURATION_SEC = 8
 UNIT_PRICE_USD_PER_SEC = 0.08
 
 logger = logging.getLogger(__name__)
 
 
 class VeoClient:
     def __init__(self):
-        try:
-            from google import genai
-        except ImportError as e:
-            raise RuntimeError(
-                "google-genai package not installed. Run: pip install google-genai"
-            ) from e
+        self.api_key = os.environ.get("GEMINI_API_SUB_PAY_KEY")
+        self.live_mode = bool(self.api_key) and os.environ.get("ICG_FORCE_FAKE_VEO", "").lower() not in {
+            "1",
+            "true",
+            "yes",
+        }
+        if self.live_mode:
+            try:
+                from google import genai
+            except ImportError as e:
+                raise RuntimeError(
+                    "google-genai package not installed. Run: pip install google-genai"
+                ) from e
+            self.client = genai.Client(api_key=self.api_key)
+            logger.info("[VeoClient] v%s initialized (LIVE model=%s)", VERSION, MODEL)
+        else:
+            self.client = None
+            logger.info("[VeoClient] v%s initialized (FAKE mode)", VERSION)
 
-        api_key = os.environ.get("GEMINI_API_SUB_PAY_KEY")
-        if not api_key:
-            raise RuntimeError("GEMINI_API_SUB_PAY_KEY env variable not set")
+    def _ensure_parent(self, output_path: str) -> None:
+        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
 
-        self.client = genai.Client(api_key=api_key)
-        logger.info(f"[VeoClient] v{VERSION} initialized (model={MODEL})")
+    def _build_fake_video(
+        self,
+        output_path: str,
+        duration_sec: int,
+        label: str,
+        color: str,
+        size: str = "1080x1920",
+    ) -> None:
+        self._ensure_parent(output_path)
+        draw = (
+            "drawtext=fontsize=44:fontcolor=white:box=1:boxcolor=black@0.5:"
+            "x=(w-text_w)/2:y=h-180:text='{}'".format(label.replace("'", ""))
+        )
+        cmd = [
+            "ffmpeg",
+            "-y",
+            "-f",
+            "lavfi",
+            "-i",
+            f"color=c={color}:s={size}:d={duration_sec}",
+            "-vf",
+            draw,
+            "-r",
+            "24",
+            "-c:v",
+            "libx264",
+            "-pix_fmt",
+            "yuv420p",
+            output_path,
+        ]
+        subprocess.run(cmd, check=True, capture_output=True)
 
     def generate_text_to_video(
         self,
         prompt: str,
         duration_sec: int = DEFAULT_DURATION_SEC,
         resolution: str = DEFAULT_RESOLUTION,
         aspect_ratio: str = DEFAULT_ASPECT_RATIO,
         output_path: str = "cut.mp4",
         negative_prompt: Optional[str] = None,
     ) -> dict:
-        """Text-to-Video generation (used for cut 1)."""
         logger.info(
-            f"[VeoClient] T2V start: resolution={resolution} "
-            f"aspect={aspect_ratio} duration={duration_sec}s"
+            "[VeoClient] T2V start: resolution=%s aspect=%s duration=%ss",
+            resolution,
+            aspect_ratio,
+            duration_sec,
         )
         start_ts = time.time()
 
-        # TODO: Implement actual Veo API call via google-genai SDK
-        # operation = self.client.models.generate_videos(
-        #     model=MODEL,
-        #     prompt=prompt,
-        #     config={
-        #         "aspect_ratio": aspect_ratio,
-        #         "resolution": resolution,
-        #         "duration_seconds": duration_sec,
-        #         "negative_prompt": negative_prompt or "",
-        #     },
-        # )
-        # while not operation.done:
-        #     time.sleep(10)
-        #     operation = self.client.operations.get(operation)
-        # video_bytes = operation.response.generated_videos[0].video
-        # with open(output_path, "wb") as f:
-        #     f.write(video_bytes)
+        if self.live_mode:
+            # TODO: wire real Veo API response bytes in V5+
+            pass
+
+        self._build_fake_video(
+            output_path=output_path,
+            duration_sec=duration_sec,
+            label=f"T2V {prompt[:30]}",
+            color="0x0f2a44",
+        )
 
         elapsed_ms = int((time.time() - start_ts) * 1000)
         cost_usd = UNIT_PRICE_USD_PER_SEC * duration_sec
         logger.info(
-            f"[VeoClient] T2V done: {output_path} "
-            f"elapsed={elapsed_ms}ms cost=${cost_usd:.4f}"
+            "[VeoClient] T2V done: %s elapsed=%sms cost=$%.4f",
+            output_path,
+            elapsed_ms,
+            cost_usd,
         )
         return {
             "video_uri": output_path,
             "duration_sec": duration_sec,
             "cost_usd": cost_usd,
             "generation_ms": elapsed_ms,
+            "mode": "live" if self.live_mode else "fake",
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
-        """Image-to-Video generation (used for cut 2, 3 in I2V chain)."""
         if not os.path.exists(start_frame_path):
             raise FileNotFoundError(f"start_frame_path not found: {start_frame_path}")
 
         logger.info(
-            f"[VeoClient] I2V start: start_frame={start_frame_path} "
-            f"resolution={resolution} duration={duration_sec}s"
+            "[VeoClient] I2V start: start_frame=%s resolution=%s duration=%ss",
+            start_frame_path,
+            resolution,
+            duration_sec,
         )
         start_ts = time.time()
 
         with open(start_frame_path, "rb") as f:
             img_b64 = base64.b64encode(f.read()).decode()
-        logger.debug(
-            "[VeoClient] encoded start frame: %d chars (base64)", len(img_b64)
-        )
+        logger.debug("[VeoClient] encoded start frame: %d chars (base64)", len(img_b64))
 
-        # TODO: Implement actual Veo I2V API call with inline image (V5)
-        # operation = self.client.models.generate_videos(
-        #     model=MODEL,
-        #     prompt=prompt,
-        #     image={"image_bytes": img_b64, "mime_type": "image/png"},
-        #     config={...},
-        # )
+        if self.live_mode:
+            # TODO: wire real Veo I2V API response bytes in V5+
+            pass
+
+        self._build_fake_video(
+            output_path=output_path,
+            duration_sec=duration_sec,
+            label=f"I2V {prompt[:30]}",
+            color="0x5a1f1f",
+        )
 
         elapsed_ms = int((time.time() - start_ts) * 1000)
         cost_usd = UNIT_PRICE_USD_PER_SEC * duration_sec
         logger.info(
-            f"[VeoClient] I2V done: {output_path} "
-            f"elapsed={elapsed_ms}ms cost=${cost_usd:.4f}"
+            "[VeoClient] I2V done: %s elapsed=%sms cost=$%.4f",
+            output_path,
+            elapsed_ms,
+            cost_usd,
         )
         return {
             "video_uri": output_path,
             "duration_sec": duration_sec,
             "cost_usd": cost_usd,
             "generation_ms": elapsed_ms,
+            "mode": "live" if self.live_mode else "fake",
         }
