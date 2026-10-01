"""
engine/assembly/pil_composer.py
패널 이미지 위에 텍스트 오버레이 → 1080×1350 슬라이드 조립.

레이아웃 (이미지 위 오버레이 방식):
  - 이미지: 1080×1350 전체 크기로 리사이즈
  - 텍스트: 하단 300px 영역에 반투명 다크 박스 오버레이
    ┌────────────────────────────────┐ ← 0
    │     Gemini 순수 이미지          │ (1080x1350)
    │     (텍스트 없음)               │
    │                               │
    ├─ 반투명 오버레이 박스 ──────────┤ ← 1050
    │  key_text (말풍선 스타일)       │
    │  narration (흰색 소자)         │
    │  market_ref (amber 하단)       │
    └────────────────────────────────┘ ← 1350

폰트:
  - GitHub Actions: fonts-noto-cjk → /usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc
  - 없으면 PIL 기본 폰트 fallback
"""

from __future__ import annotations

import logging
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

# 슬라이드 크기
SLIDE_W = 1080
SLIDE_H = 1350

# 오버레이 영역
OVERLAY_Y = 1050  # 오버레이 시작 Y (하단 300px)
OVERLAY_H = 300  # 오버레이 높이
OVERLAY_ALPHA = 200  # 반투명도 (0=투명, 255=불투명)

# 색상
BG_DARK = (10, 15, 25)
TEXT_WHITE = (230, 240, 255)
TEXT_CYAN = (6, 182, 212)
TEXT_AMBER = (245, 158, 11)
TEXT_LIGHT_GRAY = (160, 180, 200)
OVERLAY_COLOR = (8, 12, 22)

# 폰트 경로 우선순위
_FONT_PATHS = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
    "/System/Library/Fonts/AppleSDGothicNeo.ttc",  # macOS
    "/assets/fonts/NotoSansCJK-Bold.ttc",
]


def _get_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """사용 가능한 폰트 반환 (fallback: 기본 폰트)."""
    for path in _FONT_PATHS:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    logger.warning("[pil_composer] NotoSansCJK 없음 → 기본 폰트 사용")
    return ImageFont.load_default()


def _draw_overlay(draw: ImageDraw.ImageDraw, slide: Image.Image) -> None:
    """
    하단 300px 영역에 반투명 오버레이 박스 합성.
    RGBA blend 방식으로 반투명 처리.
    """
    overlay = Image.new("RGBA", (SLIDE_W, OVERLAY_H), (*OVERLAY_COLOR, OVERLAY_ALPHA))
    slide.paste(overlay, (0, OVERLAY_Y), mask=overlay)


def compose_slide(
    panel_image_path: Path | None,
    key_text: str,
    narration: str,
    panel_idx: int,
    panel_type: str,
    market_ref: str | None = None,
    output_path: Path | None = None,
) -> Path:
    """
    단일 슬라이드 조립 (오버레이 방식).

    Args:
        panel_image_path: Gemini 생성 패널 이미지 (None이면 text_card fallback).
        key_text: 말풍선 대사 (40자 이내).
        narration: 내레이션 텍스트 (120자 이내).
        panel_idx: 패널 번호.
        panel_type: 패널 타입.
        market_ref: 시장 지표 참조 텍스트.
        output_path: 저장 경로.

    Returns:
        저장된 슬라이드 파일 경로.
    """
    if output_path is None:
        output_path = Path(f"/tmp/S{panel_idx}.png")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if panel_type == "DISCLAIMER":
        return _compose_disclaimer_slide(output_path, narration)

    if panel_image_path is None or not panel_image_path.exists():
        return _compose_text_card(output_path, key_text, narration, panel_idx, market_ref)

    return _compose_image_slide(
        output_path, panel_image_path, key_text, narration, panel_idx, market_ref
    )


def _compose_image_slide(
    output_path: Path,
    panel_image_path: Path,
    key_text: str,
    narration: str,
    panel_idx: int,
    market_ref: str | None,
) -> Path:
    """이미지 전체(1080x1350) + 하단 반투명 텍스트 오버레이."""
    try:
        panel_img = Image.open(panel_image_path).convert("RGBA")
        # 전체 슬라이드 크기로 리사이즈 (1080x1350)
        panel_img = panel_img.resize((SLIDE_W, SLIDE_H), Image.LANCZOS)
    except Exception as exc:
        logger.warning("[pil_composer] 이미지 로드 실패: %s", exc)
        return _compose_text_card(output_path, key_text, narration, panel_idx, market_ref)

    # RGBA 슬라이드로 변환
    slide = panel_img.copy()

    # 반투명 오버레이 합성
    _draw_overlay(ImageDraw.Draw(slide), slide)

    # 텍스트 드로우 (RGBA 모드)
    draw = ImageDraw.Draw(slide)
    _draw_text_overlay(draw, key_text, narration, panel_idx, market_ref)

    # RGB로 변환 후 저장
    slide.convert("RGB").save(str(output_path), "PNG", optimize=True)
    return output_path


