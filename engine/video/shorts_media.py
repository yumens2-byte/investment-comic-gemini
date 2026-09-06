"""
engine/video/shorts_media.py
Daily Battle Shorts — 미디어 생성(S3/S4) + 조립(S5).

구성 (총 ~30초, 세로 1080x1920):
  [인트로 정지 이미지 3초] + [Veo T2V 8초 x 3컷] + [아웃트로 정지 이미지 3초]

원본 재사용 (시그니처 실측 완료 — 추측 사용 금지 원칙):
  - engine/image/gemini_client.generate_panel(panel_idx, prompt_text, ref_paths,
      output_dir, log_path) -> (Path|None, cost_usd)          # 북엔드 이미지
  - engine/image/ref_loader.get_refs_for_panel(char_ids) -> list[Path]
  - engine/video/veo_client.VeoClient.generate_text_to_video(...) -> dict
      (I2V 는 원본이 NotImplementedError — 3컷 모두 T2V, 마스터 수동 방식과 동일)
  - engine/video/budget_checker.check_before_generation(estimated_cost_usd)
  - engine/video/ffmpeg_composer.concat_cuts / compose_final
  - engine/video/subtitle_renderer.build_ass / burn_in
  - engine/video/audio_overlay.generate_tts (v1.2.0 실장분)

DRY_RUN 규약: os.environ.get("DRY_RUN", "true").lower() == "true"
  -> Gemini/Veo/TTS 미호출 (비용 0), 더미 파일로 조립 경로만 검증.
비용 로그: 생성 1회당 cost=$N.NNNN (기존 클라이언트들과 동일 스타일).
"""

from __future__ import annotations

import logging
import math
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from engine.video.shorts_pipeline import (
    BOOKEND_DURATION_SEC,
    BOOKEND_MAX_SEC,
    BOOKEND_MIN_SEC,
    CHARS_PER_SEC,
    ShortsScenario,
)

VERSION = "1.3.0"
logger = logging.getLogger(__name__)

VEO_UNIT_PRICE_PER_SEC = 0.15  # veo_client.py 실측 단가 (8s = $1.20/cut)
TARGET_W, TARGET_H, TARGET_FPS = 1080, 1920, 24
BOOKEND_IDX_INTRO = 91  # generate_panel 파일명 P{idx}.png — 본편 패널(1~8)과 충돌 방지
BOOKEND_IDX_OUTRO = 92
MAX_NARRATION_SPEEDUP = 1.3  # atempo 상한 (그 이상은 청취성 급락)
# 실측 기반 부대비용 (2026-08-29 run #33229690192): 이미지 2장 $0.0784 + 각색 $0.0412
# 예산 검사는 Veo 만이 아니라 회차 총비용으로 해야 실효가 있다 (v1.2.0).
SIDE_COST_USD = 0.12
NARRATION_TAIL_GAP_SEC = 0.3  # 구간 사이 최소 무음 간격


class ShortsMediaError(Exception):
    """미디어 생성/조립 실패."""


def _is_dry_run(dry_run: Optional[bool] = None) -> bool:
    if dry_run is not None:
        return dry_run
    return os.environ.get("DRY_RUN", "true").lower() == "true"


def _run_ffmpeg(args: list[str], context: str) -> None:
    cmd = ["ffmpeg", "-y", "-loglevel", "error", *args]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise ShortsMediaError(f"ffmpeg 실패 ({context}): {result.stderr[-400:]}")


