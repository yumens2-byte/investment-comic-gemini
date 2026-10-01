"""A deferred story thread must move to a future episode deadline."""

import runpy
from datetime import timedelta
from pathlib import Path

import pytest

from engine.quality.contracts import EditorialPlan, QualityHold, ThreadPayoff
from engine.quality.pipeline import prepare

_helpers = runpy.run_path(str(Path(__file__).with_name("test_webtoon_quality.py")))


@pytest.mark.parametrize("offset", [-365, -1, 0, 1])
def test_thread_deferral_requires_a_future_trading_date(tmp_path, offset):
    fixture = _helpers["fixture"].__wrapped__(tmp_path)
    plan = fixture["plan"].model_dump()
    plan["due_threads"] = ("pending-conflict",)
    plan["payoffs"] = (
        ThreadPayoff(
            thread_id="pending-conflict",
            deferred_reason="Resolution will occur in a later episode",
            new_due_date=fixture["bundle"].resolved_trading_date + timedelta(days=offset),
        ).model_dump(),
    )
    fixture["plan"] = EditorialPlan.model_validate(plan)
    if offset <= 0:
        with pytest.raises(QualityHold, match="deadline must follow"):
            prepare(**fixture)
    else:
        assert prepare(**fixture)["status"] == "awaiting_images_and_human_review"
