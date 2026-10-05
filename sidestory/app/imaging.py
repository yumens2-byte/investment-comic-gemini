"""Deterministic panel clean-up before slide composition (B1, pilot 1 re-run).

The image model sometimes returns letterboxed (black bars) or framed (white margin +
black rule) images despite the prompt (pilot 1: P2 white frame 143/31 px, P5 black bars
96 px). Uniform edge bands are cut from a copy; the paid original stays untouched because
the ledger stores its hash.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

BAND_MAX_STD = 5.0        # a band row/column is (almost) a single tone
BAND_DARK = 20.0          # ... and that tone is near black
BAND_LIGHT = 235.0        # ... or near white
MIN_BAND_PX = 8           # thinner than this is anti-aliasing, not a band
MAX_SIDE_RATIO = 0.30     # never cut more than 30% from one side
# Kept area below this = misdetection → hold. v8.10: 0.60 → 0.50 (pilot 2 P5: a real white
# letterbox around a wide scene kept 58.6% with no content lost).
MIN_KEEP_RATIO = 0.50
MAX_KEPT_ASPECT = 2.0     # kept region wider/taller than 2:1 = unusable strip → hold
# Relaxed criteria, only next to a detected band: frame rule / anti-aliased fringe.
RULE_MAX_STD = 15.0
RULE_DARK = 30.0
RULE_LIGHT = 150.0
RULE_MAX_PX = 6
SAFETY_PX = 4              # extra shave on banded sides (residual 1-3 px frame rule)


@dataclass(frozen=True)
class TrimResult:
    box: tuple[int, int, int, int]   # left, top, right, bottom of the kept region
    size: tuple[int, int]
    kept_ratio: float

    @property
    def trimmed(self) -> bool:
        return self.box != (0, 0, *self.size)

    @property
    def aspect(self) -> float:
        """Long side / short side of the kept region (1.0 = square)."""
        w, h = self.box[2] - self.box[0], self.box[3] - self.box[1]
        return max(w, h) / max(1, min(w, h))


def _edge_run(mean: np.ndarray, std: np.ndarray, *, max_std: float = BAND_MAX_STD,
              dark: float = BAND_DARK, light: float = BAND_LIGHT) -> int:
    n = 0
    for m, sd in zip(mean, std, strict=True):
        if sd < max_std and (m < dark or m > light):
            n += 1
        else:
            break
    return n


def _profiles(gray: np.ndarray) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    rm, rs, cm, cs = gray.mean(1), gray.std(1), gray.mean(0), gray.std(0)
    return {"top": (rm, rs), "bottom": (rm[::-1], rs[::-1]),
            "left": (cm, cs), "right": (cm[::-1], cs[::-1])}


def detect_bands(img: Image.Image) -> TrimResult:
    """Strict pass finds solid bands; on sides that had a band, a relaxed pass then removes
    the leftover frame rule / anti-aliased fringe (pilot 1 P2: white margin + black rule)."""
    gray = np.asarray(img.convert("L"), dtype=float)
    h, w = gray.shape
    cut = {"top": 0, "bottom": 0, "left": 0, "right": 0}
    limit = {"top": h, "bottom": h, "left": w, "right": w}
    banded: set[str] = set()
    ruled: set[str] = set()   # relaxed pass applied once per side, max RULE_MAX_PX
    for _ in range(3):
        sub = gray[cut["top"]:h - cut["bottom"], cut["left"]:w - cut["right"]]
        changed = False
        for side, (m, sd) in _profiles(sub).items():
            run = _edge_run(m, sd)
            strict = run >= MIN_BAND_PX
            if not strict:
                run = 0
                if side in banded and side not in ruled:
                    ruled.add(side)
                    run = min(_edge_run(m, sd, max_std=RULE_MAX_STD, dark=RULE_DARK,
                                        light=RULE_LIGHT), RULE_MAX_PX)
            if run and cut[side] + run <= limit[side] * MAX_SIDE_RATIO:
                cut[side] += run
                changed = True
                if strict:
                    banded.add(side)
        if not changed:
            break
    for side in banded:
        cut[side] += SAFETY_PX
    box = (cut["left"], cut["top"], w - cut["right"], h - cut["bottom"])
    kept = (box[2] - box[0]) * (box[3] - box[1]) / float(w * h)
    return TrimResult(box=box, size=(w, h), kept_ratio=round(kept, 4))


def trim_panel(src: Path, dst_dir: Path) -> tuple[Path, TrimResult]:
    """Return (path to use for composition, result). Writes a copy only when trimmed."""
    with Image.open(src) as img:
        img.load()
        res = detect_bands(img)
        if not res.trimmed:
            return src, res
        dst_dir.mkdir(parents=True, exist_ok=True)
        dst = dst_dir / src.name
        img.crop(res.box).save(dst, "PNG")
    return dst, res
