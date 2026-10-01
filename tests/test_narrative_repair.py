import copy
import json
from pathlib import Path

import pytest

from engine.arc.arc_state_engine import update_after_episode
from engine.narrative.continuity_score import score_story_continuity
from engine.narrative.serial_contracts import merge_thread_ledger, normalize_thread
from engine.narrative.state_candidate import build_state_candidate
from engine.narrative.thread_contracts import (
    review_fingerprint,
    validate_thread_transitions,
)
from engine.publish.manifest import build_manifest, validate_manifest


def test_actual_episode_cannot_pass_by_copying_unanswered_question():
    fixture = json.loads((Path(__file__).parent / "fixtures/continuity_false_resolution_20261002.json").read_text())
    score = score_story_continuity(fixture["script"], {"previous_episode": fixture["previous_episode"]})
    assert score.status == "fail"
    assert "unverified_resolved_thread" in score.missing_requirements


def contract():
    previous = {"unresolved_threads": ["문 안쪽의 인물은 누구인가"]}
    thread = normalize_thread(previous["unresolved_threads"][0])
    script = {"panels": [{"idx": 1, "narration": "문 안의 인물은 누나였다."}],
              "resolved_threads": [thread["promise"]], "thread_transitions": [{
                  "thread_id": thread["thread_id"], "status": "RESOLVED",
                  "evidence_panel_idxs": [1], "evidence_quote": "문 안의 인물은 누나였다.",
                  "new_fact": "누나의 정체 확인", "resolution_result": "인물의 정체를 확인했다",
              }]}
    return previous, thread, script


def test_resolution_needs_independent_review_bound_to_content():
    previous, thread, script = contract()
    assert validate_thread_transitions(script, previous) == ["thread_resolution_review_required"]
    review = {"script_hash": review_fingerprint(script), "resolutions": {
        thread["thread_id"]: {"status": "PASS", "evidence_quote": "문 안의 인물은 누나였다."}}}
    assert validate_thread_transitions(script, previous, review) == []
    script["panels"][0]["narration"] += " 하지만 아직 모른다."
    assert "thread_resolution_review_required" in validate_thread_transitions(script, previous, review)


@pytest.mark.parametrize("change,error", [
    ({"thread_id": "unknown"}, "unknown_or_duplicate_thread"),
    ({"evidence_panel_idxs": [8]}, "thread_evidence_panel_missing"),
    ({"evidence_quote": "조작된 인용"}, "thread_evidence_missing"),
    ({"resolution_result": "여전히 모르고 있다"}, "false_thread_resolution"),
])
def test_invalid_resolution_blocks_even_when_terms_overlap(change, error):
    previous, _, script = contract()
    script["thread_transitions"][0].update(change)
    assert error in validate_thread_transitions(script, previous)


def test_honest_progress_is_not_forced_to_resolve():
    previous, _, script = contract()
    script["thread_transitions"][0]["status"] = "PROGRESSED"
    script["resolved_threads"] = []
    assert validate_thread_transitions(script, previous) == []


def test_acknowledgement_does_not_award_resolution_points():
    previous = {"next_hook": "문은 열리지 않았다", "unresolved_threads": ["문은 열리지 않았다"]}
    score = score_story_continuity({"panels": [{"idx": 1, "narration": "문은 열리지 않았다"}]}, {"previous_episode": previous})
    assert score.thread_resolution_score == 0
    assert score.thread_acknowledgement_score == 30


def test_revision_guard_archives_verified_original_without_resetting_scope(tmp_path, monkeypatch):
    import hashlib

    from engine.image.generation_guard import ProductionGenerationGuard

    monkeypatch.setenv("ICG_GENERATION_REVISION", "2")
    image = tmp_path / "P1.png"
    image.write_bytes(b"verified old image")
    digest = hashlib.sha256(image.read_bytes()).hexdigest()
    guard = ProductionGenerationGuard(scope="output/episodes/2026-10-02/panels", panel=1, prompt="changed", refs=[])
    calls = []

    def rpc(name, params):
        calls.append((name, params))
        return {"prior_hashes": [digest]}

    monkeypatch.setattr(guard, "_rpc", rpc)
    assert guard.reuse(image) is False
    assert not image.exists()
    assert (tmp_path / "previous-revisions" / f"P1-{digest}.png").read_bytes() == b"verified old image"
    assert calls[0][0] == "image_generation_inspect_v2"
    assert calls[0][1]["p_scope"] == "output/episodes/2026-10-02/panels"
    assert calls[0][1]["p_revision"] == 2


