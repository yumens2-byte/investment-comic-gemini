"""DR-04 canary: dry run compiles one panel; outcomes are classified, never retried."""
import json

import pytest

from engine.image.generation_guard import GenerationHold
from scripts import run_path_canary as canary


@pytest.fixture
def notion_pages(monkeypatch):
    import engine.common.notion_loader as loader

    monkeypatch.setenv("NOTION_IMAGE_PROMPTS_ID", "img")
    monkeypatch.setenv("NOTION_REF_PROMPTS_ID", "ref")
    pages = {"img": "GLOBAL_STYLE_BLOCK\nstyle\nSECURITY_NEGATIVE_BLOCK_V1_1\nNEGATIVE PROMPT:\nno text",
             "ref": "CHAR_DESIGN_SPECS\n{}"}
    monkeypatch.setattr(loader, "_load_page_cached", lambda pid: pages[pid])


def test_fixture_compiles_to_one_paid_panel(notion_pages):
    prompt = canary.build_canary_prompt("ONE_VS_ONE:COMBAT")
    assert prompt.panel_idx == 1 and len(prompt.ref_image_paths) == 2
    assert "DYNAMIC ACTION" in prompt.prompt_text


def test_dry_run_makes_no_paid_call(notion_pages, monkeypatch):
    import engine.image.gemini_client as client

    monkeypatch.setattr(client, "generate_panel",
                        lambda *a, **k: pytest.fail("dry run must not call the provider"))
    report = canary.run("ONE_VS_ONE:COMBAT", dry_run=True)
    assert report["status"] == "dry_run" and report["paid_calls"] == 0
    assert len(report["fingerprint"]) == 64


@pytest.mark.parametrize("exc,expected", [
    (None, ("pass", None)),
    (GenerationHold("provider refused image; provider_reason=FinishReason.PROHIBITED_CONTENT; "
                    "panel=1"), ("refused", "FinishReason.PROHIBITED_CONTENT")),
    (GenerationHold("generation budget exhausted"), ("error", "GenerationHold")),
])
def test_outcome_classification(exc, expected):
    assert canary.classify(exc) == expected


def test_live_run_records_outcome_once(notion_pages, monkeypatch, tmp_path):
    import engine.image.gemini_client as client
    from engine.common import supabase_client

    calls, inserted = [], []

    def refuse(*args, **kwargs):
        calls.append(args)
        raise GenerationHold("provider refused image; provider_reason=SAFETY; panel=1")

    class Table:
        def insert(self, row):
            inserted.append(row)
            return self

        def execute(self):
            return None

    monkeypatch.setattr(client, "generate_panel", refuse)
    monkeypatch.setattr(supabase_client, "icg_table", lambda name: Table())
    monkeypatch.chdir(tmp_path)
    import shutil
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    shutil.copytree(root / "config", tmp_path / "config")
    shutil.copytree(root / "assets", tmp_path / "assets")
    report = canary.run("ONE_VS_ONE:COMBAT", dry_run=False)
    assert len(calls) == 1
    assert report["status"] == "refused" and report["finish_reason"] == "SAFETY"
    assert inserted[0]["path_key"] == "ONE_VS_ONE:COMBAT" and inserted[0]["status"] == "refused"
    json.dumps(report)