def _write_dummy_mp4(output_path: Path) -> None:
    """DRY_RUN 용 최소 mp4 (run_video_trailer._create_dummy_mp4 와 동일 시그니처 바이트)."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 1016)


def _write_dummy_png(output_path: Path, size: int = 16) -> None:
    """
    DRY_RUN 용 유효 PNG 생성 (표준 라이브러리만 사용).

    v1.0.0 개발 중 발견 버그: hex 하드코딩 PNG 의 청크 길이 손상
    ('chunk too big') → ffmpeg -loop 1 파서 무한 행. zlib 기반 생성으로 교체.
    """
    import struct
    import zlib

    def chunk(tag: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + tag
            + payload
            + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)  # RGB 8bit
    raw = b"".join(b"\x00" + b"\x40\x40\x40" * size for _ in range(size))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


# ────────────────────────────────────────────────────────
# 타임라인 (자막/나레이션 공용 스케줄)
# ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class TimelineItem:
    label: str  # intro / cut1 / cut2 / cut3 / outro
    start_sec: float
    end_sec: float
    narration: str
    caption: str


def bookend_duration(narration: str) -> int:
    """
    북엔드(정지 이미지) 노출 시간을 나레이션 길이로 산출한다.

    v1.1.0: 3초 고정이면 면책 문구가 포함된 아웃트로 음성이 잘리거나 다음 구간과
    겹쳤다(2026-08-29 run #33229690192 실측: outro TTS 12.6s vs 슬롯 3s).
    한국어 TTS 실측 속도 CHARS_PER_SEC 기준으로 BOOKEND_MIN~MAX 사이에서 결정.
    """
    needed = math.ceil(len(narration) / CHARS_PER_SEC)
    return max(BOOKEND_MIN_SEC, min(BOOKEND_MAX_SEC, needed))


def build_timeline(scenario: ShortsScenario) -> list[TimelineItem]:
    """인트로 → 3컷 → 아웃트로 시간축 산출 (자막·나레이션 배치의 단일 소스)."""
    items: list[TimelineItem] = []
    cursor = 0.0

    intro_sec = bookend_duration(scenario.intro.narration_tts)
    items.append(
        TimelineItem(
            "intro",
            cursor,
            cursor + intro_sec,
            scenario.intro.narration_tts,
            scenario.intro.caption,
        )
    )
    cursor += intro_sec

    for cut in scenario.cuts:
        items.append(
            TimelineItem(
                f"cut{cut.seq}",
                cursor,
                cursor + cut.duration_sec,
                cut.narration_tts,
                cut.caption,
            )
        )
        cursor += cut.duration_sec

    outro_sec = bookend_duration(scenario.outro.narration_tts)
    items.append(
        TimelineItem(
            "outro",
            cursor,
            cursor + outro_sec,
            scenario.outro.narration_tts,
            scenario.outro.caption,
        )
    )
    return items


# ────────────────────────────────────────────────────────
# S3 — 인트로/아웃트로 이미지 (Gemini, 기존 generate_panel 재사용)
# ────────────────────────────────────────────────────────


@dataclass
class MediaResult:
    intro_image: Path | None = None
    outro_image: Path | None = None
    cut_paths: list[Path] = field(default_factory=list)
    image_cost_usd: float = 0.0
    veo_cost_usd: float = 0.0
    veo_results: list[dict] = field(default_factory=list)

    @property
    def total_cost_usd(self) -> float:
        return round(self.image_cost_usd + self.veo_cost_usd, 4)


def _load_character_refs(scenario: ShortsScenario) -> list:
    """캐릭터 REF 이미지 로드 — 실패해도 북엔드 생성은 계속 (REF 없이 진행)."""
    try:
        from engine.image.ref_loader import get_refs_for_panel

        refs = get_refs_for_panel([*scenario.hero_ids, scenario.villain_id])
        logger.info("[shorts_media] REF 이미지 %d개 로드", len(refs))
        return refs
    except Exception as exc:
        logger.warning("[shorts_media] REF 로드 실패 (REF 없이 진행): %s", exc)
        return []


def preflight_check(
    scenario: ShortsScenario,
    dry_run: Optional[bool] = None,
) -> dict:
    """
    유료 호출 이전 사전 체크리스트 (v1.2.0 신설).

    배경(2026-08-29 점검): 예산 검사가 Veo 직전에만 있어서, 그 전에 이미 이미지
    2장($0.0784)이 과금되고 있었다. 또 YouTube 토큰이 죽어 있어도 $3.7 를 다
    쓴 뒤 발행 단계에서야 실패했다(run #33240050576). 비용이 나가기 전에 한 번에
    검사해 조기 중단한다.

    검사 항목:
      1) 총 예상비용이 월 예산 안에 들어가는가 (Veo + 부대비용)
      2) 조립 도구(ffmpeg/ffprobe)가 존재하는가
      3) 자막용 CJK 폰트가 설치되어 있는가 (없으면 한글이 깨진 영상이 나온다)
      4) YouTube 자격증명이 유효한가 (발행 단계 실패 선차단)

    1~3 은 실패 시 예외로 중단한다. 4 는 경고만 남긴다 — 영상 자체는 쓸 수 있고
    토큰만 재발급하면 재생성 없이 발행할 수 있기 때문이다.
    """
    estimated = estimate_episode_cost(scenario)
    report: dict = {"estimated_cost_usd": estimated}

    if _is_dry_run(dry_run):
        logger.info(
            "[shorts_media] DRY_RUN — preflight 스킵 (실행 시 예상비용 $%.4f)", estimated
        )
        report["skipped"] = True
        return report

    # 1) 예산 (fail-closed)
    from engine.video.budget_checker import check_before_generation

    budget = check_before_generation(estimated_cost_usd=estimated)
    report["budget"] = budget
    logger.info(
        "[shorts_media] preflight 예산 OK: spent=$%.4f + est=$%.4f <= cap=$%.2f",
        budget["monthly_spent_usd"],
        estimated,
        budget["budget_cap_usd"],
    )

    # 2) 조립 도구
    for tool in ("ffmpeg", "ffprobe"):
        if shutil.which(tool) is None:
            raise ShortsMediaError(
                f"preflight 실패: {tool} 없음 — 조립 불가. 워크플로의 설치 step 확인"
            )

    # 3) CJK 폰트 (자막 깨짐 방지)
    if shutil.which("fc-list"):
        fonts = subprocess.run(
            ["fc-list"], capture_output=True, text=True
        ).stdout.lower()
        if "cjk" not in fonts and "nanum" not in fonts:
            raise ShortsMediaError(
                "preflight 실패: 한글(CJK) 폰트 미설치 — 자막이 깨진 영상이 생성된다. "
                "워크플로의 fonts-noto-cjk 설치 step 확인"
            )
        report["cjk_font"] = True
    else:
        logger.warning("[shorts_media] fc-list 없음 — 폰트 검사 생략")
        report["cjk_font"] = None

    # 4) YouTube 자격증명 (경고만)
    try:
        from engine.publish.youtube_shorts_publisher import verify_youtube_credentials

        auth = verify_youtube_credentials()
        report["youtube_auth"] = auth["valid"]
        if not auth["valid"]:
            logger.warning(
                "[shorts_media] preflight 경고: YouTube 자격증명 무효 — "
                "영상은 생성되나 발행은 토큰 재발급 후 가능하다 (%s)",
                auth["detail"],
            )
    except Exception as exc:
        report["youtube_auth"] = None
        logger.warning("[shorts_media] YouTube 자격증명 검사 생략: %s", exc)

    logger.info("[shorts_media] preflight 통과 — 예상비용 $%.4f 집행 시작", estimated)
    return report


def generate_bookend_images(
    scenario: ShortsScenario,
    out_dir: Path,
    dry_run: Optional[bool] = None,
) -> MediaResult:
    """인트로/아웃트로 정지 이미지 생성 (기존 gemini_client.generate_panel 재사용)."""
    result = MediaResult()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if _is_dry_run(dry_run):
        intro = out_dir / f"P{BOOKEND_IDX_INTRO}.png"
        outro = out_dir / f"P{BOOKEND_IDX_OUTRO}.png"
        _write_dummy_png(intro)
        _write_dummy_png(outro)
        result.intro_image, result.outro_image = intro, outro
        logger.info("[shorts_media] DRY_RUN — 북엔드 이미지 더미 생성 (비용 0)")
        return result

    from engine.image.gemini_client import generate_panel

    refs = _load_character_refs(scenario)
    log_path = out_dir / "gemini_run.log"

    for idx, prompt in (
        (BOOKEND_IDX_INTRO, scenario.intro.image_prompt),
        (BOOKEND_IDX_OUTRO, scenario.outro.image_prompt),
    ):
        path, cost = generate_panel(
            panel_idx=idx,
            prompt_text=prompt,
            ref_paths=refs,
            output_dir=out_dir,
            log_path=log_path,
        )
        result.image_cost_usd = round(result.image_cost_usd + cost, 4)
        if idx == BOOKEND_IDX_INTRO:
            result.intro_image = path
        else:
            result.outro_image = path

    if result.intro_image is None or result.outro_image is None:
        raise ShortsMediaError(
            f"북엔드 이미지 생성 실패: intro={result.intro_image} outro={result.outro_image}"
        )
    logger.info(
        "[shorts_media] 북엔드 이미지 완료: cost=$%.4f", result.image_cost_usd
    )
    return result


# ────────────────────────────────────────────────────────
# S4 — 본편 3컷 Veo T2V (기존 VeoClient 재사용 + budget_checker 연동)
# ────────────────────────────────────────────────────────


def estimate_veo_cost(scenario: ShortsScenario) -> float:
    return round(sum(c.duration_sec for c in scenario.cuts) * VEO_UNIT_PRICE_PER_SEC, 4)


def estimate_episode_cost(scenario: ShortsScenario) -> float:
    """회차 총 예상비용 = Veo + 부대비용(이미지·각색·TTS)."""
    return round(estimate_veo_cost(scenario) + SIDE_COST_USD, 4)


def generate_cut_videos(
    scenario: ShortsScenario,
    out_dir: Path,
    result: MediaResult,
    dry_run: Optional[bool] = None,
    max_retry_per_cut: int = 2,
) -> MediaResult:
    """3컷 T2V 생성. 예산 사전 체크 → 컷당 재시도 → 1컷이라도 최종 실패 시 중단(부분 발행 금지)."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    estimated = estimate_veo_cost(scenario)

    if _is_dry_run(dry_run):
        for cut in scenario.cuts:
            path = out_dir / f"cut{cut.seq}.mp4"
            _write_dummy_mp4(path)
            result.cut_paths.append(path)
        logger.info(
            "[shorts_media] DRY_RUN — 3컷 더미 생성 (실생성 시 예상 cost=$%.4f)", estimated
        )
        return result

    # 예산 검사는 preflight_check 로 일원화됨 (v1.2.0) — 여기서 중복 조회하지 않는다.
    from engine.video.veo_client import VeoClient

    logger.info("[shorts_media] Veo 생성 시작: 예상 $%.4f", estimated)
    client = VeoClient()
    for cut in scenario.cuts:
        path = out_dir / f"cut{cut.seq}.mp4"
        last_exc: Exception | None = None
        for attempt in range(1, max_retry_per_cut + 2):
            try:
                res = client.generate_text_to_video(
                    prompt=cut.video_prompt,
                    output_path=str(path),
                    duration_sec=cut.duration_sec,
                    aspect_ratio="9:16",
                )
                result.veo_results.append(res)
                result.veo_cost_usd = round(
                    result.veo_cost_usd + float(res.get("cost_usd") or 0.0), 4
                )
                result.cut_paths.append(path)
                last_exc = None
                break
            except Exception as exc:
                last_exc = exc
                logger.warning(
                    "[shorts_media] cut%d 생성 실패 attempt=%d/%d: %s",
                    cut.seq,
                    attempt,
                    max_retry_per_cut + 1,
                    exc,
                )
        if last_exc is not None:
            raise ShortsMediaError(
                f"cut{cut.seq} 최종 실패 — 당일 영상 생성 중단 (부분 발행 금지): {last_exc}"
            ) from last_exc

    logger.info(
        "[shorts_media] %d컷 완료: veo cost=$%.4f (누계 $%.4f)",
        len(scenario.cuts),
        result.veo_cost_usd,
        result.total_cost_usd,
    )
    return result


