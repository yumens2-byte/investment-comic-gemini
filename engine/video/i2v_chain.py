"""
I2V Chaining Orchestrator.

Veo 3.1 Lite does NOT support Extension (continuous generation).
To maintain character/scene continuity across 3 cuts, we chain via:

  Cut 1 (T2V) → last frame → Cut 2 (I2V) → last frame → Cut 3 (I2V)

The last frame of cut N is injected as the start frame of cut N+1,
ensuring smooth visual transitions and character consistency.
"""
import logging
from pathlib import Path
from typing import List

from engine.video.veo_client import VeoClient
from engine.video.frame_extractor import extract_last_frame

VERSION = "1.0.0"
logger = logging.getLogger(__name__)


def run_i2v_chain(
    cut_prompts: List[str],
    output_dir: str = "output/videos/today",
    resolution: str = "1080p",
    aspect_ratio: str = "9:16",
    duration_sec: int = 8,
) -> dict:
    """
    Run 3-cut I2V chain.

    Args:
        cut_prompts: List of exactly 3 prompts [cut1, cut2, cut3]
        output_dir: Directory to save cut mp4 files and intermediate frames
        resolution: Veo resolution (1080p recommended)
        aspect_ratio: Veo aspect ratio (9:16 for Shorts)
        duration_sec: Per-cut duration (8s max for Veo 3.1 Lite)

    Returns:
        dict with keys:
            cut_paths      : [cut1.mp4, cut2.mp4, cut3.mp4]
            frame_paths    : [cut1_last.png, cut2_last.png]
            total_cost_usd : sum of per-cut costs
            total_ms       : sum of per-cut generation times
    """
    assert len(cut_prompts) == 3, f"Requires exactly 3 cut prompts, got {len(cut_prompts)}"

    logger.info(f"[i2v_chain] v{VERSION} starting 3-cut chain")
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    veo = VeoClient()
    cut_paths = []
    frame_paths = []
    total_cost = 0.0
    total_ms = 0

    # ─ Cut 1: Text-to-Video ────────────────────────────────────
    cut1_path = f"{output_dir}/cut1.mp4"
    logger.info(f"[i2v_chain] Cut 1 (T2V) start")
    r1 = veo.generate_text_to_video(
        prompt=cut_prompts[0],
        duration_sec=duration_sec,
        resolution=resolution,
        aspect_ratio=aspect_ratio,
        output_path=cut1_path,
    )
    cut_paths.append(cut1_path)
    total_cost += r1["cost_usd"]
    total_ms += r1["generation_ms"]

    # Extract last frame of cut 1
    cut1_last_frame = f"{output_dir}/cut1_last.png"
    extract_last_frame(cut1_path, cut1_last_frame)
    frame_paths.append(cut1_last_frame)

    # ─ Cut 2: Image-to-Video from cut1 last frame ──────────────
    cut2_path = f"{output_dir}/cut2.mp4"
    logger.info(f"[i2v_chain] Cut 2 (I2V from cut1_last) start")
    r2 = veo.generate_image_to_video(
        prompt=cut_prompts[1],
        start_frame_path=cut1_last_frame,
        duration_sec=duration_sec,
        resolution=resolution,
        aspect_ratio=aspect_ratio,
        output_path=cut2_path,
    )
    cut_paths.append(cut2_path)
    total_cost += r2["cost_usd"]
    total_ms += r2["generation_ms"]

    # Extract last frame of cut 2
    cut2_last_frame = f"{output_dir}/cut2_last.png"
    extract_last_frame(cut2_path, cut2_last_frame)
    frame_paths.append(cut2_last_frame)

    # ─ Cut 3: Image-to-Video from cut2 last frame ──────────────
    cut3_path = f"{output_dir}/cut3.mp4"
    logger.info(f"[i2v_chain] Cut 3 (I2V from cut2_last) start")
    r3 = veo.generate_image_to_video(
        prompt=cut_prompts[2],
        start_frame_path=cut2_last_frame,
        duration_sec=duration_sec,
        resolution=resolution,
        aspect_ratio=aspect_ratio,
        output_path=cut3_path,
    )
    cut_paths.append(cut3_path)
    total_cost += r3["cost_usd"]
    total_ms += r3["generation_ms"]

    logger.info(
        f"[i2v_chain] 3-cut chain complete: "
        f"total_cost=${total_cost:.4f} total_ms={total_ms}"
    )

    return {
        "cut_paths": cut_paths,
        "frame_paths": frame_paths,
        "total_cost_usd": total_cost,
        "total_ms": total_ms,
    }
