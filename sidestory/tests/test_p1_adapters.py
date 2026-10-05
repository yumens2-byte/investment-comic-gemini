"""ICG adapters (whitelisted engine symbols) and Notion loader, all offline."""
from __future__ import annotations

from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from sidestory.adapters.icg import image_adapter
from sidestory.adapters.icg.composer_adapter import PilSlideComposer
from sidestory.adapters.icg.llm_adapter import ClaudeNarrativeLLM
from sidestory.adapters.notion.prompt_loader import NotionPromptSource, blocks_to_text
from sidestory.app.p1 import P1Deps, run_p1
from sidestory.ports.image import ImageHold
from sidestory.ports.llm import LLMError
from sidestory.tests.fixtures import FakeFeed, FakeStore, main_row
from sidestory.tests.p1_fixtures import FakeImages, FakeLLM, FakePrompts, make_refs, raw_script


class _Messages:
    def __init__(self, text=None, exc=None):
        self.text, self.exc, self.kwargs = text, exc, None

    def create(self, *, model, max_tokens, system, messages, **extra):
        self.kwargs = {"model": model, "system": system, "messages": messages, **extra}
        if self.exc:
            raise self.exc
        return SimpleNamespace(content=[SimpleNamespace(text=self.text)],
                               usage=SimpleNamespace(input_tokens=10, output_tokens=20))


def test_llm_adapter_parses_fenced_json() -> None:
    msgs = _Messages('설명\n```json\n{"title": "t"}\n```')
    llm = ClaudeNarrativeLLM(client=SimpleNamespace(messages=msgs), model="m")
    assert llm.generate_script("SYS", "USER") == {"title": "t"}
    assert msgs.kwargs["system"] == "SYS" and msgs.kwargs["model"] == "m"
    assert msgs.kwargs["messages"] == [{"role": "user", "content": "USER"}]
    assert llm.usage == [{"input": 10, "output": 20}]


@pytest.mark.parametrize("text,exc", [("not json at all", None), ("[1, 2]", None),
                                      (None, RuntimeError("529 overloaded"))])
def test_llm_adapter_errors_are_typed(text, exc) -> None:
    llm = ClaudeNarrativeLLM(client=SimpleNamespace(messages=_Messages(text, exc)), model="m")
    with pytest.raises(LLMError):
        llm.generate_script("S", "U")


def test_llm_adapter_requires_key(monkeypatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(LLMError, match="ANTHROPIC_API_KEY"):
        ClaudeNarrativeLLM().generate_script("S", "U")


def test_llm_model_env(monkeypatch) -> None:
    monkeypatch.setenv("SIDESTORY_LLM_MODEL", "claude-x")
    assert ClaudeNarrativeLLM(client=object()).model == "claude-x"
    monkeypatch.delenv("SIDESTORY_LLM_MODEL")
    assert ClaudeNarrativeLLM(client=object()).model == "claude-sonnet-4-6"


def test_image_adapter_maps_hold_and_none(monkeypatch, tmp_path) -> None:
    from engine.image.generation_guard import GenerationHold

    seen = {}

    def ok(idx, prompt, refs, out, log, aspect, *, guard=None):
        seen.update(idx=idx, log=log, aspect=aspect)
        return out / f"P{idx}.png", 0.04

    monkeypatch.setattr(image_adapter, "generate_panel", ok)
    out = tmp_path / "output/sidestory/2026-10-06/panels"
    path, cost = image_adapter.GeminiPanelGenerator().generate(3, "p", [], out)
    assert path == out / "P3.png" and cost == 0.04
    assert seen["log"] == out.parent / "gemini_run.log" and seen["aspect"] is None

    def hold(*a, **k):
        raise GenerationHold("Daily image call cap reached")

    monkeypatch.setattr(image_adapter, "generate_panel", hold)
    with pytest.raises(ImageHold, match="cap"):
        image_adapter.GeminiPanelGenerator().generate(3, "p", [], out)
    monkeypatch.setattr(image_adapter, "generate_panel", lambda *a, **k: (None, 0.08))
    with pytest.raises(ImageHold, match="no valid image"):
        image_adapter.GeminiPanelGenerator().generate(3, "p", [], out)


def test_notion_loader_paginates_and_formats() -> None:
    def block(t, text):
        return {"type": t, t: {"rich_text": [{"plain_text": text}]}}

    pages = [
        {"results": [block("heading_2", "규칙"), block("paragraph", "가" * 150),
                     block("image", "skip")], "has_more": True, "next_cursor": "c1"},
        {"results": [block("bulleted_list_item", "항목"), block("code", "나" * 100)],
         "has_more": False},
    ]
    urls = []

    class Session:
        def get(self, url, headers, timeout):
            urls.append(url)
            assert headers["Authorization"] == "Bearer tok"
            return SimpleNamespace(status_code=200, json=lambda: pages[len(urls) - 1])

    text = NotionPromptSource("ab-cd", "tok", Session()).system_prompt()
    assert text.startswith("## 규칙") and "- 항목" in text and "skip" not in text
    assert "start_cursor=c1" in urls[1] and "/blocks/abcd/" in urls[0]


@pytest.mark.parametrize("status,body,match", [
    (404, {}, "HTTP 404"), (200, {"results": [], "has_more": False}, "too short")])
def test_notion_loader_failures(status, body, match) -> None:
    session = SimpleNamespace(get=lambda *a, **k: SimpleNamespace(status_code=status,
                                                                   json=lambda: body))
    with pytest.raises(LLMError, match=match):
        NotionPromptSource("p", "t", session).system_prompt()
    with pytest.raises(LLMError, match="missing"):
        NotionPromptSource("", "", session).system_prompt()


def test_blocks_to_text_ignores_unknown() -> None:
    assert blocks_to_text([{"type": "divider", "divider": {}}]) == []


def test_real_pil_composer_full_p1_flow(tmp_path, monkeypatch) -> None:
    """Fake LLM/images, REAL main compose_episode (strict): 8 slides 1080x1350."""
    monkeypatch.chdir(tmp_path)
    deps = P1Deps(feed=FakeFeed([main_row("2026-10-06")], fingerprints=("a" * 64,)),
                  store=FakeStore(), llm=FakeLLM([raw_script()]), prompts=FakePrompts(),
                  images=FakeImages(), composer=PilSlideComposer(),
                  characters=make_refs(tmp_path), output_root=tmp_path / "output/sidestory",
                  ref_root=tmp_path)
    results = run_p1(date(2026, 10, 6), deps)
    assert results[-1].status == "assembled", results[-1].detail
    row = deps.store.get_episode("SIDE-2026-10-06-01")
    for slide in row["slides_json"]:
        with Image.open(Path(slide["path"])) as img:
            assert img.size == (1080, 1350)


def test_composer_refuses_without_korean_font(tmp_path) -> None:
    composer = PilSlideComposer(font_candidates=(tmp_path / "missing.ttc",))
    with pytest.raises(ValueError, match="Korean font"):
        composer.compose([], [], tmp_path)
