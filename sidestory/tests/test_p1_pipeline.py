"""P1 orchestration with fakes: draft → assembled, holds, resume, CAS, SG-7."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from sidestory.app.p1 import MAX_NARRATIVE_ATTEMPTS, P1Deps, render_user_prompt, run_p1, run_stage
from sidestory.ports.llm import LLMError
from sidestory.tests.fixtures import FakeFeed, FakeStore, main_row
from sidestory.tests.p1_fixtures import (
    FakeComposer,
    FakeImages,
    FakeLLM,
    FakePrompts,
    echo_for,
    make_refs,
    raw_script,
)

TUE = date(2026, 10, 6)
SID = "SIDE-2026-10-06-01"


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    store = FakeStore()
    deps = P1Deps(
        feed=FakeFeed([main_row("2026-10-06")], fingerprints=("a" * 64,)),
        store=store, llm=FakeLLM([raw_script()]), prompts=FakePrompts(),
        images=FakeImages(), composer=FakeComposer(), characters=make_refs(tmp_path),
        output_root=tmp_path / "output/sidestory", ref_root=tmp_path)
    return deps


def _statuses(results):
    return [(r.stage, r.status) for r in results]


def test_p1_full_flow_from_new_slot(env) -> None:
    results = run_p1(TUE, env)
    assert _statuses(results) == [("echo", "draft"), ("narrative", "narrative_done"),
                                  ("image", "image_done"), ("assembly", "assembled")]
    row = env.store.get_episode(SID)
    assert row["status"] == "assembled"
    assert len(row["script_json"]["panels"]) == 8
    assert [p["idx"] for p in row["panels_json"]["panels"]] == [1, 2, 3, 4, 5, 6]
    assert len(row["slides_json"]) == 8 and set(row["manifest_json"]["slides"]) == {
        f"S{i}.png" for i in range(1, 9)}
    # REF attached only for posed panels; side REF for P4.
    calls = {c[0]: c for c in env.images.calls}
    assert calls[2][2] == [] and calls[4][2][0].name == "zero_block_side.png"
    assert all(c[3].as_posix().endswith("output/sidestory/2026-10-06/panels")
               for c in env.images.calls)
    assert [g.gate for g in results[1].gates] == ["SG-1", "SG-7"]
    assert {g.gate for g in results[2].gates} == {"SG-1", "SG-2", "SG-7"}
    assert {g.gate for g in results[3].gates} == {"SG-1", "SG-6", "SG-7"}
    assert [log[1] for log in env.store.logs] == ["ok", "ok", "ok", "ok"]
    # rerun = nothing left to do (idempotent)
    assert run_p1(TUE, env) == []


def test_p1_skips_non_slot_day_without_writing(env) -> None:
    results = run_p1(date(2026, 10, 7), env)
    assert _statuses(results) == [("echo", "skipped")]
    assert env.store.episodes == {}


def test_narrative_regenerates_with_feedback_then_passes(env) -> None:
    bad = raw_script()
    bad["panels"][3]["zero_block_pose"] = "attack"
    env.llm = FakeLLM([LLMError("unparseable JSON"), bad, raw_script()])
    results = run_p1(TUE, env)
    assert results[-1].status == "assembled"
    assert results[1].detail["attempts"] == 3
    assert "pose attack" in env.llm.calls[2][1]  # feedback reached the 3rd prompt
    assert "output error" in env.llm.calls[1][1]


def test_narrative_holds_after_max_attempts(env) -> None:
    bad = raw_script()
    bad["panels"][2]["narration"] = "VIX 17.80"
    env.llm = FakeLLM([bad] * MAX_NARRATIVE_ATTEMPTS)
    results = run_p1(TUE, env)
    assert results[-1].stage == "narrative" and results[-1].status == "hold"
    row = env.store.get_episode(SID)
    assert row["status"] == "hold" and "EC-2" in row["error_message"]
    assert row.get("script_json") is None
    assert len(env.llm.calls) == MAX_NARRATIVE_ATTEMPTS
    assert env.images.calls == []


def test_hold_requires_retry_flag_then_resumes(env) -> None:
    env.llm = FakeLLM([LLMError("x")] * MAX_NARRATIVE_ATTEMPTS)
    run_p1(TUE, env)
    blocked = run_p1(TUE, env)
    assert _statuses(blocked) == [("p1", "hold")] and "--retry-hold" in blocked[0].detail["reason"]
    env.llm = FakeLLM([raw_script()])
    resumed = run_p1(TUE, env, retry_hold=True)
    assert resumed[-1].status == "assembled"
    assert ("p1", "resume", {"sid": SID, "status": "draft"}) in env.store.logs


def test_system_prompt_failure_holds_without_llm_call(env) -> None:
    env.prompts = FakePrompts(error=LLMError("NOTION_SIDE_SYSTEM_ID missing"))
    results = run_p1(TUE, env)
    assert results[-1].status == "hold" and env.llm.calls == []


def test_sg2_pending_ref_holds_before_any_paid_call(env) -> None:
    env.characters["anti_heroes"]["CHAR_ANTI_HERO_001"]["refs"]["side"]["sha256"] = "__PENDING__"
    results = run_p1(TUE, env)
    assert results[-1].stage == "image" and results[-1].status == "hold"
    assert "SG-2" in [g.gate for g in results[-1].gates] and env.images.calls == []
    assert env.store.get_episode(SID)["status"] == "hold"


def test_sg2_tampered_ref_holds(env, tmp_path) -> None:
    (tmp_path / "sidestory/assets/refs/zero_block_side.png").write_bytes(b"tampered")
    results = run_p1(TUE, env)
    assert results[-1].status == "hold" and "mismatch" in results[-1].detail["reason"]


def test_image_hold_records_progress_and_stops(env) -> None:
    env.images = FakeImages(hold_on=4)
    results = run_p1(TUE, env)
    last = results[-1]
    assert last.stage == "image" and last.status == "hold"
    assert [p["idx"] for p in last.detail["panels_done"]] == [1, 2, 3]
    assert [g.gate for g in last.gates] == ["SG-1", "SG-2"]
    row = env.store.get_episode(SID)
    assert row["status"] == "hold" and row.get("panels_json") is None
    # resume from hold goes back to image (script kept), not narrative
    env.images = FakeImages()
    resumed = run_p1(TUE, env, retry_hold=True)
    assert _statuses(resumed) == [("image", "image_done"), ("assembly", "assembled")]


def test_assembly_requires_panel_artifacts(env, tmp_path) -> None:
    run_stage_results = run_p1(TUE, env)
    assert run_stage_results[-1].status == "assembled"
    row = env.store.get_episode(SID)
    row["status"] = "image_done"
    Path(row["panels_json"]["panels"][0]["path"]).unlink()
    res = run_stage("assembly", TUE, env)
    assert res.status == "hold" and "artifact" in res.detail["reason"]


def test_assembly_rejects_wrong_slide_size(env) -> None:
    env.composer = FakeComposer(size=(1080, 1080))
    results = run_p1(TUE, env)
    assert results[-1].stage == "assembly" and results[-1].status == "hold"


def test_sg7_main_change_holds(env) -> None:
    env.feed = FakeFeed([main_row("2026-10-06")], fingerprints=("a" * 64,) * 5 + ("b" * 64,))
    results = run_p1(TUE, env)
    # reads: echo 1-2, narrative 3-4, image before=5th (a) after=6th (b) → SG-7 hold
    assert results[1].status == "narrative_done"
    assert results[2].status == "hold" and results[2].detail["reason"] == (
        "main state changed during side run")
    assert env.store.get_episode(SID)["status"] == "hold"


def test_stage_order_enforced(env) -> None:
    run_p1(TUE, env)  # assembled
    res = run_stage("narrative", TUE, env)
    assert res.status == "error" and "requires status" in res.detail["reason"]
    assert run_stage("image", date(2026, 10, 8), env).detail["reason"] == "slot not echoed yet"


def test_cas_conflict_reports_error(env) -> None:
    run_p1(TUE, env)
    store = env.store
    original = store.update_episode
    store.episodes[SID]["status"] = "image_done"
    store.update_episode = lambda sid, fields, expect_status: False
    res = run_stage("assembly", TUE, env)
    store.update_episode = original
    assert res.status == "error" and "compare-and-set" in res.detail["reason"]


def test_previous_side_hook_is_carried(env) -> None:
    env.store.episodes["SIDE-2026-10-01-01"] = {"status": "assembled",
                                                "script_json": {"next_hook_side": "균열의 좌표"}}
    run_p1(TUE, env)
    assert "균열의 좌표" in env.llm.calls[0][1]


def test_user_prompt_render_contains_contract() -> None:
    echo = echo_for()
    text = render_user_prompt(side_episode_id_=SID, echo=echo, nn_stage="E01",
                              previous_hook=None, feedback=["P4 pose attack"])
    assert "첨탑 아래의 방패" in text and "us10y = 5.24" in text
    assert "본 콘텐츠는 투자 참고 정보이며, 투자 권유가 아닙니다" in text
    assert "P4 pose attack" in text and "dollar_index" not in text
    for idx in range(1, 7):
        assert f"- P{idx} [" in text
