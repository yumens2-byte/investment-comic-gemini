"""tests/test_shorts_media.py — S3/S4/S5 미디어·조립 단위 테스트 (외부 API 미사용, ffmpeg 실사용)."""

from __future__ import annotations

import shutil
import wave

import pytest

from engine.video.audio_overlay import _pcm_to_wav_bytes
from engine.video.shorts_media import (
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


def test_timeline_structure_and_total():
    """v1.1.0: 북엔드가 가변이므로 총 길이는 24s + intro/outro 실제 길이."""
    from engine.video.shorts_media import bookend_duration

    sc = _scenario()
    tl = build_timeline(sc)
    assert [t.label for t in tl] == ["intro", "cut1", "cut2", "cut3", "outro"]
    assert tl[0].start_sec == 0.0
    expected = (
        8 * 3
        + bookend_duration(sc.intro.narration_tts)
        + bookend_duration(sc.outro.narration_tts)
    )
    assert tl[-1].end_sec == expected
    assert expected == sc.total_duration_sec()  # 스키마 계산과 일치
    assert expected < 60  # Shorts 제한


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


# ── v1.1.0: 나레이션 슬롯 보정 / 북엔드 가변 길이 ────────────
# (2026-08-29 run #33229690192 회고: TTS 12~15s vs 슬롯 3~8s → 음성 겹침)


def test_bookend_duration_scales_with_narration():
    from engine.video.shorts_media import bookend_duration

    assert bookend_duration("짧다") == 3  # 하한
    assert bookend_duration("가" * 25) == 5
    assert bookend_duration("가" * 100) == 6  # 상한


def test_timeline_uses_variable_bookend():
    sc = _scenario()
    sc.outro.narration_tts = "투자 참고 정보이며 투자 권유가 아닙니다"  # 21자 → 5초
    tl = build_timeline(sc)
    outro = tl[-1]
    assert outro.end_sec - outro.start_sec == 5
    # 컷 구간은 그대로 8초 유지
    assert tl[1].end_sec - tl[1].start_sec == 8


def test_timeline_still_contiguous_with_variable_bookend():
    sc = _scenario()
    sc.intro.narration_tts = "가" * 28
    tl = build_timeline(sc)
    for prev, nxt in zip(tl, tl[1:]):
        assert prev.end_sec == nxt.start_sec


@pytest.mark.skipif(not FFMPEG, reason="ffmpeg not available")
def test_fit_narration_speeds_up_overlong_audio(tmp_path):
    """슬롯 초과 나레이션이 슬롯 안으로 들어와야 한다 (겹침 방지 최종 방어선)."""
    from engine.video.shorts_media import fit_narration_to_slot, probe_duration

    src = tmp_path / "long.wav"
    src.write_bytes(_pcm_to_wav_bytes(b"\x00\x01" * (24000 * 10)))  # 10초
    assert probe_duration(src) == pytest.approx(10.0, abs=0.2)

    out = fit_narration_to_slot(src, slot_sec=8.0, output_path=tmp_path / "fit.wav")
    assert out != src
    assert probe_duration(out) <= 8.0  # 슬롯 이내


@pytest.mark.skipif(not FFMPEG, reason="ffmpeg not available")
def test_fit_narration_keeps_short_audio_untouched(tmp_path):
    from engine.video.shorts_media import fit_narration_to_slot

    src = tmp_path / "short.wav"
    src.write_bytes(_pcm_to_wav_bytes(b"\x00\x01" * (24000 * 2)))  # 2초
    out = fit_narration_to_slot(src, slot_sec=8.0, output_path=tmp_path / "fit.wav")
    assert out == src  # 원본 그대로


@pytest.mark.skipif(not FFMPEG, reason="ffmpeg not available")
def test_fit_narration_truncates_when_speedup_insufficient(tmp_path):
    """가속 상한(1.3배)으로도 부족하면 절단해서라도 슬롯을 지켜야 한다."""
    from engine.video.shorts_media import fit_narration_to_slot, probe_duration

    src = tmp_path / "verylong.wav"
    src.write_bytes(_pcm_to_wav_bytes(b"\x00\x01" * (24000 * 15)))  # 15초
    out = fit_narration_to_slot(src, slot_sec=5.0, output_path=tmp_path / "fit.wav")
    assert probe_duration(out) <= 5.0


# ── v1.2.0 사전 체크리스트 (2026-08-29 파이프라인 점검) ──────
# 배경: 예산 검사가 Veo 직전에만 있어 이미지 $0.0784 가 먼저 과금됐고,
#       YouTube 토큰 무효는 $3.7 소진 후에야 드러났다(run #33240050576).


def test_estimate_episode_cost_includes_side_costs():
    from engine.video.shorts_media import (
        SIDE_COST_USD,
        estimate_episode_cost,
        estimate_veo_cost,
    )

    sc = _scenario()
    assert estimate_episode_cost(sc) == pytest.approx(estimate_veo_cost(sc) + SIDE_COST_USD)
    assert estimate_episode_cost(sc) > estimate_veo_cost(sc)  # 부대비용 반영


def test_preflight_dry_run_skips_without_cost():
    from engine.video.shorts_media import preflight_check

    report = preflight_check(_scenario(), dry_run=True)
    assert report["skipped"] is True
    assert report["estimated_cost_usd"] > 0


def test_preflight_raises_when_budget_exceeded(monkeypatch):
    """예산 초과 시 이미지 1장도 생성되기 전에 중단되어야 한다."""
    import sys
    import types

    from engine.video.shorts_media import preflight_check

    class _Exceeded(RuntimeError):
        pass

    def _check(estimated_cost_usd):
        raise _Exceeded(f"budget exceeded for ${estimated_cost_usd}")

    monkeypatch.setitem(
        sys.modules,
        "engine.video.budget_checker",
        types.SimpleNamespace(check_before_generation=_check),
    )
    with pytest.raises(_Exceeded):
        preflight_check(_scenario(), dry_run=False)


def test_preflight_blocks_when_ffmpeg_missing(monkeypatch):
    import sys
    import types

    from engine.video import shorts_media as sm

    monkeypatch.setitem(
        sys.modules,
        "engine.video.budget_checker",
        types.SimpleNamespace(
            check_before_generation=lambda estimated_cost_usd: {
                "monthly_spent_usd": 0.0,
                "budget_cap_usd": 80.0,
                "remaining_usd": 80.0,
            }
        ),
    )
    monkeypatch.setattr(sm.shutil, "which", lambda name: None)
    with pytest.raises(sm.ShortsMediaError, match="ffmpeg 없음"):
        sm.preflight_check(_scenario(), dry_run=False)


# ── v1.3.0 컷 수 하드코딩 제거 (2026-09-06 run #34004565648 회고) ──
# 증상: 주간 2컷 시나리오 조립 시 "본편 컷 수 이상: 2 (3 필요)" 로 실패.
#       미디어 비용($1.88)은 이미 지출된 뒤였다.


@pytest.mark.skipif(not FFMPEG, reason="ffmpeg not available")
def test_assemble_accepts_two_cut_weekly(tmp_path):
    from engine.video.shorts_media import (
        MediaResult,
        _write_dummy_mp4,
        _write_dummy_png,
        assemble_shorts,
    )

    sc = _scenario()
    sc.cuts = sc.cuts[:2]  # 주간 다이제스트 = 2컷
    for c in sc.cuts:
        c.duration_sec = 6

    intro, outro = tmp_path / "P91.png", tmp_path / "P92.png"
    _write_dummy_png(intro)
    _write_dummy_png(outro)
    cuts = []
    for i in (1, 2):
        p = tmp_path / f"cut{i}.mp4"
        _write_dummy_mp4(p)
        cuts.append(p)

    media = MediaResult(intro_image=intro, outro_image=outro, cut_paths=cuts)
    # 더미 mp4 는 실제 디코딩이 불가하므로 컷 수 검증 통과 여부만 본다.
    try:
        assemble_shorts(sc, media, tmp_path / "out")
    except Exception as exc:
        assert "컷 수 불일치" not in str(exc), f"2컷 조립이 컷 수 검증에서 막힘: {exc}"


def test_assemble_rejects_cut_count_mismatch(tmp_path):
    from engine.video.shorts_media import (
        MediaResult,
        ShortsMediaError,
        _write_dummy_mp4,
        _write_dummy_png,
        assemble_shorts,
    )

    sc = _scenario()  # 3컷
    intro, outro = tmp_path / "P91.png", tmp_path / "P92.png"
    _write_dummy_png(intro)
    _write_dummy_png(outro)
    p = tmp_path / "cut1.mp4"
    _write_dummy_mp4(p)

    media = MediaResult(intro_image=intro, outro_image=outro, cut_paths=[p])
    with pytest.raises(ShortsMediaError, match="컷 수 불일치"):
        assemble_shorts(sc, media, tmp_path / "out")
