from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from sidestory.market_talk.monitoring import completed_day, watch
from sidestory.market_talk.policy import KST, PolicyError, source_hash
from sidestory.market_talk.scheduling import candidate_slot, ensure_slot, slot_status

NOW = datetime(2026, 10, 12, 13, tzinfo=KST)


def row(target):
    return dict(
        slot_date=target.day.isoformat(),
        due_at=target.due.isoformat(),
        window_end=target.end.isoformat(),
    )


@pytest.mark.parametrize("minute,expected", [(0, "13:00"), (270, "17:30")])
def test_random_endpoints(minute, expected):
    def choose(n):
        assert n == 271
        return minute

    target = candidate_slot(NOW, randbelow=choose)
    assert target.due.strftime("%H:%M") == expected
    assert target.end.strftime("%H:%M") == "18:00"
    assert slot_status(target, target.due - timedelta(seconds=1)) == "WAITING_SLOT"
    assert slot_status(target, target.due) == "READY"
    assert slot_status(target, target.end) == "MISSED_WINDOW"


def test_retry_uses_saved_winner_not_new_random_candidate():
    winner = candidate_slot(NOW, randbelow=lambda n: 120)
    store = SimpleNamespace(ensure_schedule=lambda *args: row(winner))
    assert ensure_slot(store, "123", NOW) == winner
    assert ensure_slot(store, "123", NOW + timedelta(hours=3)) == winner


@pytest.mark.parametrize(
    "now,requested,code",
    [
        (NOW.replace(tzinfo=None), "", "AWARE_CLOCK_REQUIRED"),
        (NOW, "2026-10-13", "SLOT_DATE_MISMATCH"),
        (NOW - timedelta(days=1), "", "SKIPPED_WEEKEND"),
    ],
)
def test_invalid_schedule(now, requested, code):
    with pytest.raises(PolicyError, match=code):
        candidate_slot(now, requested)


def test_watcher_day_boundary_and_missing_slot():
    assert completed_day(NOW).isoformat() == "2026-10-09"
    end = NOW.replace(hour=18)
    assert completed_day(end).isoformat() == "2026-10-12"
    assert completed_day(end + timedelta(days=5)).isoformat() == "2026-10-16"
    store = SimpleNamespace(get_slot=lambda *args: None)
    assert watch(store, "123", end)["blockers"] == ["NO_RUN"]
    assert watch(store, "123", NOW, "2026-10-12")["status"] == "WATCH_PENDING"


def test_watcher_honors_saved_deadline_and_verified_delivery():
    target = candidate_slot(NOW, randbelow=lambda n: 10)
    store = SimpleNamespace(
        get_slot=lambda *a: row(target),
        day_deliveries=lambda *a: [dict(state="PUBLISHED", business_key="r")],
        slot_outcomes=lambda *a: [
            dict(status="PUBLISHED", reason_code="PUBLISHED_VERIFIED", revision="r")
        ],
    )
    assert watch(store, "123", NOW, "2026-10-12")["status"] == "WATCH_PENDING"
    assert watch(store, "123", target.end)["status"] == "WATCH_OK"
    assert watch(store, "123", target.end, "2026-10-11")["status"] == "SKIPPED_WEEKEND"


def test_v4_hash_includes_source_provenance():
    a, b = (
        {"vix": 20, "data_quality": {"provider": "a"}},
        {"vix": 20, "data_quality": {"provider": "b"}},
    )
    assert source_hash(a, "market-talk-4") != source_hash(b, "market-talk-4")
    assert source_hash(a, "market-talk-2") == source_hash(b, "market-talk-2")


@pytest.mark.parametrize("status", ["WAITING_SLOT", "MISSED_WINDOW", "ALREADY_PUBLISHED"])
def test_preflight_blocks_before_paid_or_source_access(status):
    from sidestory.market_talk.automation import automatic_draft

    target = candidate_slot(NOW, randbelow=lambda n: 0)
    store = SimpleNamespace(
        ensure_schedule=lambda *a: row(target), preflight=lambda *a: {"status": status}
    )
    report = automatic_draft(
        None,
        store,
        "123",
        canon_path=None,
        allowed=set(),
        now=NOW,
        source_commit="",
        model="",
        input_rate=0,
        output_rate=0,
        current=None,
        scheduled=True,
    )
    assert report["status"] == status
    assert report["paid_call_count"] == 0


@pytest.mark.parametrize("due,end", [("12:59", "18:00"), ("17:31", "18:00"), ("15:00", "23:59")])
def test_v4_saved_schedule_rejects_invalid_policy_window(due, end):
    from sidestory.market_talk.scheduling import saved_slot

    record = dict(
        slot_date="2026-10-12",
        due_at=f"2026-10-12T{due}:00+09:00",
        window_end=f"2026-10-12T{end}:00+09:00",
        policy_version=4,
    )
    with pytest.raises(PolicyError, match="SLOT_INVALID"):
        saved_slot(record)


def test_saved_slot_accepts_database_integer_v4_contract():
    from sidestory.market_talk.scheduling import saved_slot

    target = candidate_slot(NOW, randbelow=lambda n: 270)
    record = dict(row(target), policy_version=4, schedule_origin="random_afternoon")
    assert saved_slot(record) == target


@pytest.mark.parametrize(
    "patch",
    [
        {"due_at": "2026-10-12T13:00:01+09:00"},
        {"due_at": "2026-10-12T13:00:00.000001+09:00"},
        {"due_at": "2026-10-12T13:00:00"},
        {"due_at": "2026-10-13T13:00:00+09:00"},
        {"window_end": "2026-10-12T18:00:01+09:00"},
        {
            "slot_date": "2026-10-11",
            "due_at": "2026-10-11T13:00:00+09:00",
            "window_end": "2026-10-11T18:00:00+09:00",
        },
    ],
)
def test_database_integer_v4_malformed_schedule_rejected(patch):
    from sidestory.market_talk.scheduling import saved_slot

    target = candidate_slot(NOW, randbelow=lambda n: 0)
    record = dict(row(target), policy_version=4)
    record.update(patch)
    with pytest.raises(PolicyError, match="SLOT_INVALID"):
        saved_slot(record)
