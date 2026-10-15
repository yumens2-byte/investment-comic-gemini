"""Safety properties for Actions planning and resumable execution (no external providers)."""
from copy import deepcopy
from datetime import date
from types import SimpleNamespace

import pytest
import yaml

from sidestory.market_talk.executor import execute
from sidestory.market_talk.recovery import audit_day, plan, retryable
from sidestory.market_talk.policy import timestamp
from sidestory.market_talk.scheduling import saved_slot
from sidestory.tests.conftest import REPO_ROOT

DAY = date(2026, 10, 16)
REV = "a" * 64


def snapshot():
    return {
        "slot_date": DAY.isoformat(), "db_now": "2026-10-16T19:00:00+09:00",
        "policy": {"enabled": True, "policy_version": 5, "effective_from": "2026-10-16"},
        "slot": {"slot_date": DAY.isoformat(), "policy_version": 5,
                 "due_at": "2026-10-16T14:00:00+09:00",
                 "normal_end": "2026-10-16T18:00:00+09:00",
                 "window_end": "2026-10-16T23:30:00+09:00"},
        "unresolved": 0, "deliveries": [], "drafts": [], "models": [],
        "cost_count": 0, "recovery": {},
    }


@pytest.mark.parametrize("patch,expected", [
    ({"unresolved": 1}, "RECONCILE_REQUIRED"),
    ({"db_now": "2026-10-16T23:30:00+09:00"}, "MISSED_FINAL"),
    ({"db_now": "2026-10-17T00:00:00+09:00"}, "OUTSIDE_RECOVERY_DAY"),
    ({"db_now": "2026-10-16T13:59:59+09:00"}, "WAITING_SLOT"),
    ({"recovery": {"execution_count": 3}}, "RETRY_EXHAUSTED"),
    ({"recovery": {"last_status": "HOLD"}}, "HOLD"),
    ({"recovery": {"next_retry_at": "2026-10-16T19:01:00+09:00"}}, "RETRY_WAIT"),
    ({"recovery": {"lease_expires_at": "2026-10-16T19:01:00+09:00"}}, "IN_PROGRESS"),
    ({"models": [{"phase": "generation", "state": "UNKNOWN"}]}, "MODEL_HOLD"),
    ({"models": [{"phase": "generation", "state": "RESERVED"}]}, "MODEL_HOLD"),
    ({"models": [{"phase": "generation", "state": "FAILED"}]}, "MODEL_HOLD"),
    ({"models": [{"phase": "generation", "state": "COMPLETE"}]}, "RESULT_PERSISTENCE_HOLD"),
    ({"cost_count": 1}, "RESULT_PERSISTENCE_HOLD"),
    ({"drafts": [{"revision": REV, "status": "CONTENT_HOLD"}]}, "CONTENT_HOLD"),
    ({"drafts": [{"revision": REV, "status": "DRAFT"}],
      "models": [{"phase": "review", "state": "COMPLETE"}]}, "RESULT_PERSISTENCE_HOLD"),
    ({"drafts": [{"revision": REV, "status": "APPROVED"},
                {"revision": "b"*64, "status": "DRAFT"}]}, "MULTIPLE_DRAFTS"),
    ({"deliveries": [{"state": "REJECTED", "revision": REV}]}, "RECONCILE_REQUIRED"),
])
def test_unsafe_states_never_request_execution(patch, expected):
    value = snapshot()
    value.update(patch)
    result = plan(value)
    assert result["status"] == expected
    assert result["action"] == "none"


@pytest.mark.parametrize("state", ["DRAFT", "APPROVED"])
def test_saved_draft_selects_same_revision(state):
    value = snapshot()
    value["drafts"] = [{"revision": REV, "status": state}]
    result = plan(value)
    assert result["action"] == "recovery" and result["revision"] == REV


def test_normal_cutoff_does_not_block_recovery():
    assert plan(snapshot(), "normal")["status"] == "PENDING_RECOVERY"
    assert plan(snapshot())["action"] == "recovery"


def test_no_run_gets_first_attempt_but_never_before_13_or_after_cutoff():
    value = snapshot()
    value["slot"] = None
    assert plan(value)["status"] == "NO_RUN"
    for at in ["12:59:00", "23:30:00"]:
        value["db_now"] = f"2026-10-16T{at}+09:00"
        assert plan(value)["action"] == "none"


@pytest.mark.parametrize("verified,action", [(True, "none"), (False, "verify")])
def test_published_only_verifies_even_after_expiry_or_pause(verified, action):
    value = snapshot()
    value["policy"]["enabled"] = False
    value["db_now"] = "2026-10-17T01:00:00+09:00"
    value["deliveries"] = [{"state": "PUBLISHED", "revision": REV,
                            "post_id": "123_1", "verified": verified}]
    result = plan(value)
    assert result["action"] == action
    assert result["revision"] == REV


def test_verification_is_bounded_and_has_cooldown():
    value = snapshot()
    value["deliveries"] = [{"state": "PUBLISHED", "revision": REV,
                            "post_id": "123_1", "verified": False}]
    value["recovery"] = {"verification_retry_count": 3}
    assert plan(value)["status"] == "VERIFY_EXHAUSTED"
    value["recovery"] = {"next_retry_at": "2026-10-16T19:01:00+09:00"}
    assert plan(value)["status"] == "RETRY_WAIT"


