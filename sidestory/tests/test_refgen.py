"""refgen (F3) and the Notion REF_PROMPTS loader, offline."""
from __future__ import annotations

import hashlib
from types import SimpleNamespace

import pytest

from sidestory.adapters.notion.prompt_loader import NotionPromptSource, parse_ref_prompts
from sidestory.app.refgen import POSE_ORDER, REF_ASPECT, run_refgen
from sidestory.ports.llm import LLMError
from sidestory.tests.fixtures import FakeStore
from sidestory.tests.p1_fixtures import FakeImages

PROMPTS = {p: f"prompt {p} " * 50 for p in POSE_ORDER}


class _Prompts:
    def __init__(self, data=None, error=None):
        self.data, self.error = data or PROMPTS, error

    def ref_prompts(self):
        if self.error:
            raise self.error
        return self.data


def test_refgen_order_attachment_aspect_and_hashes(tmp_path) -> None:
    images, store = FakeImages(), FakeStore()
    res = run_refgen(2, images=images, prompts=_Prompts(), store=store,
                     output_root=tmp_path / "output/sidestory")
    assert res.status == "ok"
    assert [c[0] for c in images.calls] == [1, 2, 3, 4, 5]
    assert images.calls[0][2] == []  # front: no (watermarked) image input
    assert all(c[2] == [tmp_path / "output/sidestory/refs/r2/zero_block_front.png"]
               for c in images.calls[1:])
    assert images.aspects == [REF_ASPECT] * 5
    assert all(c[3] == tmp_path / "output/sidestory/refs/r2/panels" for c in images.calls)
    for pose, f in res.files.items():
        data = (tmp_path / f"output/sidestory/refs/r2/zero_block_{pose}.png").read_bytes()
        assert f["sha256"] == hashlib.sha256(data).hexdigest()
        assert f'{pose}:' in res.detail["characters_side_yaml_refs"] and f["sha256"] in \
            res.detail["characters_side_yaml_refs"]
    assert (tmp_path / "output/sidestory/refs/r2/refs.json").is_file()
    assert store.logs[-1][0:2] == ("refgen", "ok")


def test_refgen_hold_stops_and_logs(tmp_path) -> None:
    store = FakeStore()
    res = run_refgen(1, images=FakeImages(hold_on=3), prompts=_Prompts(), store=store,
                     output_root=tmp_path)
    assert res.status == "hold" and "back" in res.detail["reason"]
    assert set(res.files) == {"front", "side"}
    assert store.logs[-1][1] == "hold"


@pytest.mark.parametrize("rev", [0, 1000])
def test_refgen_revision_bounds(tmp_path, rev) -> None:
    res = run_refgen(rev, images=FakeImages(), prompts=_Prompts(), store=None,
                     output_root=tmp_path)
    assert res.status == "error" and "revision" in res.detail["reason"]


def test_refgen_prompt_error(tmp_path) -> None:
    images = FakeImages()
    res = run_refgen(1, images=images, prompts=_Prompts(error=LLMError("x")), store=None,
                     output_root=tmp_path)
    assert res.status == "error" and images.calls == []


def _blk(t, text, **extra):
    return {"type": t, t: {"rich_text": [{"plain_text": text}], **extra}, **extra}


def test_parse_ref_prompts() -> None:
    blocks = [_blk("heading_2", "front"), _blk("code", "F" * 10),
              _blk("paragraph", "note"), _blk("heading_2", "Back"), _blk("code", "B"),
              _blk("code", "ignored second"), _blk("heading_2", "other"), _blk("code", "X")]
    assert parse_ref_prompts(blocks) == {"front": "F" * 10, "back": "B"}


def test_notion_ref_prompts_child_page_lookup() -> None:
    page_blocks = [{"type": "paragraph", "paragraph": {"rich_text": [{"plain_text": "s" * 300}]}},
                   {"type": "child_page", "id": "decoy", "child_page": {"title": "OLD_NOTES"}},
                   {"type": "child_page", "id": "child-1", "child_page": {"title": "REF_PROMPTS"}}]
    ref_blocks = []
    for p in POSE_ORDER:
        ref_blocks += [_blk("heading_2", p), _blk("code", f"{p} " * 200)]
    pages = {"sys": page_blocks, "child1": ref_blocks, "decoy": []}

    class Session:
        def get(self, url, headers, timeout):
            key = url.split("/blocks/")[1].split("/")[0]
            return SimpleNamespace(status_code=200,
                                   json=lambda: {"results": pages[key], "has_more": False})

    src = NotionPromptSource("sys", "tok", Session())
    assert set(src.ref_prompts()) == set(POSE_ORDER)
    assert "REF_PROMPTS" not in src.system_prompt()  # child page is not system prompt text
    pages["child1"] = ref_blocks[:-2]
    with pytest.raises(LLMError, match="defense"):
        src.ref_prompts()
    pages["sys"] = page_blocks[:2]
    with pytest.raises(LLMError, match="not found"):
        src.ref_prompts()
