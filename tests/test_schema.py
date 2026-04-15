"""
tests/test_schema.py
EpisodeScript Pydantic 스키마 검증.
"""
import pytest
from pydantic import ValidationError

from engine.narrative.schema import EpisodeScript


def _make_valid_script(**overrides) -> dict:
    base = {
        "episode_id": "ICG-2026-04-14-001",
        "date": "2026-04-14",
        "event_type": "BATTLE",
        "title": "오일 쇼크의 습격",
        "logline": "유가 급등으로 오일 쇼크 타이탄이 소환되었다.",
        "panels": [
            {"idx": i, "panel_type": "BATTLE" if i < 8 else "DISCLAIMER",
             "characters": [], "camera": "WIDE",
             "setting": "Seoul", "action": "fight",
             "key_text": f"대사{i}", "narration": f"내레이션{i}"}
            for i in range(1, 9)
        ],
        "caption_x_cover": "오늘 유가 폭등!",
        "caption_x_parts": ["파트1", "파트2"],
        "caption_x_final": "본 콘텐츠는 투자 참고 정보이며, 투자 권유가 아닙니다.",
        "caption_telegram": "텔레그램 캡션",
        "hashtags": ["#미장", "#EDT"],
        "arc_tension_delta": 5,
    }
    base.update(overrides)
    return base


class TestEpisodeScript:
    def test_valid_script_passes(self):
        data = _make_valid_script()
        script = EpisodeScript.model_validate(data)
        assert script.episode_id == "ICG-2026-04-14-001"
        assert len(script.panels) == 8

    def test_last_panel_not_disclaimer_fails(self):
        data = _make_valid_script()
        data["panels"][-1]["panel_type"] = "BATTLE"  # DISCLAIMER 아님
        with pytest.raises(ValidationError):
            EpisodeScript.model_validate(data)

    def test_caption_missing_disclaimer_fails(self):
        data = _make_valid_script(caption_x_final="면책고지 없는 캡션")
        with pytest.raises(ValidationError):
            EpisodeScript.model_validate(data)

    def test_episode_id_pattern_enforced(self):
        data = _make_valid_script(episode_id="WRONG-FORMAT")
        with pytest.raises(ValidationError):
            EpisodeScript.model_validate(data)

    def test_panel_count_min_8(self):
        data = _make_valid_script()
        data["panels"] = data["panels"][:7]  # 7개 → 실패
        with pytest.raises(ValidationError):
            EpisodeScript.model_validate(data)

    def test_panel_count_max_10(self):
        data = _make_valid_script()
        extra = {"idx": 11, "panel_type": "BATTLE", "characters": [],
                 "camera": "WIDE", "setting": "S", "action": "A",
                 "key_text": "X", "narration": "Y"}
        data["panels"] = data["panels"] + [extra] * 3  # 11개 → 실패
        with pytest.raises(ValidationError):
            EpisodeScript.model_validate(data)

    def test_key_text_max_length(self):
        data = _make_valid_script()
        data["panels"][0]["key_text"] = "A" * 41  # 41자 초과
        with pytest.raises(ValidationError):
            EpisodeScript.model_validate(data)

    def test_narration_max_length(self):
        data = _make_valid_script()
        data["panels"][0]["narration"] = "A" * 121  # 121자 초과
        with pytest.raises(ValidationError):
            EpisodeScript.model_validate(data)

    def test_arc_tension_delta_bounds(self):
        with pytest.raises(ValidationError):
            EpisodeScript.model_validate(_make_valid_script(arc_tension_delta=11))
        with pytest.raises(ValidationError):
            EpisodeScript.model_validate(_make_valid_script(arc_tension_delta=-11))

    def test_caption_x_parts_min_2(self):
        data = _make_valid_script(caption_x_parts=["하나"])
        with pytest.raises(ValidationError):
            EpisodeScript.model_validate(data)

    def test_model_dump_roundtrip(self):
        script = EpisodeScript.model_validate(_make_valid_script())
        d = script.model_dump()
        script2 = EpisodeScript.model_validate(d)
        assert script2.episode_id == script.episode_id


# ── x_publisher 청킹 테스트 ───────────────────────────────────────────────────

from pathlib import Path  # noqa: E402

from engine.common.exceptions import DisclaimerMissing  # noqa: E402
from engine.publish.x_publisher import (  # noqa: E402
    SLEEP_BETWEEN_TWEETS,
    _chunk_slides,
    _guard_disclaimer,
)


class TestXPublisherChunking:
    """_chunk_slides() 슬라이드 분할 검증."""

    def _make_slides(self, n: int) -> list[Path]:
        return [Path(f"/tmp/S{i}.png") for i in range(1, n + 1)]

    def test_8_slides_to_4_chunks(self):
        slides = self._make_slides(8)
        chunks = _chunk_slides(slides)
        assert len(chunks) == 4
        assert len(chunks[0]) == 1   # T1: 커버
        assert len(chunks[1]) == 3   # T2: S2-S4
        assert len(chunks[2]) == 3   # T3: S5-S7
        assert len(chunks[3]) == 1   # T4: disclaimer

    def test_cover_is_first_slide(self):
        slides = self._make_slides(8)
        chunks = _chunk_slides(slides)
        assert chunks[0][0] == slides[0]

    def test_disclaimer_is_last_slide(self):
        slides = self._make_slides(8)
        chunks = _chunk_slides(slides)
        assert chunks[-1][-1] == slides[-1]

    def test_10_slides_chunking(self):
        slides = self._make_slides(10)
        chunks = _chunk_slides(slides)
        assert len(chunks) >= 4
        assert chunks[0][0] == slides[0]
        assert chunks[-1][-1] == slides[-1]

    def test_empty_slides(self):
        assert _chunk_slides([]) == []

    def test_sleep_constant(self):
        assert SLEEP_BETWEEN_TWEETS == 10


class TestDisclaimerGuard:
    """_guard_disclaimer() + DisclaimerMissing 예외 검증."""

    def test_valid_disclaimer_passes(self):
        _guard_disclaimer("본 콘텐츠는 투자 참고 정보이며, 투자 권유가 아닙니다.")

    def test_missing_disclaimer_raises(self):
        with pytest.raises(DisclaimerMissing):
            _guard_disclaimer("면책 고지 없는 캡션입니다.")

    def test_partial_disclaimer_raises(self):
        with pytest.raises(DisclaimerMissing):
            _guard_disclaimer("투자 참고 정보입니다.")  # 전체 문구 없음

    def test_disclaimer_missing_location_field(self):
        exc = DisclaimerMissing(location="caption_x_final")
        assert "caption_x_final" in str(exc)

    def test_dry_run_publish(self):
        """DRY_RUN 모드에서 X API 호출 없이 DRY_RUN 반환."""
        from engine.publish.x_publisher import publish_episode_x

        script = {
            "caption_x_cover": "테스트 커버",
            "caption_x_parts": ["파트1", "파트2"],
            "caption_x_final": "본 콘텐츠는 투자 참고 정보이며, 투자 권유가 아닙니다.",
            "hashtags": ["#테스트"],
        }
        slides = [Path(f"/tmp/S{i}.png") for i in range(1, 9)]

        result = publish_episode_x(script, slides, dry_run=True)
        assert len(result) > 0
        assert all("DRY_RUN" in tid for tid in result)
