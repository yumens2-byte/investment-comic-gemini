"""
engine/assembly/slide_templates.py
슬라이드 타입별 레이아웃 정의.

pil_composer.py에서 참조하는 레이아웃 상수 및 설정.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

PanelType = Literal["COVER", "TENSION", "BATTLE", "CLIMAX", "AFTERMATH", "TEXT_CARD", "DISCLAIMER"]


@dataclass(frozen=True)
class SlideLayout:
    """단일 슬라이드 레이아웃 설정."""

    panel_type: str
    bg_color: tuple[int, int, int]  # RGB 배경색
    text_bar_color: tuple[int, int, int]  # 텍스트 바 배경색
    accent_color: tuple[int, int, int]  # 강조색 (패널 번호, market_ref)
    key_text_size: int  # 말풍선 폰트 크기
    narration_size: int  # 내레이션 폰트 크기
    show_panel_number: bool  # 패널 번호 표시 여부
    full_text_mode: bool  # 이미지 없이 텍스트 전용 여부


# 패널 타입별 레이아웃 매핑
LAYOUTS: dict[str, SlideLayout] = {
    "COVER": SlideLayout(
        panel_type="COVER",
        bg_color=(5, 8, 18),
        text_bar_color=(8, 12, 25),
        accent_color=(59, 130, 246),  # 파란색
        key_text_size=40,
        narration_size=26,
        show_panel_number=False,
        full_text_mode=False,
    ),
    "TENSION": SlideLayout(
        panel_type="TENSION",
        bg_color=(10, 10, 20),
        text_bar_color=(12, 12, 22),
        accent_color=(245, 158, 11),  # 앰버
        key_text_size=34,
        narration_size=24,
        show_panel_number=True,
        full_text_mode=False,
    ),
    "BATTLE": SlideLayout(
        panel_type="BATTLE",
        bg_color=(15, 5, 5),
        text_bar_color=(18, 8, 8),
        accent_color=(239, 68, 68),  # 빨간색
        key_text_size=36,
        narration_size=24,
        show_panel_number=True,
        full_text_mode=False,
    ),
    "CLIMAX": SlideLayout(
        panel_type="CLIMAX",
        bg_color=(15, 5, 15),
        text_bar_color=(18, 8, 18),
        accent_color=(139, 92, 246),  # 보라색
        key_text_size=38,
        narration_size=24,
        show_panel_number=True,
        full_text_mode=False,
    ),
    "AFTERMATH": SlideLayout(
        panel_type="AFTERMATH",
        bg_color=(8, 12, 20),
        text_bar_color=(10, 15, 25),
        accent_color=(6, 182, 212),  # 시안
        key_text_size=32,
        narration_size=24,
        show_panel_number=True,
        full_text_mode=False,
    ),
    "TEXT_CARD": SlideLayout(
        panel_type="TEXT_CARD",
        bg_color=(5, 10, 20),
        text_bar_color=(5, 10, 20),
        accent_color=(16, 185, 129),  # 초록
        key_text_size=52,
        narration_size=32,
        show_panel_number=False,
        full_text_mode=True,  # 이미지 없이 텍스트만
    ),
    "DISCLAIMER": SlideLayout(
        panel_type="DISCLAIMER",
        bg_color=(8, 5, 15),
        text_bar_color=(8, 5, 15),
        accent_color=(245, 158, 11),  # 앰버 (경고)
        key_text_size=36,
        narration_size=36,
        show_panel_number=False,
        full_text_mode=True,
    ),
}


def get_layout(panel_type: str) -> SlideLayout:
    """패널 타입에 맞는 SlideLayout 반환 (없으면 BATTLE 기본값)."""
    return LAYOUTS.get(panel_type, LAYOUTS["BATTLE"])
