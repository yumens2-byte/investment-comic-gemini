"""Launch invariants: no paid catch-up, fabricated sources or blind repost."""

from copy import deepcopy
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from postgrest.exceptions import APIError

from sidestory.market_talk import __main__ as cli
from sidestory.market_talk.automation import automatic_draft
from sidestory.market_talk.content import digest
from sidestory.market_talk.diagnostics import PhaseFailure, failure_report, phase_call
from sidestory.market_talk.monitoring import completed_day, watch
from sidestory.market_talk.policy import (
    KST,
    LEGACY_FIELDS,
    PolicyError,
    scheduled_slot,
    slot,
    source_hash,
    validate_source,
)
from sidestory.market_talk.publishing import ControlledPublisher
from sidestory.market_talk.reporting import summary
from sidestory.market_talk.service import publish, verify_publication
from sidestory.tests.market_talk.test_automation import snapshot
from sidestory.tests.market_talk.test_content_and_delivery import NOW, Provider, Store, sample


@pytest.mark.parametrize(
    "clock,day,status",
    [
        ("2026-10-09T01:41:00+09:00", "2026-10-08", "SKIPPED_OUTSIDE_WINDOW"),
        ("2026-10-09T18:29:59+09:00", "2026-10-08", "SKIPPED_OUTSIDE_WINDOW"),
        ("2026-10-09T18:30:00+09:00", "2026-10-09", "READY"),
        ("2026-10-09T23:58:59+09:00", "2026-10-09", "READY"),
        ("2026-10-09T23:59:00+09:00", "2026-10-09", "SKIPPED_OUTSIDE_WINDOW"),
        ("2026-10-12T01:00:00+09:00", "2026-10-09", "SKIPPED_OUTSIDE_WINDOW"),
        ("2026-10-10T18:30:00+09:00", "2026-10-10", "SKIPPED_WEEKEND"),
    ],
)
def test_scheduled_slot_boundaries(clock, day, status):
    now = datetime.fromisoformat(clock)
    target = scheduled_slot(now)
    assert target.day.isoformat() == day and target.status(now) == status
    store = SimpleNamespace()  # Any policy/model/DB call would fail.
    if status != "READY":
        report = automatic_draft(
            None,
            store,
            "123",
            canon_path=None,
            allowed=set(),
            now=now,
            source_commit="",
            model="",
            input_rate=0,
            output_rate=0,
            current=None,
            scheduled=True,
        )
        assert report["status"] == status and report["slot_date"] == day


def test_explicit_old_slot_and_naive_clock_rejected():
    assert scheduled_slot(NOW, "2026-10-05").status(NOW) == "SKIPPED_OUTSIDE_WINDOW"
    with pytest.raises(PolicyError, match="AWARE_CLOCK_REQUIRED"):
        slot(NOW.replace(tzinfo=None))


@pytest.mark.parametrize(
    "change,code",
    [
        (lambda s: s.update(oil_wti=-99999), "SOURCE_VALUE_OUT_OF_RANGE"),
        (
            lambda s: s.update(created_at=NOW.replace(tzinfo=None).isoformat()),
            "SOURCE_TIMESTAMP_REQUIRED",
        ),
        (lambda s: s["data_quality"].update(status="partial"), "SOURCE_QUALITY_REQUIRED"),
        (lambda s: s["data_quality"].update(fallbacks=["vix"]), "SOURCE_QUALITY_BLOCKED"),
        (lambda s: s["data_quality"].update(source_status={}), "SOURCE_SESSION_REQUIRED"),
        (
            lambda s: s["data_quality"]["source_status"]["vix"].update(unit="percent"),
            "SOURCE_UNIT_MISMATCH",
        ),
        (
            lambda s: s["data_quality"]["source_status"]["vix"].update(provider=" "),
            "SOURCE_PROVIDER_REQUIRED",
        ),
        (
            lambda s: s["data_quality"]["source_status"]["vix"].update(
                observed_at=(NOW + timedelta(hours=1)).isoformat()
            ),
            "SOURCE_OBSERVATION_STALE",
        ),
        (
            lambda s: s["data_quality"]["source_status"]["vix"].update(
                market_session_date="2026-10-04"
            ),
            "SOURCE_SESSION_MISMATCH",
        ),
    ],
)
def test_source_fail_closed(change, code):
    value = deepcopy(snapshot())
    change(value)
    with pytest.raises(PolicyError, match=code):
        validate_source(value, NOW)


