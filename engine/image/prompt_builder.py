"""
engine/image/prompt_builder.py
Gemini 이미지 프롬프트 생성.

RULE 08: 모든 프롬프트에 SECURITY NEGATIVE BLOCK v1.1 자동 주입.
RULE 07: 모든 패널에 캐릭터 REF 이미지 경로 포함.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

# ── SECURITY NEGATIVE BLOCK v1.1 (불변 — 임의 수정 금지) ─────────────────────
SECURITY_NEGATIVE_BLOCK_V1_1 = """
STRICT NEGATIVE CONSTRAINTS — DO NOT GENERATE:
- No real people, no celebrity faces, no identifiable public figures
- No copyrighted characters (Marvel, DC, Disney, Pixar, Nintendo, etc.)
- No nudity, sexual content, or suggestive imagery
- No gore, explicit blood, or graphic violence
- No weapons aimed directly at the viewer
- No stock logos, brand marks, or trademark symbols
- No text overlay in image (text will be added in post-processing)
- No photorealism — comic book / cel shading style only
- No watermarks, signatures, or artist branding
- No real-world financial institution logos or building identifications
""".strip()

# ── 전역 스타일 고정 (Rendering Canon Lock) ───────────────────────────────────
GLOBAL_STYLE_BLOCK = """
STYLE REQUIREMENTS (Canon Lock):
- Line weight: bold, consistent
- Shading: cel shading only, no gradients
- Color palette: high-contrast, neon accents on dark backgrounds
- Influence: Korean manhwa / webtoon
- Hero gaze direction: RIGHT
- Villain gaze direction: LEFT
- Hero position: LEFT of frame
- Villain position: RIGHT of frame
- No direct camera eye contact (except COVER panel)
- Aspect ratio: 1:1 (1024x1024)
""".strip()


@dataclass
class PanelPrompt:
    """단일 패널 프롬프트 데이터."""

    panel_idx: int
    panel_type: str       # COVER / TENSION / BATTLE / CLIMAX / AFTERMATH / TEXT_CARD / DISCLAIMER
    prompt_text: str      # 전체 조립된 프롬프트
    ref_image_paths: list[Path] = field(default_factory=list)
    retry_fallback: str = "text_card"


def build_panel_prompt(
    panel_idx: int,
    panel_type: str,
    setting: str,
    action: str,
    camera: str,
    characters: list[dict],
    mood: str = "tense, dramatic",
) -> str:
    """
    패널 프롬프트 본문 조립 (Security Block / Style Block 포함).

    Args:
        panel_idx: 패널 번호 (1-based).
        panel_type: COVER / BATTLE 등.
        setting: 배경 묘사.
        action: 액션 묘사.
        camera: WIDE / MEDIUM / CLOSE_UP / DUTCH / LOW_ANGLE.
        characters: [{"char_id": ..., "role": ..., "position": ..., "name_en": ...}]
        mood: 분위기 묘사.

    Returns:
        전체 프롬프트 문자열 (Security Block 포함).
    """
    lines: list[str] = []

    # 스타일 헤더
    lines.append("Comic book style, Korean manhwa influence, cel shading.")
    lines.append(f"Panel {panel_idx} — Type: {panel_type}")
    lines.append("")

    # 캐릭터 묘사 (REF 이미지 순서와 일치해야 함)
    for i, char in enumerate(characters, start=1):
        role = char.get("role", "character")
        name = char.get("name_en", char.get("char_id", ""))
        position = char.get("position", "CENTER")
        lines.append(
            f"Character {i} [image {i}] ({role}): {name}. "
            f"Maintain EXACT face/costume/build from reference. "
            f"Position: {position} of frame."
        )
    lines.append("")

    # 씬 묘사
    lines.append(f"Setting: {setting}")
    lines.append(f"Action: {action}")
    lines.append(f"Camera: {camera}")
    lines.append(f"Mood/Lighting: {mood}")
    lines.append("")

    # 전역 스타일 블록
    lines.append(GLOBAL_STYLE_BLOCK)
    lines.append("")

    # SECURITY NEGATIVE BLOCK v1.1 (RULE 08 — 반드시 포함)
    lines.append(SECURITY_NEGATIVE_BLOCK_V1_1)

    return "\n".join(lines)


def build_for_episode(episode_script: dict) -> list[PanelPrompt]:
    """
    EpisodeScript dict에서 전체 패널 프롬프트 목록 생성.

    Args:
        episode_script: EpisodeScript.model_dump() 결과.

    Returns:
        PanelPrompt 리스트 (panels 순서 동일).
    """
    from engine.image.ref_loader import get_refs_for_panel, get_canon_name
    from engine.common.exceptions import CanonLockViolation

    panel_prompts: list[PanelPrompt] = []

    panels = episode_script.get("panels", [])
    for panel in panels:
        idx = panel.get("idx", 0)
        panel_type = panel.get("panel_type", "NORMAL")
        setting = panel.get("setting", "")
        action = panel.get("action", "")
        camera = panel.get("camera", "WIDE")

        # 캐릭터 목록 조립
        chars = panel.get("characters", [])
        char_details: list[dict] = []
        char_ids: list[str] = []

        for c in chars:
            char_id = c.get("char_id", "")
            char_ids.append(char_id)
            try:
                name_en = get_canon_name(char_id)
            except Exception:
                name_en = char_id
            char_details.append({
                "char_id": char_id,
                "role": c.get("role", "character"),
                "position": c.get("position", "CENTER"),
                "name_en": name_en,
            })

        # REF 이미지 경로 (CanonLockViolation은 상위로 전파)
        try:
            ref_paths = get_refs_for_panel(char_ids)
        except CanonLockViolation:
            raise  # 치명적 — 이미지 생성 전 중단

        # 프롬프트 조립
        prompt_text = build_panel_prompt(
            panel_idx=idx,
            panel_type=panel_type,
            setting=setting,
            action=action,
            camera=camera,
            characters=char_details,
        )

        panel_prompts.append(
            PanelPrompt(
                panel_idx=idx,
                panel_type=panel_type,
                prompt_text=prompt_text,
                ref_image_paths=ref_paths,
                retry_fallback="text_card",
            )
        )

    logger.info("[prompt_builder] %d개 패널 프롬프트 생성 완료", len(panel_prompts))
    return panel_prompts


def verify_negative_block_present(prompt: str) -> bool:
    """
    프롬프트에 SECURITY NEGATIVE BLOCK이 포함되어 있는지 검증.
    테스트 및 사전 검증용.
    """
    return "STRICT NEGATIVE CONSTRAINTS" in prompt and "No real people" in prompt
