from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from sidestory.market_talk import automation as auto
from sidestory.market_talk.content import digest
from sidestory.market_talk.diagnostics import PhaseFailure
from sidestory.market_talk.generation import Review, review
from sidestory.market_talk.policy import FIELDS, UNITS
from sidestory.tests.market_talk.test_content_and_delivery import NOW, Store, sample


class AutoStore(Store):
    def __init__(self):
        super().__init__()
        self.row = None
        self.options = dict(
            enabled=True,
            exclusive_managed=False,
            coexistence_allowed=True,
            daily_budget_usd=1,
            monthly_budget_usd=10,
        )

    def policy(self, page):
        return self.options

    def daily_auto_item(self, *args):
        return self.row

    def put(self, page, draft):
        self.draft = draft
        self.row = dict(
            status="DRAFT",
            revision=draft.revision,
            body=draft.body,
            payload=draft.model_dump(mode="json"),
        )
        self.writes.append("put")

    def item(self, revision):
        return dict(super().item(revision), status=self.row["status"])

    def approve(self, revision, actor, note):
        self.row["status"] = "APPROVED"
        self.writes.append(("approve", actor, note))
        return {"status": "APPROVED"}

    def rpc(self, name, **kwargs):
        assert name == "talk_hold"
        self.row["status"] = "CONTENT_HOLD"
        self.writes.append("hold")


def accepted():
    return Review(
        evidence_supported=True,
        canon_consistent=True,
        no_invented_events=True,
        no_trading_advice=True,
        readable_korean=True,
    )


def execute(store, monkeypatch, verdict=None, changed=False):
    draft = sample()
    monkeypatch.setattr(auto, "prepare_context", lambda *a: (draft.context, draft.due_at))
    monkeypatch.setattr(auto, "generate", lambda *a, **kw: draft.text)
    monkeypatch.setattr(auto, "review", lambda *a, **kw: verdict or accepted())
    return auto.automatic_draft(
        None,
        store,
        "123",
        canon_path=Path("unused"),
        allowed={"CHAR_HERO_001"},
        now=NOW,
        source_commit="a" * 40,
        model="fixture",
        input_rate=1,
        output_rate=2,
        current=lambda *a: ("b" * 64, ("c" if changed else "a") * 64),
    )


def test_automatic_prepare_review_approve_without_human(monkeypatch):
    store = AutoStore()
    assert execute(store, monkeypatch)["status"] == "AUTO_APPROVED"
    approval = store.writes[-1]
    assert approval[0:2] == ("approve", auto.ACTOR)
    assert "사람 검수 아님" in approval[2]
    store.row["status"] = "PUBLISHED"
    assert execute(store, monkeypatch)["status"] == "ALREADY_PUBLISHED"
    assert len(store.writes) == 2


def test_model_reject_holds_and_never_approves(monkeypatch):
    store = AutoStore()
    verdict = accepted().model_copy(update={"canon_consistent": False})
    assert execute(store, monkeypatch, verdict)["status"] == "SKIPPED_MODEL_REVIEW"
    assert store.writes == ["put", "hold"]
    assert execute(store, monkeypatch)["status"] == "SKIPPED_CONTENT_HOLD"


def test_changed_snapshot_never_approves(monkeypatch):
    store = AutoStore()
    report = execute(store, monkeypatch, changed=True)
    assert report["status"] == "SKIPPED_QUALITY"
    assert "snapshot_changed" in report["errors"] and store.writes == []


@pytest.mark.parametrize(
    "option,value,code",
    [
        ("enabled", False, "PAGE_POLICY_DISABLED"),
        ("daily_budget_usd", 0, "GENERATION_BUDGET_REQUIRED"),
        ("monthly_budget_usd", 0, "GENERATION_BUDGET_REQUIRED"),
    ],
)
def test_configuration_blocks_before_model(monkeypatch, option, value, code):
    store = AutoStore()
    store.options[option] = value

    def forbidden(*args, **kwargs):
        pytest.fail("blocked configuration must not call a model")

    monkeypatch.setattr(auto, "generate", forbidden)
    report = auto.automatic_draft(
        None,
        store,
        "123",
        canon_path=Path("unused"),
        allowed=set(),
        now=NOW,
        source_commit="a" * 40,
        model="fixture",
        input_rate=1,
        output_rate=2,
        current=None,
    )
    assert report["blockers"] == [code]


class Query:
    def __init__(self, row):
        self.row = row

    def __getattr__(self, name):
        if name == "execute":
            return lambda: SimpleNamespace(data=[self.row])
        return lambda *a, **kw: self


def snapshot():
    return dict(
        snapshot_date="2026-10-06",
        created_at=NOW.isoformat(),
        data_quality=dict(
            status="complete",
            fallbacks=[],
            missing_after=[],
            blocked_fields=[],
            source_status={
                field: dict(
                    status="ok",
                    provider="test-fixture",
                    unit=UNITS[field],
                    observed_at=NOW.isoformat(),
                    market_session_date="2026-10-05",
                )
                for field in FIELDS
            },
        ),
        vix=15.5,
        us10y=4.4,
        oil_wti=80,
        spy_change=0.5,
        nasdaq_change=0.6,
        fear_greed=50,
    )


def test_preparation_is_stable_and_grounded():
    row = snapshot()
    path = Path(__file__).resolve().parents[3] / "config/characters.yaml"
    args = (Query(row), path, {"CHAR_HERO_001"})
    context, due = auto.prepare_context(*args, NOW, "a" * 40)
    repeat, _ = auto.prepare_context(*args, NOW + timedelta(minutes=1), "a" * 40)
    assert context.snapshot_hash == repeat.snapshot_hash == digest(row)
    assert context.evidence[0].observed_at == NOW
    assert context.provenance_reviewer == auto.ACTOR
    assert "원본 실시간 시세 재검증 아님" in context.evidence[0].market_session
    assert due.hour == 18 and due.minute == 30


@pytest.mark.parametrize(
    "field,value",
    [
        ("vix", float("nan")),
        ("fear_greed", 101),
        ("spy_change", None),
        ("snapshot_date", "2026-09-01"),
    ],
)
def test_bad_snapshot_rejected(field, value):
    row = snapshot()
    row[field] = value
    with pytest.raises(ValueError):
        auto.prepare_context(Query(row), Path("unused"), {"CHAR_HERO_001"}, NOW, "a" * 40)


def test_review_strict_schema_and_once_only_reservation():
    store = AutoStore()
    calls = []
    messages = SimpleNamespace(
        count_tokens=lambda **kw: SimpleNamespace(input_tokens=100),
        create=lambda **kw: (
            calls.append(kw)
            or SimpleNamespace(
                stop_reason="end_turn",
                content=[SimpleNamespace(type="text", text=accepted().model_dump_json())],
            )
        ),
    )
    client = SimpleNamespace(messages=messages)
    assert review(
        sample(), store, "123", model="fixture", input_rate=1, output_rate=2, client=client
    ).accepted
    with pytest.raises(PhaseFailure, match="reservation"):
        review(sample(), store, "123", model="fixture", input_rate=1, output_rate=2, client=client)
    assert len(calls) == 1
    with pytest.raises(ValueError):
        Review.model_validate(dict(accepted().model_dump(), evidence_supported="true"))