def test_source_metadata_hash_and_legacy_immutability():
    value = snapshot()
    legacy = digest({k: value[k] for k in LEGACY_FIELDS if k in value})
    assert source_hash(value, "market-talk-2") == legacy
    old = source_hash(value, "market-talk-3")
    value["data_quality"]["source_status"]["vix"]["provider"] = "other-fixture"
    assert source_hash(value, "market-talk-3") != old
    assert source_hash(value, "market-talk-2") == legacy
    value["oil_wti"] = -20  # Negative oil is possible, not automatically malformed.
    assert validate_source(value, NOW) is value


@pytest.mark.parametrize(
    "db_code,code",
    [
        ("42501", "DB_PERMISSION_DENIED"),
        ("PGRST202", "DB_MIGRATION_REQUIRED"),
        ("23505", "DB_DUPLICATE_RESERVATION_OR_KEY"),
    ],
)
def test_safe_database_diagnostics(db_code, code):
    error = APIError(
        dict(code=db_code, message="secret-token", details="https://private", hint="raw text")
    )
    with pytest.raises(PhaseFailure) as exc:
        phase_call("review_reservation", lambda: (_ for _ in ()).throw(error))
    report = failure_report(exc.value, "automation")
    assert report["phase"] == "review_reservation" and report["blockers"] == [code]
    assert "secret" not in str(report) and "private" not in str(report)


def test_posted_read_failure_then_read_only_verification_never_reposts():
    store, provider, draft = Store(), Provider(), sample()
    provider.get_post = lambda _: (_ for _ in ()).throw(TimeoutError("secret"))
    publisher = ControlledPublisher(provider, store, "123", draft.revision, "talk")
    report = publish(
        draft.revision, store, publisher, now=NOW, canon_hash="b" * 64, snapshot_hash="a" * 64
    )
    assert report["status"] == "POSTED_UNVERIFIED" and store.state == "PUBLISHED"
    # Read-only recovery is permitted after draft expiry; no create_post call.
    provider.get_post = lambda post: dict(
        id=post, message=draft.body, is_published=True, created_time=NOW.isoformat()
    )
    report = verify_publication(draft.revision, store, publisher, now=NOW + timedelta(days=1))
    assert report["verified"] and provider.calls == 1


@pytest.mark.parametrize(
    "deliveries,outcomes,expected",
    [
        ([], [], "MISSED_PUBLICATION_SLOT"),
        ([dict(state="UNKNOWN")], [], "UNRESOLVED_DELIVERY"),
        ([dict(state="PUBLISHED", business_key="rev")], [], "POSTED_UNVERIFIED"),
        (
            [dict(state="PUBLISHED", business_key="rev")],
            [dict(status="PUBLISHED", reason_code="PUBLISHED_VERIFIED", revision="other")],
            "POSTED_UNVERIFIED",
        ),
        (
            [dict(state="PUBLISHED", business_key="rev")],
            [dict(status="PUBLISHED", reason_code="PUBLISHED_VERIFIED", revision="rev")],
            None,
        ),
    ],
)
def test_watcher_is_read_only(deliveries, outcomes, expected):
    store = SimpleNamespace(day_deliveries=lambda *a: deliveries, slot_outcomes=lambda *a: outcomes)
    report = watch(store, "123", NOW + timedelta(days=1))
    assert report["status"] == ("WATCH_ALERT" if expected else "WATCH_OK")
    assert report["blockers"] == ([expected] if expected else []) and not report["allowed"]
    assert completed_day(datetime(2026, 10, 12, 0, 15, tzinfo=KST)).isoformat() == "2026-10-09"


