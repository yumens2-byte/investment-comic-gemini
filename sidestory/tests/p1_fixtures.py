"""Fakes and builders for P1 tests (no network, no paid calls)."""
from __future__ import annotations

import copy
import hashlib
from pathlib import Path

from PIL import Image

from sidestory.core.echo import build_echo_pack
from sidestory.core.models import EchoPack
from sidestory.ports.image import ImageHold
from sidestory.ports.llm import LLMError
from sidestory.tests.fixtures import arc_row, main_row, market_row

SYSTEM_PROMPT = "외전 시스템 프롬프트 " * 30


def echo_for(outcome: str = "HERO_VICTORY", scenario: str = "ONE_VS_ONE",
             day: str = "2026-10-06") -> EchoPack:
    return build_echo_pack(day, main_row(day, outcome, scenario), market_row(day), arc_row())


def raw_script(title: str = "첨탑 아래의 방패", pose4: str = "side",
               silhouettes5: list[str] | None = None) -> dict:
    sil = ["node_c"] if silhouettes5 is None else silhouettes5
    panel = {"camera": "wide shot", "setting": "neon cyber city at night",
             "action": "data streams drift between towers", "market_ref": None}
    return {
        "title": "관측 기록 001",
        "logline": "승리의 잔해 속에서 흐름을 기록하는 관찰자",
        "caption_fb": "본편이 끝난 자리, 데이터는 여전히 흐른다.",
        "panels": [
            {**panel, "idx": 1, "panel_type": "COVER", "key_text": "관측 개시",
             "narration": "도시는 아직 숨을 고른다", "zero_block_pose": "back", "silhouettes": []},
            {**panel, "idx": 2, "panel_type": "TENSION", "key_text": "본편 기록",
             "narration": f"「{title}」 — 방패는 버텼다", "zero_block_pose": "none",
             "silhouettes": []},
            {**panel, "idx": 3, "panel_type": "TENSION", "key_text": "흐름",
             "narration": "VIX 15.31, 붕괴 데이터가 흘러간다", "zero_block_pose": "none",
             "silhouettes": []},
            {**panel, "idx": 4, "panel_type": "CLIMAX", "key_text": "기록 중",
             "narration": "나는 개입하지 않는다", "zero_block_pose": pose4, "silhouettes": []},
            {**panel, "idx": 5, "panel_type": "CLIMAX", "key_text": "",
             "narration": "지평선 너머 무언가가 서 있다", "zero_block_pose": "none",
             "silhouettes": sil},
            {**panel, "idx": 6, "panel_type": "AFTERMATH", "key_text": "구조는 그대로다",
             "narration": "승리는 구조를 바꾸지 않는다", "zero_block_pose": "front",
             "silhouettes": []},
        ],
        "side_threads": ["흘러간 붕괴 데이터의 행방"],
        "next_hook_side": "다음 균열은 어디서 오는가",
    }


class FakeLLM:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.calls: list[tuple[str, str]] = []

    def generate_script(self, system_prompt, user_prompt):
        self.calls.append((system_prompt, user_prompt))
        item = self.outputs.pop(0) if self.outputs else self.outputs_last
        if isinstance(item, Exception):
            raise item
        return copy.deepcopy(item)

    @property
    def outputs_last(self):
        raise LLMError("no more fake outputs")


class FakePrompts:
    def __init__(self, text: str = SYSTEM_PROMPT, error: Exception | None = None):
        self.text, self.error = text, error

    def system_prompt(self):
        if self.error:
            raise self.error
        return self.text


class FakeImages:
    def __init__(self, hold_on: int | None = None):
        self.hold_on = hold_on
        self.calls: list[tuple[int, str, list[Path], Path]] = []

    def generate(self, panel_idx, prompt, refs, output_dir):
        self.calls.append((panel_idx, prompt, list(refs), output_dir))
        if panel_idx == self.hold_on:
            raise ImageHold("ledger cap reached")
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / f"P{panel_idx}.png"
        Image.new("RGB", (64, 80), (20 * panel_idx, 40, 90)).save(path)
        return path, 0.039


class FakeComposer:
    def __init__(self, size=(1080, 1350)):
        self.size = size
        self.calls = 0

    def compose(self, panels, images, output_dir):
        self.calls += 1
        output_dir.mkdir(parents=True, exist_ok=True)
        out = []
        for p in panels:
            path = output_dir / f"S{p['idx']}.png"
            Image.new("RGB", self.size, (p["idx"] * 10, 0, 0)).save(path)
            out.append(path)
        return out


def make_refs(root: Path) -> dict:
    """characters_side-shaped dict with real REF files under root."""
    refs = {}
    for pose in ("front", "side", "back", "attack", "defense"):
        rel = f"sidestory/assets/refs/zero_block_{pose}.png"
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (32, 32), (len(pose) * 20, 0, 120)).save(path)
        refs[pose] = {"path": rel, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    return {
        "anti_heroes": {"CHAR_ANTI_HERO_001": {
            "name": "Zero Block", "refs": refs, "visual_lock": ["full hood, face never visible"],
            "gdl": "TYPE_B independent — CENTER placement"}},
        "nodes": [{"key": "node_a", "silhouette": "small fast afterimage"},
                  {"key": "node_b", "silhouette": "white-noise hologram"},
                  {"key": "node_c", "silhouette": "cube-fortress on the horizon"}],
    }
