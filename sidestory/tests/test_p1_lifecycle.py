from __future__ import annotations

import pytest

from sidestory.core import lifecycle


def test_transitions() -> None:
    lifecycle.check_transition("narrative", "draft")
    lifecycle.check_transition("image", "narrative_done")
    lifecycle.check_transition("assembly", "image_done")
    for stage, bad in (("narrative", "narrative_done"), ("image", "draft"),
                       ("assembly", "hold"), ("image", "published")):
        with pytest.raises(lifecycle.TransitionError):
            lifecycle.check_transition(stage, bad)


def test_resume_and_remaining() -> None:
    assert lifecycle.resume_status({}) == "draft"
    assert lifecycle.resume_status({"script_json": {"a": 1}}) == "narrative_done"
    assert lifecycle.resume_status({"script_json": {}, "panels_json": {"p": 1}}) == "image_done"
    assert lifecycle.resume_status({"slides_json": [1], "manifest_json": {"a": 1},
                                    "panels_json": {"p": 1}}) == "assembled"
    assert lifecycle.remaining_stages("draft") == ["narrative", "image", "assembly"]
    assert lifecycle.remaining_stages("image_done") == ["assembly"]
    assert lifecycle.remaining_stages("assembled") == []
    with pytest.raises(lifecycle.TransitionError):
        lifecycle.remaining_stages("published")