def _draw_text_overlay(
    draw: ImageDraw.ImageDraw,
    key_text: str,
    narration: str,
    panel_idx: int,
    market_ref: str | None,
) -> None:
    """
    오버레이 박스 안에 텍스트 배치.

    레이아웃 (Y 기준 OVERLAY_Y=1050):
      +15  패널 번호 (우측)
      +18  key_text (대사, 34px bold)
      +75  narration (24px, 최대 2줄)
      +150 narration 2번째 줄
      +245 market_ref (amber, 22px)
    """
    y = OVERLAY_Y

    # 패널 번호 (우상단)
    num_font = _get_font(24)
    draw.text((SLIDE_W - 55, y + 12), f"#{panel_idx}", font=num_font, fill=TEXT_CYAN)

    # key_text — 말풍선 스타일 (대사, 진하게)
    key_font = _get_font(34)
    wrapped_key = textwrap.fill(key_text or "", width=24)
    draw.text((28, y + 16), wrapped_key, font=key_font, fill=TEXT_WHITE)

    # narration — 작은 글씨, 최대 3줄
    narr_font = _get_font(22)
    wrapped_narr = textwrap.fill(narration or "", width=42)
    draw.text((28, y + 108), wrapped_narr, font=narr_font, fill=TEXT_LIGHT_GRAY)

    # market_ref — amber, 하단
    if market_ref:
        ref_font = _get_font(20)
        draw.text((28, y + OVERLAY_H - 38), market_ref[:80], font=ref_font, fill=TEXT_AMBER)


def _compose_text_card(
    output_path: Path,
    key_text: str,
    narration: str,
    panel_idx: int,
    market_ref: str | None,
) -> Path:
    """이미지 없을 때 전체 텍스트 카드 (fallback)."""
    slide = Image.new("RGB", (SLIDE_W, SLIDE_H), (5, 10, 20))
    draw = ImageDraw.Draw(slide)

    # 패널 번호
    num_font = _get_font(40)
    draw.text((50, 80), f"PANEL {panel_idx}", font=num_font, fill=TEXT_CYAN)

    # key_text
    key_font = _get_font(52)
    wrapped_key = textwrap.fill(key_text or "", width=18)
    draw.text((50, 220), wrapped_key, font=key_font, fill=TEXT_WHITE)

    # narration
    narr_font = _get_font(32)
    wrapped_narr = textwrap.fill(narration or "", width=28)
    draw.text((50, 600), wrapped_narr, font=narr_font, fill=(160, 180, 200))

    if market_ref:
        ref_font = _get_font(30)
        draw.text((50, SLIDE_H - 100), market_ref, font=ref_font, fill=TEXT_AMBER)

    slide.save(str(output_path), "PNG", optimize=True)
    return output_path


def _compose_disclaimer_slide(output_path: Path, narration: str) -> Path:
    """DISCLAIMER 슬라이드 — 투자 고지 전용."""
    slide = Image.new("RGB", (SLIDE_W, SLIDE_H), (8, 5, 15))
    draw = ImageDraw.Draw(slide)

    for i in range(5):
        draw.rectangle(
            [(0, i * 200), (SLIDE_W, (i + 1) * 200)],
            fill=(8 + i, 5 + i * 2, 15 + i * 3),
        )

    warn_font = _get_font(80)
    draw.text((SLIDE_W // 2 - 50, 120), "⚠️", font=warn_font, fill=TEXT_AMBER)

    DISCLAIMER_TEXT = (
        "⚠️ 투자 참고 정보\n\n"
        "본 콘텐츠는 투자 참고 정보이며,\n"
        "투자 권유가 아닙니다.\n\n"
        "모든 투자 판단과 책임은\n"
        "투자자 본인에게 있습니다.\n\n"
        "EDT Investment Comic"
    )
    disc_font = _get_font(36)
    wrapped = textwrap.fill(DISCLAIMER_TEXT, width=22)
    draw.text((60, 320), wrapped, font=disc_font, fill=(200, 200, 220), spacing=8)

    logo_font = _get_font(28)
    draw.text(
        (SLIDE_W // 2 - 180, SLIDE_H - 80),
        "🍌 Investment Comic Gemini",
        font=logo_font,
        fill=TEXT_CYAN,
    )

    slide.save(str(output_path), "PNG", optimize=True)
    return output_path


def compose_episode(
    panels: list[dict],
    panel_images: list[Path | None],
    output_dir: Path,
) -> list[Path]:
    """
    에피소드 전체 슬라이드 조립.

    Args:
        panels: EpisodeScript.panels 딕셔너리 목록.
        panel_images: Gemini 생성 패널 이미지 경로 (None이면 fallback).
        output_dir: 슬라이드 저장 디렉토리.

    Returns:
        슬라이드 경로 목록 (S1.png ~ S8.png).
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    slides: list[Path] = []

    for i, panel in enumerate(panels):
        idx = panel.get("idx", i + 1)
        img_path = panel_images[i] if i < len(panel_images) else None

        slide_path = compose_slide(
            panel_image_path=img_path,
            key_text=panel.get("key_text", ""),
            narration=panel.get("narration", ""),
            panel_idx=idx,
            panel_type=panel.get("panel_type", "NORMAL"),
            market_ref=panel.get("market_ref"),
            output_path=output_dir / f"S{idx}.png",
        )
        slides.append(slide_path)
        logger.info("[pil_composer] S%d.png → %s", idx, slide_path)

    logger.info("[pil_composer] 슬라이드 %d개 조립 완료", len(slides))
    return slides