# ────────────────────────────────────────────────────────
# S5 — 조립 (스틸→클립, concat, 자막, 나레이션 TTS 믹스, 최종 렌더)
# ────────────────────────────────────────────────────────


def still_to_clip(
    image_path: Path,
    output_path: Path,
    duration_sec: int = BOOKEND_DURATION_SEC,
) -> Path:
    """정지 이미지 → 무음 mp4 클립 (해상도/프레임레이트는 본편과 동일 규격)."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    vf = (
        f"scale={TARGET_W}:{TARGET_H}:force_original_aspect_ratio=decrease,"
        f"pad={TARGET_W}:{TARGET_H}:(ow-iw)/2:(oh-ih)/2:black,fps={TARGET_FPS},"
        f"format=yuv420p"
    )
    _run_ffmpeg(
        [
            # 무한 소스 2개(-loop still + anullsrc) 조합의 -shortest 판정 불능 리스크 회피:
            # 입력 측에서 각각 -t 로 길이를 확정한다 (개발 중 실측으로 검증된 패턴).
            "-loop", "1",
            "-t", str(duration_sec),
            "-i", str(image_path),
            "-f", "lavfi",
            "-t", str(duration_sec),
            "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
            "-vf", vf,
            "-preset", "veryfast",
            "-c:v", "libx264",
            "-c:a", "aac",
            str(output_path),
        ],
        context=f"still_to_clip({image_path.name})",
    )
    logger.info("[shorts_media] still→clip: %s (%ds)", output_path.name, duration_sec)
    return output_path


def probe_duration(path: Path) -> float:
    """ffprobe 로 미디어 길이(초) 측정."""
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not result.stdout.strip():
        raise ShortsMediaError(f"ffprobe 실패: {path} — {result.stderr[-200:]}")
    return float(result.stdout.strip())


def fit_narration_to_slot(
    wav_path: Path,
    slot_sec: float,
    output_path: Path,
    max_speedup: float = MAX_NARRATION_SPEEDUP,
) -> Path:
    """
    나레이션 길이를 슬롯 안에 맞춘다 (겹침 방지의 최종 방어선).

    v1.1.0: 스키마에서 글자 수를 제한해도 TTS 발화 속도 편차로 초과할 수 있다.
    1) 슬롯 이내면 그대로 사용
    2) 초과분이 max_speedup 배 이내면 atempo 로 가속 (음정 유지)
    3) 그래도 넘치면 가속 + 슬롯 경계에서 절단(끝 0.3s 페이드아웃)
    """
    duration = probe_duration(wav_path)
    budget = max(slot_sec - NARRATION_TAIL_GAP_SEC, 0.5)
    if duration <= budget:
        return wav_path

    tempo = min(max(duration / budget, 1.0), max_speedup)
    filters = [f"atempo={tempo:.3f}"]
    after_tempo = duration / tempo
    truncated = after_tempo > budget
    if truncated:
        fade_start = max(budget - 0.3, 0.0)
        filters.append(f"afade=t=out:st={fade_start:.2f}:d=0.3")

    args = ["-i", str(wav_path), "-af", ",".join(filters)]
    if truncated:
        args += ["-t", f"{budget:.2f}"]
    args.append(str(output_path))
    _run_ffmpeg(args, context=f"fit_narration({wav_path.name})")

    logger.info(
        "[shorts_media] 나레이션 슬롯 보정: %s %.1fs -> %.1fs (slot=%.1fs "
        "tempo=%.2f truncated=%s)",
        wav_path.name,
        duration,
        min(after_tempo, budget),
        slot_sec,
        tempo,
        truncated,
    )
    return output_path


def build_subtitle_items(scenario: ShortsScenario) -> list[dict]:
    """subtitle_renderer.build_ass 입력 형식(start_sec/end_sec/text)으로 변환."""
    return [
        {"start_sec": t.start_sec + 0.2, "end_sec": t.end_sec - 0.2, "text": t.caption}
        for t in build_timeline(scenario)
    ]


def generate_narrations(
    scenario: ShortsScenario,
    out_dir: Path,
    dry_run: Optional[bool] = None,
) -> list[tuple[float, Path]]:
    """
    구간별 나레이션 TTS 생성 → [(start_sec, wav_path)].
    TTS 실패는 경고 후 해당 구간 무음 (영상은 자막으로 정보 전달 — 조립 중단 없음).
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    segments: list[tuple[float, Path]] = []

    if _is_dry_run(dry_run):
        logger.info("[shorts_media] DRY_RUN — TTS 스킵 (비용 0)")
        return segments

    from engine.video.audio_overlay import generate_tts

    for t in build_timeline(scenario):
        wav_path = out_dir / f"narr_{t.label}.wav"
        try:
            generate_tts(text=t.narration, output_path=str(wav_path))
        except Exception as exc:
            logger.warning(
                "[shorts_media] TTS 실패 (%s) — 무음 진행: %s", t.label, exc
            )
            continue
        try:
            fitted = fit_narration_to_slot(
                wav_path,
                slot_sec=t.end_sec - t.start_sec,
                output_path=out_dir / f"narr_{t.label}_fit.wav",
            )
        except Exception as exc:
            # 보정 실패 시 원본을 쓰면 겹침이 발생하므로 해당 구간을 버린다.
            logger.warning(
                "[shorts_media] 나레이션 보정 실패 (%s) — 해당 구간 무음: %s",
                t.label,
                exc,
            )
            continue
        segments.append((t.start_sec, fitted))
    return segments