def test_revision_guard_never_replaces_unreceipted_image(tmp_path, monkeypatch):
    from engine.image.generation_guard import GenerationHold, ProductionGenerationGuard

    monkeypatch.setenv("ICG_GENERATION_REVISION", "2")
    image = tmp_path / "P1.png"
    image.write_bytes(b"unknown")
    guard = ProductionGenerationGuard(scope="output/episodes/2026-10-02/panels", panel=1, prompt="changed", refs=[])
    monkeypatch.setattr(guard, "_rpc", lambda *_: {"prior_hashes": []})
    with pytest.raises(GenerationHold, match="Unreceipted"):
        guard.reuse(image)
    assert image.read_bytes() == b"unknown"


def test_restore_artifact_never_restores_previous_script(tmp_path):
    from scripts.restore_generation_artifact import restore

    source, target = tmp_path / "source", tmp_path / "target"
    panels = source / "episodes/2026-10-02/panels"
    panels.mkdir(parents=True)
    (panels / "P1.png").write_bytes(b"original")
    (panels.parent / "old-script.json").write_text("old narrative")
    assert restore("2026-10-02", source, target) == 1
    assert (target / "2026-10-02/panels/P1.png").read_bytes() == b"original"
    assert not (target / "2026-10-02/old-script.json").exists()


def test_latest_open_state_is_not_overwritten_by_older_closed_state():
    current = normalize_thread("미스터리")
    old = dict(current, status="PAID")
    merged = merge_thread_ledger([{"structured_threads": [current]}, {"structured_threads": [old]}])
    assert merged[0]["status"] == "OPEN"


@pytest.mark.parametrize("outcome", ["OBSERVATION", "PEACEFUL_GROWTH"])
def test_noncombat_preserves_zero_and_does_not_award_victory(outcome):
    state = {"arc_tension": 0, "hero_momentum": 0, "hero_win_streak": 5,
             "last_episode_date": "2026-10-01", "arc_day": 63}
    result = update_after_episode(state, outcome, "INTEL", {"vix": 16}, episode_date="2026-10-02")
    assert result["arc_tension"] == 0
    assert result["hero_momentum"] == 0
    assert result["hero_win_streak"] == 5
    assert result["last_episode_date"] == "2026-10-02"
    assert update_after_episode(result, outcome, "INTEL", {}, episode_date="2026-10-02")["arc_day"] == 64
    assert state["arc_day"] == 63


def test_candidate_is_pure_and_uses_real_vix():
    ctx = {"_arc_state": {"arc_day": 63, "arc_tension": 0},
           "_story_state": {"arc_episode": 10}, "_snapshot_row": {"vix": 36},
           "battle_result": {"outcome": "OBSERVATION"}}
    before = copy.deepcopy(ctx)
    candidate = build_state_candidate("2026-10-02", ctx, {})
    assert candidate["story_after"]["world_state"]["volatility_fields_active"] is True
    assert candidate["arc_after"]["last_episode_date"] == "2026-10-02"
    assert ctx == before


def test_manifest_rejects_changed_dialogue_and_changed_slide(tmp_path):
    slide = tmp_path / "S1.png"
    slide.write_bytes(b"original bytes")
    script = {"panels": [{"narration": "대본"}], "_generation_revision": 2}
    script["_assembly_manifest"] = build_manifest(script, [slide])
    validate_manifest(script, [slide])
    script["panels"][0]["narration"] = "변경된 대본"
    with pytest.raises(ValueError, match="manifest"):
        validate_manifest(script, [slide])
    script["panels"][0]["narration"] = "대본"
    slide.write_bytes(b"swapped artifact")
    with pytest.raises(ValueError, match="manifest"):
        validate_manifest(script, [slide])


def test_missing_database_adapter_blocks_before_send(monkeypatch):
    from engine.publish import state_commit
    from engine.quality.contracts import QualityHold

    monkeypatch.setattr(state_commit, "_rpc", lambda *_: {"ready": False})
    with pytest.raises(QualityHold):
        state_commit.require_state_ready("2026-10-02", 1, {})
