"""
engine/image/prompt_builder.py
Gemini 이미지 생성 프롬프트 빌더.

GLOBAL_STYLE_BLOCK, SECURITY_NEGATIVE_BLOCK_V1_1은
Public repo 노출 방지를 위해 Notion에서 런타임 로드.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# Fallback 상수 — Notion 로드 실패 시 사용 (최소 보안 수준)
_FALLBACK_STYLE = "Marvel + DC Hybrid Comic Style, ultra detailed, 8k, dark cinematic"
_FALLBACK_NEGATIVE = "No real people, no copyrighted characters, no nudity, comic style only"


def _get_style_block() -> str:
    try:
        from engine.common.notion_loader import load_image_prompt_blocks

        blocks = load_image_prompt_blocks()
        return blocks.get("GLOBAL_STYLE_BLOCK", _FALLBACK_STYLE)
    except Exception as exc:
        logger.warning("[prompt_builder] GLOBAL_STYLE_BLOCK Notion 로드 실패: %s", exc)
        return _FALLBACK_STYLE


def _get_negative_block() -> str:
    try:
        from engine.common.notion_loader import load_image_prompt_blocks

        blocks = load_image_prompt_blocks()
        return blocks.get("SECURITY_NEGATIVE_BLOCK_V1_1", _FALLBACK_NEGATIVE)
    except Exception as exc:
        logger.warning("[prompt_builder] SECURITY_NEGATIVE_BLOCK Notion 로드 실패: %s", exc)
        return _FALLBACK_NEGATIVE


@dataclass
class PanelPrompt:
    panel_idx: int
    char_ids: list[str]
    prompt_text: str
    ref_image_paths: list[Path]


def verify_negative_block_present(prompt_text: str) -> bool:
    """NEGATIVE 블록이 포함되어 있는지 확인."""
    return "NEGATIVE" in prompt_text.upper() or "No real people" in prompt_text


def build_panel_prompt(
    panel: dict,
    ref_paths: list[Path] | None = None,
) -> str:
    """
    단일 패널 Gemini 프롬프트 생성.

    Args:
        panel: EpisodeScript.panels[i] dict
        ref_paths: 캐릭터 REF 이미지 경로 목록

    Returns:
        완성된 프롬프트 문자열.
    """
    style_block = _get_style_block()
    negative_block = _get_negative_block()

    panel_type = panel.get("panel_type", "BATTLE")
    setting = panel.get("setting", "Financial district")
    action = panel.get("action", "")
    key_text = panel.get("key_text", "")
    narration = panel.get("narration", "")
    market_ref = panel.get("market_ref", "")
    camera = panel.get("camera", "MEDIUM")

    # 캐릭터 정보
    characters = panel.get("characters", [])
    char_desc_lines: list[str] = []
    for ch in characters:
        role = ch.get("role", "")
        char_id = ch.get("char_id", "")
        position = ch.get("position", "CENTER")
        char_desc_lines.append(f"{role.upper()} ({char_id}): position={position}")

    char_desc = "\n".join(char_desc_lines) if char_desc_lines else "No characters"

    lines = [
        "== STYLE LOCK ==",
        style_block,
        "== END STYLE LOCK ==",
        "",
        f"PANEL TYPE: {panel_type}",
        f"CAMERA: {camera}",
        f"SETTING: {setting}",
        f"ACTION: {action}",
        "",
        "CHARACTERS:",
        char_desc,
        "",
        f"KEY TEXT (Korean): {key_text}",
        f"NARRATION (Korean): {narration}",
        f"MARKET DATA: {market_ref}",
        "",
        negative_block,
    ]

    if ref_paths:
        lines.append(f"\nREF IMAGES: {len(ref_paths)} character reference(s) provided.")

    return "\n".join(lines)


def build_for_episode(episode_script: dict) -> list[PanelPrompt]:
    """
    에피소드 전체 패널 프롬프트 생성.

    Args:
        episode_script: EpisodeScript JSON dict

    Returns:
        PanelPrompt 리스트 (panels 순서 동일).
    """
    from engine.common.exceptions import CanonLockViolation
    from engine.image.ref_loader import get_refs_for_panel

    panels = episode_script.get("panels", [])
    panel_prompts: list[PanelPrompt] = []

    for panel in panels:
        idx = panel.get("idx", 0)
        char_ids = [ch.get("char_id", "") for ch in panel.get("characters", [])]

        # REF 이미지 로드 — char_ids 리스트 전체를 한 번에 전달
        ref_paths: list[Path] = []
        try:
            valid_char_ids = [c for c in char_ids if c]
            if valid_char_ids:
                ref_paths = get_refs_for_panel(valid_char_ids)
        except CanonLockViolation as exc:
            logger.error("[prompt_builder] Canon Lock 위반: %s", exc)
            raise

        prompt_text = build_panel_prompt(panel, ref_paths)
        panel_prompts.append(
            PanelPrompt(
                panel_idx=idx,
                char_ids=char_ids,
                prompt_text=prompt_text,
                ref_image_paths=ref_paths,
            )
        )

    logger.info("[prompt_builder] %d개 패널 프롬프트 생성 완료", len(panel_prompts))
    return panel_prompts