def test_safe_summary_rejects_workflow_commands_and_model_text():
    rendered = summary(
        dict(
            status="BLOCKED\n::error::secret",
            phase="source",
            blockers=["SAFE_CODE", "<script>"],
            body="raw model",
        )
    )
    assert "source" in rendered and "SAFE_CODE" in rendered
    assert "secret" not in rendered and "raw model" not in rendered and "<script>" not in rendered


def test_scheduled_publish_stops_before_queue_or_provider(monkeypatch, capsys):
    monkeypatch.setenv("FACE_PAGE_ID", "123")
    monkeypatch.setattr(cli, "connection", lambda: None)
    store = Store()
    monkeypatch.setattr(cli, "TalkStore", lambda _: store)
    monkeypatch.setattr(cli, "utcnow", lambda: datetime(2026, 10, 9, 1, 41, tzinfo=KST))
    assert cli.main(["--stage", "publish", "--scheduled", "--live"]) == 0
    assert store.outcomes[0][1] == "2026-10-08" and store.writes == []
    assert "SKIPPED_OUTSIDE_WINDOW" in capsys.readouterr().out


def test_cli_dry_publish_does_not_record_outcomes(monkeypatch, tmp_path):
    import json

    store = Store()
    draft = sample()
    path = tmp_path / "draft.json"
    path.write_text(draft.model_dump_json())
    monkeypatch.setenv("FACE_PAGE_ID", "123")
    monkeypatch.setattr(cli, "connection", lambda: None)
    monkeypatch.setattr(cli, "TalkStore", lambda _: store)
    monkeypatch.setattr(cli, "utcnow", lambda: NOW)
    monkeypatch.setattr(cli, "current", lambda *a: ("b" * 64, "a" * 64))
    output = tmp_path / "report.json"
    assert (
        cli.main(
            [
                "--stage",
                "publish",
                "--revision",
                draft.revision,
                "--input",
                str(path),
                "--output",
                str(output),
            ]
        )
        == 0
    )
    assert json.loads(output.read_text())["status"] == "DRY_RUN"
    assert store.writes == [] and store.outcomes == []


def test_cli_verify_records_original_slot_without_post_or_model(monkeypatch):
    store, provider, draft = Store(), Provider(), sample()
    store.state = "PUBLISHED"
    provider.message = draft.body
    monkeypatch.setenv("FACE_PAGE_ID", "123")
    monkeypatch.setattr(cli, "connection", lambda: None)
    monkeypatch.setattr(cli, "TalkStore", lambda _: store)
    monkeypatch.setattr(cli, "utcnow", lambda: NOW + timedelta(days=1))
    monkeypatch.setattr(cli, "live_publisher", lambda _: provider)
    assert cli.main(["--stage", "verify", "--revision", draft.revision]) == 0
    assert store.outcomes[0][1] == "2026-10-06" and store.outcomes[0][-1]["verified"]
    assert provider.calls == 0 and store.cost == set() and store.writes == []


def test_prepare_payload_roundtrips_without_report_metadata(monkeypatch, tmp_path):
    import json

    from sidestory.market_talk.content import Context
    from sidestory.tests.market_talk.test_automation import Query

    data = sample().context.model_dump(mode="json")
    for key in ("snapshot_hash", "canon_version", "character_name", "character_voice"):
        data.pop(key)
    source = tmp_path / "source.json"
    output = tmp_path / "context.json"
    source.write_text(json.dumps(data))
    monkeypatch.setenv("FACE_PAGE_ID", "123")
    monkeypatch.setenv("MARKET_TALK_CHARACTER_IDS", "CHAR_HERO_001")
    monkeypatch.setattr(cli, "connection", lambda: Query(snapshot()))
    monkeypatch.setattr(cli, "utcnow", lambda: NOW)
    assert cli.main(["--stage", "prepare", "--input", str(source), "--output", str(output)]) == 0
    context = Context.model_validate_json(output.read_text())
    assert context.snapshot_hash == source_hash(snapshot(), "market-talk-1")
    assert "run_id" not in json.loads(output.read_text())