def test_weekend_and_monday_audit_never_repost():
    assert audit_day(timestamp("2026-10-19T09:17:00+09:00")) == DAY
    assert plan(snapshot(), "audit")["status"] == "MISSED_FINAL"
    value = snapshot()
    value["slot_date"] = "2026-10-17"
    value["db_now"] = "2026-10-17T15:00:00+09:00"
    assert plan(value)["action"] == "none"


def test_v5_deadlines_are_validated_and_legacy_not_extended():
    assert saved_slot(snapshot()["slot"]).end.hour == 23
    value = deepcopy(snapshot()["slot"])
    value["policy_version"] = 4
    with pytest.raises(ValueError):
        saved_slot(value)
    value["policy_version"] = 5
    value["normal_end"] = "2026-10-16T20:00:00+09:00"
    with pytest.raises(ValueError):
        saved_slot(value)


@pytest.mark.parametrize("phase,unknown,expected", [
    ("page_identity", False, True), ("source", False, True),
    ("generation", False, False), ("review", True, False),
    ("delivery", False, False),
])
def test_retry_allowlist_never_replays_paid_or_post(phase, unknown, expected):
    assert retryable({"phase": phase, "outcome_unknown": unknown,
                      "blockers": ["PROVIDER_TIMEOUT"]}) is expected


def fake_store(value, calls):
    target = snapshot()["slot"]
    def claim(*args):
        calls.append("claim")
        return {"status": "CLAIMED", "db_now": value["db_now"]}
    return SimpleNamespace(
        mode="recovery", snapshot=lambda *a: value,
        ensure_schedule=lambda *a: target, claim=claim,
        record_outcome=lambda *a: calls.append("record"),
        complete=lambda *a, **k: calls.append("complete"),
    )


def test_unknown_execution_makes_zero_callbacks():
    value = snapshot()
    value["unresolved"] = 1
    calls = []
    forbidden = lambda *a: pytest.fail("external operation forbidden")
    report = execute(None, fake_store(value, calls), "123", day=DAY, mode="recovery",
                     run="1", automatic=forbidden, publish_one=forbidden, verify_one=forbidden)
    assert report["status"] == "RECONCILE_REQUIRED" and calls == []


def test_approved_resume_publishes_once_and_records():
    value, calls = snapshot(), []
    value["drafts"] = [{"revision": REV, "status": "APPROVED"}]
    def publish(revision):
        calls.append(("publish", revision))
        return {"status": "PUBLISHED", "verified": True, "revision": revision}
    report = execute(None, fake_store(value, calls), "123", day=DAY, mode="recovery",
                     run="1", automatic=lambda at: {"status": "AUTO_APPROVED", "revision": REV},
                     publish_one=publish, verify_one=lambda *a: pytest.fail("wrong path"))
    assert report["verified"] and calls.count(("publish", REV)) == 1
    assert calls[-2:] == ["record", "complete"]


def test_published_unverified_uses_only_exact_id_verification():
    value, calls = snapshot(), []
    value["deliveries"] = [{"state": "PUBLISHED", "revision": REV,
                            "post_id": "123_1", "verified": False}]
    forbidden = lambda *a: pytest.fail("generation/POST forbidden")
    report = execute(None, fake_store(value, calls), "123", day=DAY, mode="verify",
                     run="1", automatic=forbidden, publish_one=forbidden,
                     verify_one=lambda r: {"status": "PUBLISHED", "verified": True, "revision": r})
    assert report["verified"] and calls == ["claim", "record", "complete"]


def test_workflows_have_no_external_dispatch_or_watch_skip_gate():
    root = REPO_ROOT / ".github/workflows"
    primary = yaml.safe_load((root / "sidestory_market_talk.yml").read_text())
    worker = yaml.safe_load((root / "sidestory_market_talk_execute.yml").read_text())
    watchdog_text = (root / "sidestory_market_talk_watchdog.yml").read_text()
    watchdog = yaml.safe_load(watchdog_text)
    assert "scheduler" not in primary[True]["workflow_dispatch"]["inputs"]
    assert "steps" not in primary["jobs"]["market-talk"]
    assert "workflow_call" in worker[True]
    assert "concurrency" not in worker
    assert primary["concurrency"] == watchdog["concurrency"]
    assert "MARKET_TALK_WATCH_ENABLED" not in watchdog_text
    assert "FACE_PAGE_TOKEN" not in watchdog["jobs"]["plan"]["env"]
    assert "ANTHROPIC_API_KEY" not in watchdog["jobs"]["plan"]["env"]
    assert watchdog[True]["workflow_run"]["types"] == ["completed"]
    assert watchdog[True]["workflow_run"]["workflows"] == [primary["name"]]
    for name in ["sidestory_market_talk.yml", "sidestory_market_talk_execute.yml",
                 "sidestory_market_talk_watchdog.yml"]:
        text = (root / name).read_text()
        assert "/dispatches" not in text and "github_icg_dispatch_pat" not in text
