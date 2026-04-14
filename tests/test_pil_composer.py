"""
tests/test_pil_composer.py
PIL 슬라이드 조립 단위 테스트.
"""
import tempfile
from pathlib import Path

import pytest

from engine.assembly.pil_composer import (
    compose_slide,
    compose_episode,
    SLIDE_W,
    SLIDE_H,
)


class TestComposeSlide:
    """compose_slide() 단일 슬라이드 검증."""

    def test_disclaimer_slide_created(self, tmp_path):
        """DISCLAIMER 타입 슬라이드 생성."""
        out = tmp_path / "S8.png"
        result = compose_slide(
            panel_image_path=None,
            key_text="⚠️ 투자 참고 정보",
            narration="본 콘텐츠는 투자 참고 정보이며, 투자 권유가 아닙니다.",
            panel_idx=8,
            panel_type="DISCLAIMER",
            output_path=out,
        )
        assert result.exists()
        assert result.stat().st_size > 0

    def test_text_card_fallback_when_no_image(self, tmp_path):
        """이미지 없으면 text_card fallback 슬라이드 생성."""
        out = tmp_path / "S1.png"
        result = compose_slide(
            panel_image_path=None,
            key_text="전투 시작!",
            narration="오일 쇼크 타이탄이 등장했다.",
            panel_idx=1,
            panel_type="BATTLE",
            output_path=out,
        )
        assert result.exists()
        assert result.stat().st_size > 0

    def test_slide_dimensions(self, tmp_path):
        """생성된 슬라이드 크기가 1080×1350이어야 한다."""
        from PIL import Image

        out = tmp_path / "slide.png"
        compose_slide(
            panel_image_path=None,
            key_text="테스트",
            narration="내레이션 테스트",
            panel_idx=1,
            panel_type="TENSION",
            output_path=out,
        )
        with Image.open(out) as img:
            assert img.size == (SLIDE_W, SLIDE_H), f"기대 {SLIDE_W}x{SLIDE_H}, 실제 {img.size}"

    def test_image_slide_with_panel(self, tmp_path):
        """실제 이미지 파일이 있을 때 이미지 합성 슬라이드 생성."""
        from PIL import Image

        # 더미 패널 이미지 생성 (1080x1080)
        panel_img = tmp_path / "P1.png"
        img = Image.new("RGB", (1080, 1080), (50, 50, 100))
        img.save(str(panel_img))

        out = tmp_path / "S1.png"
        result = compose_slide(
            panel_image_path=panel_img,
            key_text="레버리지 공격!",
            narration="레버리지 머슬맨이 역기를 들어올렸다.",
            panel_idx=1,
            panel_type="BATTLE",
            market_ref="WTI +7.8%",
            output_path=out,
        )
        assert result.exists()
        with Image.open(result) as img:
            assert img.size == (SLIDE_W, SLIDE_H)


class TestComposeEpisode:
    """compose_episode() 에피소드 전체 조립."""

    def _make_panels(self, n: int = 8) -> list[dict]:
        panels = [
            {
                "idx": i,
                "panel_type": "BATTLE" if i < n else "DISCLAIMER",
                "key_text": f"대사 {i}",
                "narration": f"내레이션 {i}",
                "market_ref": None,
            }
            for i in range(1, n + 1)
        ]
        return panels

    def test_compose_8_panels(self, tmp_path):
        """8개 패널 → 8개 슬라이드 파일 생성."""
        panels = self._make_panels(8)
        panel_images = [None] * 8  # 이미지 없음 → text_card

        slides = compose_episode(panels, panel_images, tmp_path)

        assert len(slides) == 8
        for s in slides:
            assert s.exists()

    def test_slide_naming(self, tmp_path):
        """슬라이드 파일명이 S1.png ~ S8.png 형식이어야 한다."""
        panels = self._make_panels(8)
        slides = compose_episode(panels, [None] * 8, tmp_path)

        names = {s.name for s in slides}
        expected = {f"S{i}.png" for i in range(1, 9)}
        assert names == expected
