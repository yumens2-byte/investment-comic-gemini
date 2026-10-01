from engine.narrative.continuity_score import score_story_continuity


def test_score_story_continuity_passes_with_hook_thread_and_relationship() -> None:
    script = {
        "resolved_threads": ["검은 문 안쪽 목소리 확인"],
        "panels": [
            {
                "idx": 1,
                "narration": "검은 문은 아직 닫히지 않았고 영웅은 경계 심화를 감춘다.",
                "key_text": "문이 다시 열린다",
            },
            {"idx": 2, "narration": "철문 안쪽의 목소리가 오늘 VIX와 겹친다."},
        ],
    }
    context = {
        "previous_episode": {
            "source_episode_id": "ICG-2026-06-14-001",
            "next_hook": "검은 문은 아직 닫히지 않았다",
            "unresolved_threads": ["철문 안쪽의 목소리"],
            "relationship_delta": {"hero:villain": "경계 심화"},
        }
    }
    plan = {"panel_beats": [{"panel_idx": 1, "must_reference_previous": True}]}

    score = score_story_continuity(script, context, plan)

    assert score.status == "pass"
    assert score.total_score >= 70


def test_score_story_continuity_fails_when_opening_ignores_previous() -> None:
    score = score_story_continuity(
        {"panels": [{"idx": 1, "narration": "완전히 새로운 전투가 시작된다."}]},
        {"previous_episode": {"next_hook": "검은 문은 아직 닫히지 않았다"}},
        None,
    )

    assert score.status == "fail"
    assert "opening_hook_payoff" in score.missing_requirements


def test_score_story_continuity_does_not_treat_hook_as_thread_resolution() -> None:
    """A hook keyword match must not silently resolve a different thread."""
    script = {
        "resolved_threads": [],
        "panels": [
            {
                "idx": 1,
                "narration": "검은 문은 아직 닫히지 않았고, 오늘의 VIX가 그 틈을 흔들었다.",
            },
            {"idx": 2, "narration": "영웅은 이전 압력이 오늘의 신호로 이어졌음을 확인한다."},
        ],
    }
    context = {
        "previous_episode": {
            "source_episode_id": "ICG-2026-06-25-001",
            "next_hook": "검은 문은 아직 닫히지 않았다",
            "unresolved_threads": ["철문 안쪽의 목소리"],
        }
    }
    plan = {"panel_beats": [{"panel_idx": 1, "must_reference_previous": True}]}

    score = score_story_continuity(script, context, plan)

    assert score.status != "pass"
    assert "unresolved_thread_resolution" in score.missing_requirements
    assert score.thread_resolution_score == 0.0


def test_score_does_not_award_relationship_points_when_no_relationship_exists() -> None:
    score = score_story_continuity(
        {"panels": [{"idx": 1, "narration": "검은 문은 아직 닫히지 않았다."}]},
        {"previous_episode": {"next_hook": "검은 문은 아직 닫히지 않았다"}},
    )

    assert score.relationship_reuse_score == 0.0
    assert score.total_score == 100.0
