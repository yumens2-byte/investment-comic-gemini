"""tests/test_shorts_media.py — S3/S4/S5 미디어·조립 단위 테스트 (외부 API 미사용, ffmpeg 실사용)."""

from __future__ import annotations

import shutil
import wave

import pytest

from engine.video.audio_overlay import _pcm_to_wav_bytes
from engine.video.shorts_media import (
    BOOKEND_DURATION_SEC,
    MediaResult,
    build_subtitle_items,
    build_timeline,
    estimate_veo_cost,
    generate_bookend_images,
    generate_cut_videos,
    mix_narrations,
    still_to_clip,
)
from engine.video.shorts_pipeline import ShortsScenario

FFMPEG = shutil.which("ffmpeg") is not None
DATE = "2026-08-29"


def _scenario() -> ShortsScenario:
    cut = {
        "caption": "금리 하락",
        "narration_tts": "국채금리가 내려가며 전선이 열립니다.",
        "video_prompt": "Cinematic vertical full shot of tiger warrior, Manhwa style, 9:16.",
        "duration_sec": 8,
    }
    return ShortsScenario(
        episode_id=f"icg-v-{DATE}-001",
        episode_date=DATE,
        event_type="BATTLE",
        scenario_type="ONE_VS_ONE",
        outcome="HERO_TACTICAL_VICTORY",
        hero_ids=["CHAR_HERO_001"],
        villain_id="CHAR_VILLAIN_001",
        intro={
            "caption": "오늘의 전투",
            "narration_tts": "시장의 수호자가 움직입니다.",
            "image_prompt": "Vertical 9:16 heroic intro card, Manhwa style, no text overlay.",
        },
        cuts=[{**cut, "seq": s} for s in (1, 2, 3)],
        outro={
            "caption": "다음 화 예고",
            "narration_tts": "투자 참고 정보이며, 투자 권유가 아닙니다.",
            "image_prompt": "Vertical 9:16 outro card with sunrise city, Manhwa style.",
        },
        youtube_title="부채 타이탄 격파",
        youtube_description="투자 참고 정보이며, 투자 권유가 아닙니다.",
    )


# ── 타임라인/자막 ────────────────────────────────────────────


def test_timeline_total_30s():
    tl = build_timeline(_scenario())
    assert [t.label for t in tl] == ["intro", "cut1", "cut2", "cut3", "outro"]
    assert tl[0].start_sec == 0.0
    assert tl[-1].end_sec == 8 * 3 + BOOKEND_DURATION_SEC * 2  # 30초


def test_timeline_contiguous():
    tl = build_timeline(_scenario())
    for prev, nxt in zip(tl, tl[1:]):
        assert prev.end_sec == nxt.start_sec


def test_subtitle_items_format():
    items = build_subtitle_items(_scenario())
    assert len(items) == 5
    assert set(items[0].keys()) == {"start_sec", "end_sec", "text"}
    assert all(i["end_sec"] > i["start_sec"] for i in items)


def test_estimate_veo_cost():
    assert estimate_veo_cost(_scenario()) == pytest.approx(24 * 0.15)  # $3.60


# ── DRY_RUN 생성 (비용 0, 외부 API 미호출) ───────────────────


def test_bookend_dry_run(tmp_path):
    media = generate_bookend_images(_scenario(), tmp_path, dry_run=True)
    assert media.intro_image.exists()
    assert media.outro_image.exists()
    assert media.image_cost_usd == 0.0


def test_cuts_dry_run(tmp_path):
    media = generate_cut_videos(_scenario(), tmp_path, MediaResult(), dry_run=True)
    assert len(media.cut_paths) == 3
    assert all(p.exists() for p in media.cut_paths)
    assert media.veo_cost_usd == 0.0


# ── WAV 헤더 (audio_overlay v1.2.0) ─────────────────────────


def test_pcm_to_wav_roundtrip(tmp_path):
    pcm = b"\x00\x01" * 2400  # 0.1s @24kHz s16le mono
    wav_bytes = _pcm_to_wav_bytes(pcm)
    p = tmp_path / "t.wav"
    p.write_bytes(wav_bytes)
    with wave.open(str(p), "rb") as w:
        assert w.getframerate() == 24000
        assert w.getnchannels() == 1
        assert w.getsampwidth() == 2
        assert w.getnframes() == 2400


# ── ffmpeg 실사용 (컨테이너/CI 공통 — ffmpeg 부재 시 skip) ──


@pytest.mark.skipif(not FFMPEG, reason="ffmpeg not available")
def test_still_to_clip_real(tmp_path):
    from engine.video.shorts_media import _write_dummy_png

    img = tmp_path / "card.png"
    _write_dummy_png(img)
    clip = still_to_clip(img, tmp_path / "clip.mp4", duration_sec=1)
    assert clip.exists()
    assert clip.stat().st_size > 1000  # 실 인코딩 산출물


@pytest.mark.skipif(not FFMPEG, reason="ffmpeg not available")
def test_mix_narrations_copy_when_no_segments(tmp_path):
    from engine.video.shorts_media import _write_dummy_png

    img = tmp_path / "card.png"
    _write_dummy_png(img)
    src = still_to_clip(img, tmp_path / "src.mp4", duration_sec=1)
    out = mix_narrations(src, [], tmp_path / "out.mp4")
    assert out.exists()


@pytest.mark.skipif(not FFMPEG, reason="ffmpeg not available")
def test_mix_narrations_with_segment(tmp_path):
    from engine.video.shorts_media import _write_dummy_png

    img = tmp_path / "card.png"
    _write_dummy_png(img)
    src = still_to_clip(img, tmp_path / "src.mp4", duration_sec=1)

    wav = tmp_path / "n.wav"
    wav.write_bytes(_pcm_to_wav_bytes(b"\x00\x01" * 4800))  # 0.2s
    out = mix_narrations(src, [(0.1, wav)], tmp_path / "out.mp4")
    assert out.exists()
    assert out.stat().st_size > 1000