def mix_narrations(
    video_path: Path,
    segments: list[tuple[float, Path]],
    output_path: Path,
) -> Path:
    """
    나레이션 전용 믹스 (원본 audio_overlay.mix_audio 는 BGM 필수 시그니처라 미사용).
    원본 영상 오디오는 음소거하고 나레이션만 배치. 세그먼트 없으면 원본 유지 복사.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not segments:
        _run_ffmpeg(["-i", str(video_path), "-c", "copy", str(output_path)], "mix(copy)")
        return output_path

    inputs: list[str] = ["-i", str(video_path)]
    filters: list[str] = []
    labels: list[str] = []
    for i, (start_sec, wav) in enumerate(segments, start=1):
        inputs += ["-i", str(wav)]
        delay_ms = int(start_sec * 1000)
        filters.append(f"[{i}:a]adelay={delay_ms}|{delay_ms}[n{i}]")
        labels.append(f"[n{i}]")
    filters.append(f"{''.join(labels)}amix=inputs={len(labels)}:duration=longest[aout]")

    _run_ffmpeg(
        [
            *inputs,
            "-filter_complex", ";".join(filters),
            "-map", "0:v",
            "-map", "[aout]",
            "-c:v", "copy",
            "-c:a", "aac",
            str(output_path),
        ],
        context="mix_narrations",
    )
    logger.info("[shorts_media] 나레이션 믹스 완료: %d 세그먼트", len(segments))
    return output_path


def assemble_shorts(
    scenario: ShortsScenario,
    media: MediaResult,
    out_dir: Path,
    burn_subtitles: bool = True,
) -> Path:
    """
    최종 조립: [인트로clip + cut1..3 + 아웃트로clip] → 자막 번인 → 나레이션 믹스 → 최종 렌더.
    Returns: final mp4 경로 (out_dir/final_shorts.mp4)
    """
    from engine.video.ffmpeg_composer import compose_final, concat_cuts
    from engine.video.subtitle_renderer import build_ass, burn_in

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if media.intro_image is None or media.outro_image is None:
        raise ShortsMediaError("북엔드 이미지 누락 — assemble 불가")
    # v1.3.0: 컷 수 3 하드코딩 제거. 주간 다이제스트는 2컷이다.
    # (2026-09-06 run #34004565648: 시나리오 2컷인데 조립이 3컷을 요구해 실패)
    expected_cuts = len(scenario.cuts)
    if len(media.cut_paths) != expected_cuts:
        raise ShortsMediaError(
            f"본편 컷 수 불일치: 파일 {len(media.cut_paths)}개 / "
            f"시나리오 {expected_cuts}컷"
        )

    # v1.1.0: 북엔드 길이는 타임라인(나레이션 길이 기반)과 반드시 동일해야 한다.
    timeline = {t.label: t for t in build_timeline(scenario)}
    intro_sec = int(round(timeline["intro"].end_sec - timeline["intro"].start_sec))
    outro_sec = int(round(timeline["outro"].end_sec - timeline["outro"].start_sec))
    intro_clip = still_to_clip(
        media.intro_image, out_dir / "intro_clip.mp4", duration_sec=intro_sec
    )
    outro_clip = still_to_clip(
        media.outro_image, out_dir / "outro_clip.mp4", duration_sec=outro_sec
    )

    concat_path = str(out_dir / "concat.mp4")
    concat_cuts(
        [str(intro_clip), *[str(p) for p in media.cut_paths], str(outro_clip)],
        concat_path,
    )

    current = concat_path
    if burn_subtitles:
        ass_path = build_ass(build_subtitle_items(scenario), str(out_dir / "subs.ass"))
        current = burn_in(current, ass_path, str(out_dir / "with_subs.mp4"))

    narrations = generate_narrations(scenario, out_dir / "tts")
    mixed = mix_narrations(Path(current), narrations, out_dir / "with_audio.mp4")

    final_path = compose_final(str(mixed), str(out_dir / "final_shorts.mp4"))
    total_sec = build_timeline(scenario)[-1].end_sec
    logger.info(
        "[shorts_media] v%s 조립 완료: %s (총 %.0fs, media cost=$%.4f)",
        VERSION,
        final_path,
        total_sec,
        media.total_cost_usd,
    )
    return Path(final_path)


# ────────────────────────────────────────────────────────
# 저장 (video_assets 상태 전이)
# ────────────────────────────────────────────────────────


def persist_media(episode_id: str, media: MediaResult) -> None:
    """S3/S4 완료 → status='media_generated' + 경로/비용 기록."""
    from engine.common.supabase_client import icg_table

    uris = [str(p) for p in media.cut_paths]
    icg_table("video_assets").update(
        {
            "status": "media_generated",
            "intro_image_uri": str(media.intro_image) if media.intro_image else None,
            "outro_image_uri": str(media.outro_image) if media.outro_image else None,
            "cut1_video_uri": uris[0] if len(uris) > 0 else None,
            "cut2_video_uri": uris[1] if len(uris) > 1 else None,
            "cut3_video_uri": uris[2] if len(uris) > 2 else None,
            "veo_cost_usd": media.total_cost_usd,
        }
    ).eq("episode_id", episode_id).execute()
    logger.info(
        "[shorts_media] persist media: %s cost=$%.4f", episode_id, media.total_cost_usd
    )


def persist_assembled(episode_id: str, final_path: Path) -> None:
    """S5 완료 → status='assembled' + 최종 경로 + artifact run_id 기록 (publish 복원용)."""
    from engine.common.supabase_client import icg_table

    icg_table("video_assets").update(
        {
            "status": "assembled",
            "final_video_uri": str(final_path),
            "artifact_run_id": os.environ.get("GITHUB_RUN_ID"),
        }
    ).eq("episode_id", episode_id).execute()
    logger.info("[shorts_media] persist assembled: %s -> %s", episode_id, final_path)
