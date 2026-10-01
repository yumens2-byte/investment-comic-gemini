"""Network-free regression tests for webtoon quality and pilot release contracts."""

from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from decimal import Decimal
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image
from pydantic import ValidationError

from engine.quality.canon import CanonEntry, CanonManifest, file_hash, repair_prompt, safe_asset
from engine.quality.contracts import (
    Claim,
    DramaticBeat,
    EditorialPlan,
    Evidence,
    EvidenceBundle,
    MetricScale,
    QualityHold,
    ThreadPayoff,
    digest,
    rank_evidence,
    validate_claims,
)
from engine.quality.ledger import PilotLedger, money_units
from engine.quality.pipeline import business_status, generate_bounded, prepare, publish_pilot
from engine.quality.release import (
    REQUIRED_CHECKS,
    ROLES,
    RUBRIC,
    QualityReport,
    ReviewItem,
    RoleReview,
    build_release,
)
from engine.quality.render import Rect, compose_quality_panel

NOW = datetime(2026, 9, 25, 22, tzinfo=timezone.utc)
LIMITS = dict(estimate="0.1", episode_cap="1", daily_cap="2", monthly_cap="3", max_calls=4)


@pytest.fixture
def fixture(tmp_path):
    ref = tmp_path / "ref.png"
    Image.new("RGB", (100, 100), "blue").save(ref)
    e = Evidence(
        evidence_id="e1",
        metric="spx",
        value="100",
        change="2",
        unit="points",
        semantic_type="index",
        instrument="SPX",
        price_basis="close",
        source="fixture",
        observed_at=NOW,
        trading_date=date(2026, 9, 25),
        confidence=1,
    )
    bundle = EvidenceBundle(
        requested_date=e.trading_date,
        resolved_trading_date=e.trading_date,
        calendar_policy="fixture",
        collected_at=NOW,
        synthetic=True,
        evidence=(e,),
    )
    canon = CanonManifest(
        registry_version="v1",
        approved_by="fixture-reviewer",
        entries=(
            CanonEntry(
                char_id="hero",
                form="form1",
                ref_path="ref.png",
                ref_sha256=file_hash(ref),
                required_props=("shield",),
                hand_rules=("left shield",),
                direction_rules=("right",),
                forbidden=("duplicate",),
                approval_id="test-only",
            ),
        ),
    )
    panels = [
        dict(
            idx=i,
            panel_type="STORY" if i < 8 else "DISCLAIMER",
            characters=[dict(char_id="hero", form="form1")],
            key_text="Hold the line",
        )
        for i in range(1, 9)
    ]
    claims = [
        Claim(
            claim_id=f"c{i}", panel_idx=i, field="key_text", text="Hold the line", kind="metaphor"
        )
        for i in range(1, 9)
    ]
    plan = EditorialPlan(
        thesis="Protect the city at a cost",
        top_evidence_ids=("e1",),
        beats=tuple(
            DramaticBeat(
                panel_idx=i,
                goal="protect",
                action="block",
                resistance="pressure",
                cost="cracked shield",
                visible_state_change="barrier held",
                causal_from_panel=i - 1 if i > 1 else None,
                evidence_ids=("e1",) if i == 1 else (),
                required_cast=("hero",),
            )
            for i in range(1, 8)
        ),
    )
    script = dict(panels=panels, fixed_outcome="PEACEFUL_GROWTH")
    return dict(
        bundle=bundle,
        plan=plan,
        claims=claims,
        canon=canon,
        script=script,
        calculation={"outcome": "PEACEFUL_GROWTH"},
        root=tmp_path,
    )


def reviewed_release(f):
    inputs = prepare(**f)["inputs"]
    parts = {"x": [{"text": "part one"}, {"text": "part two"}], "telegram": [{"text": "episode"}]}
    inputs["publication_parts"] = parts
    artifacts = {"ref.png": file_hash(f["root"] / "ref.png")}
    (f["root"] / "slides").mkdir(exist_ok=True)
    for i in range(1, 9):
        for suffix, size in (
            ("", (1080, 1350)),
            ("-preview-360", (360, 450)),
            ("-preview-390", (390, 488)),
        ):
            relative = f"slides/P{i}{suffix}.png"
            Image.new("RGB", size, "blue").save(f["root"] / relative)
            artifacts[relative] = file_hash(f["root"] / relative)
    content_hash = digest(
        dict(
            episode_id="ICG-2026-09-25-001",
            version=1,
            inputs={k: digest(v) for k, v in inputs.items()},
            artifacts=artifacts,
            channels=("x", "telegram"),
            synthetic=True,
        )
    )
    report = QualityReport(
        content_hash=content_hash,
        items=tuple(
            ReviewItem(domain=d, criterion=c, score=5, evidence="TEST ONLY")
            for d, cs in RUBRIC.items()
            for c in cs
        ),
        roles=tuple(
            RoleReview(
                role=r,
                reviewer_id="synthetic-test-reviewer",
                method="human",
                reviewed_at=NOW,
                evidence="TEST ONLY",
                verdict="pass",
            )
            for r in sorted(ROLES)
        ),
        checks={c: "pass" for c in REQUIRED_CHECKS},
    )
    release = build_release(
        episode_id="ICG-2026-09-25-001",
        version=1,
        synthetic=True,
        inputs=inputs,
        artifacts=artifacts,
        channels=("x", "telegram"),
        report=report,
        approved_by="TEST ONLY",
        approved_at=NOW,
    )
    return inputs, parts, report, release


def test_prepare_never_approves_art(fixture):
    prepared = prepare(**fixture)
    assert prepared["status"] == "awaiting_images_and_human_review"
    assert set(prepared["input_hashes"]) == {
        "evidence",
        "editorial",
        "claims",
        "canon",
        "script",
        "calculation",
    }


@pytest.mark.parametrize(
    "mutation", ["outcome", "battle", "cast", "form", "ref", "coverage", "count"]
)
def test_preparation_holds(fixture, mutation):
    f = fixture
    if mutation == "outcome":
        f["calculation"]["outcome"] = "OTHER"
    if mutation == "battle":
        f["script"]["panels"][0]["panel_type"] = "BATTLE"
    if mutation == "cast":
        f["script"]["panels"][0]["characters"] = []
    if mutation == "form":
        f["script"]["panels"][0]["characters"][0]["form"] = "form2"
    if mutation == "ref":
        (f["root"] / "ref.png").write_bytes(b"changed")
    if mutation == "coverage":
        f["claims"] = f["claims"][1:]
    if mutation == "count":
        f["script"]["panels"].pop()
    with pytest.raises(QualityHold):
        prepare(**f)


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity"])
def test_nonfinite_evidence(fixture, value):
    data = fixture["bundle"].evidence[0].model_dump()
    data["value"] = value
    with pytest.raises(ValidationError):
        Evidence(**data)


@pytest.mark.parametrize("mutation", ["timezone", "future", "duplicate", "day", "calendar"])
def test_provenance_holds(fixture, mutation):
    data = fixture["bundle"].model_dump()
    if mutation == "timezone":
        data["collected_at"] = NOW.replace(tzinfo=None)
    if mutation == "future":
        data["collected_at"] = NOW.replace(hour=21)
    if mutation == "duplicate":
        data["evidence"] = data["evidence"] * 2
    if mutation == "day":
        data["resolved_trading_date"] = date(2026, 9, 24)
    if mutation == "calendar":
        data["requested_date"] = date(2026, 9, 26)
    with pytest.raises(ValidationError):
        EvidenceBundle(**data)


def test_scaled_ranking_and_future_cutoff(fixture):
    scale = MetricScale(
        metric="spx",
        unit="points",
        price_basis="close",
        reference_scale=4,
        valid_as_of=date(2026, 9, 24),
        policy_version="v1",
    )
    assert rank_evidence(fixture["bundle"], [scale])[0]["score"] == 0.5
    for patch in ({"valid_as_of": date(2026, 9, 26)}, {"unit": "bp"}, {"price_basis": "intraday"}):
        with pytest.raises(QualityHold):
            rank_evidence(fixture["bundle"], [scale.model_copy(update=patch)])


@pytest.mark.parametrize(
    "kind,asserted,quoted",
    [
        ("fact", False, None),
        ("causal", True, 100),
        ("forecast", True, None),
        ("metaphor", False, None),
    ],
)
def test_unsupported_numeric_or_causal_claim(fixture, kind, asserted, quoted):
    p = dict(idx=1, key_text="SPX 100 points")
    c = Claim(
        claim_id="c",
        panel_idx=1,
        field="key_text",
        text=p["key_text"],
        kind=kind,
        evidence_ids=("e1",),
        asserted=asserted,
        quoted_value=quoted,
        quoted_unit="points",
        quoted_basis="close",
    )
    with pytest.raises(QualityHold):
        validate_claims(fixture["bundle"], [c], [p])


def test_exact_fact_quote(fixture):
    p = dict(idx=1, key_text="SPX 100 points")
    c = Claim(
        claim_id="c",
        panel_idx=1,
        field="key_text",
        text=p["key_text"],
        kind="fact",
        evidence_ids=("e1",),
        quoted_value=100,
        quoted_unit="points",
        quoted_basis="close",
    )
    validate_claims(fixture["bundle"], [c], [p])
    with pytest.raises(QualityHold):
        validate_claims(
            fixture["bundle"], [c.model_copy(update={"quoted_value": Decimal(101)})], [p]
        )


def test_thread_deferral_and_causal_direction(fixture):
    with pytest.raises(ValidationError):
        ThreadPayoff(thread_id="a")
    assert ThreadPayoff(
        thread_id="a", deferred_reason="needs setup", new_due_date=date(2026, 10, 1)
    )
    data = fixture["plan"].model_dump()
    data["beats"][0]["causal_from_panel"] = 2
    with pytest.raises(ValidationError):
        EditorialPlan(**data)
    data = fixture["plan"].model_dump()
    data["due_threads"] = ["unresolved"]
    with pytest.raises(ValidationError):
        EditorialPlan(**data)


@pytest.mark.parametrize("path", ["/etc/passwd", "../outside", "missing"])
def test_asset_path_holds(tmp_path, path):
    with pytest.raises(QualityHold):
        safe_asset(tmp_path, path)


def test_repair_preserves_cast():
    text = repair_prompt("two heroes battle", ("hero", "villain"), ["<unsafe>"])
    assert "hero, villain" in text and "OPTIONAL" in text and "<unsafe>" not in text
    assert "ONE character" not in text


@pytest.mark.parametrize("mutation", ["input", "artifact", "report", "live"])
def test_release_hash_and_fixture_holds(fixture, mutation):
    inputs, parts, report, release = reviewed_release(fixture)
    if mutation == "input":
        inputs["script"] = {}
    if mutation == "artifact":
        (fixture["root"] / "ref.png").write_bytes(b"changed")
    if mutation == "report":
        report = report.model_copy(update={"major_findings": ("defect",)})
    with pytest.raises(QualityHold):
        release.verify(fixture["root"], inputs, report, live=mutation == "live")


@pytest.mark.parametrize(
    "mutation", ["missing", "duplicate", "floor", "unverified", "machine", "critical"]
)
def test_qc_hard_gates(fixture, mutation):
    _, _, report, _ = reviewed_release(fixture)
    data = report.model_dump(mode="json")
    if mutation == "missing":
        data["items"].pop()
    if mutation == "duplicate":
        data["items"][-1] = data["items"][0]
    if mutation == "floor":
        for i in data["items"]:
            if i["domain"] == "mobile":
                i["score"] = 3
    if mutation == "unverified":
        data["checks"]["actual_images"] = "unverified"
    if mutation == "machine":
        next(r for r in data["roles"] if r["role"] == "art")["method"] = "model"
    if mutation == "critical":
        data["critical_findings"] = ["missing shield"]
    with pytest.raises(QualityHold):
        QualityReport(**data).approve()


def test_mobile_previews_and_overflow(tmp_path):
    font = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
    if not font.exists():
        pytest.skip("font fixture unavailable")
    args = dict(
        image_path=None,
        text="Protect the city.",
        text_area=Rect(x=0, y=1000, width=1080, height=350),
        protected=[],
        font_path=font,
        output=tmp_path / "panel.png",
    )
    result = compose_quality_panel(**args)
    assert result["human_readability"] == "unverified"
    assert [Image.open(p).width for p in result["previews"]] == [360, 390]
    with pytest.raises(QualityHold):
        compose_quality_panel(**{**args, "font_size": 41})
    with pytest.raises(QualityHold):
        compose_quality_panel(**{**args, "text": "huge text " * 500})
    with pytest.raises(QualityHold):
        compose_quality_panel(**{**args, "protected": [Rect(x=50, y=1050, width=20, height=20)]})


def reserve(ledger, **changes):
    return ledger.reserve(episode="e", kind="image", panel=1, **{**LIMITS, **changes})


def test_budget_persistence_unknown_and_calls(tmp_path):
    ledger = PilotLedger(tmp_path / "ledger.sqlite")
    call = reserve(ledger)
    ledger.settle(call, None)
    with pytest.raises(QualityHold):
        reserve(PilotLedger(ledger.path))
    ledger.settle(call, ".1")
    call = reserve(ledger)
    ledger.settle(call, ".1")
    with pytest.raises(QualityHold):
        reserve(ledger)
    assert money_units("0.0000001") == 1
    for cost in ["NaN", "-1", "Infinity"]:
        with pytest.raises(QualityHold):
            money_units(cost)


def test_atomic_budget_race(tmp_path):
    ledger = PilotLedger(tmp_path / "ledger.sqlite")

    def claim(_):
        try:
            return reserve(ledger)
        except QualityHold:
            return None

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(claim, range(8)))
    assert len([r for r in results if r]) == 1


def test_month_boundary_and_cap(tmp_path):
    ledger = PilotLedger(tmp_path / "ledger.sqlite")
    call = reserve(ledger, now=NOW, monthly_cap=".1")
    ledger.settle(call, ".1")
    with pytest.raises(QualityHold):
        reserve(ledger, monthly_cap=".1", now=NOW)
    assert reserve(ledger, monthly_cap=".1", now=NOW.replace(month=10))


def test_fencing_and_reconciliation(tmp_path):
    ledger = PilotLedger(tmp_path / "ledger.sqlite")
    token, _ = ledger.claim("part", "hash")
    with pytest.raises(QualityHold):
        ledger.claim("part", "hash")
    ledger.reconcile("part", external_id="remote1", reviewer="qa", proof="provider receipt")
    with pytest.raises(QualityHold):
        ledger.finish("part", token, "published", "remote2")
    assert ledger.claim("part", "hash") == (None, "remote1")
    with pytest.raises(QualityHold):
        ledger.claim("part", "different")


def test_bounded_generation_no_hidden_retry(fixture):
    ledger = PilotLedger(fixture["root"] / "ledger.sqlite")
    calls = []
    image = BytesIO()
    Image.new("RGB", (20, 20)).save(image, format="PNG")

    def provider(prompt, refs):
        calls.append(refs)
        return image.getvalue(), ".05"

    args = dict(
        ledger=ledger,
        episode="e",
        panel=1,
        prompt="hero",
        refs=(fixture["root"] / "ref.png",),
        output=fixture["root"] / "p1.png",
        provider=provider,
        limits=LIMITS,
    )
    assert generate_bounded(**args).exists()
    with pytest.raises(QualityHold):
        generate_bounded(**args)
    assert len(calls) == 1
    assert ledger.snapshot()["calls"][0]["amount"] == 50000


def test_provider_timeout_holds_next_call(fixture):
    ledger = PilotLedger(fixture["root"] / "ledger.sqlite")
    calls = []

    def provider(*args):
        calls.append(1)
        raise TimeoutError()

    args = dict(
        ledger=ledger,
        episode="e",
        panel=1,
        prompt="hero",
        refs=(fixture["root"] / "ref.png",),
        output=fixture["root"] / "p1.png",
        provider=provider,
        limits=LIMITS,
    )
    with pytest.raises(TimeoutError):
        generate_bounded(**args)
    with pytest.raises(QualityHold):
        generate_bounded(**args)
    assert len(calls) == 1


def test_partial_publish_restart_never_reposts(fixture):
    inputs, parts, report, release = reviewed_release(fixture)
    ledger = PilotLedger(fixture["root"] / "ledger.sqlite")
    sent = []

    def sender(channel, index, part):
        sent.append((channel, index))
        if channel == "x" and index == 2:
            raise TimeoutError()
        return f"{channel}-{index}"

    args = dict(
        ledger=ledger,
        release=release,
        root=fixture["root"],
        inputs=inputs,
        report=report,
        parts=parts,
        sender=sender,
    )
    with pytest.raises(QualityHold):
        publish_pilot(**args)
    with pytest.raises(QualityHold):
        publish_pilot(**{**args, "ledger": PilotLedger(ledger.path)})
    assert sent == [("x", 1), ("x", 2)]
    key = f"{release.episode_id}:1:x:2"
    ledger.reconcile(key, external_id="x-2", reviewer="qa", proof="simulated provider receipt")
    result = publish_pilot(**args)
    assert result == {"x": ["x-1", "x-2"], "telegram": ["telegram-1"]}
    assert business_status(ledger, [key])["status"] == "complete"
    assert business_status(ledger, ["missing"])["status"] == "hold"
    with pytest.raises(QualityHold):
        publish_pilot(**args, live=True)


@pytest.mark.parametrize(
    "channels,x,tg",
    [
        (["x"], [], False),
        (["all"], ["one"], False),
        (["telegram"], [], False),
        (["typo"], ["one"], True),
    ],
)
def test_publication_channel_hold(channels, x, tg):
    from engine.quality.publish_guard import require_channel_success

    with pytest.raises(QualityHold):
        require_channel_success(channels, x, tg)


def test_pilot_cannot_enter_legacy_publisher():
    from engine.quality.publish_guard import guard_legacy_track, require_channel_success

    with pytest.raises(QualityHold):
        guard_legacy_track({"_webtoon_quality": {"version": 1}}, {})
    require_channel_success(["all"], ["tweet"], True)


def test_gemini_recovery_preserves_all_refs(monkeypatch, tmp_path):
    from engine.image import gemini_client

    calls = []

    def generator(client, prompt, refs, aspect_ratio=None):
        calls.append((prompt, refs))
        return b"image", 1, 1

    generator._retry_count = 2
    monkeypatch.setattr(gemini_client, "_generate_one", generator)
    monkeypatch.setattr(gemini_client, "_get_client", lambda: object())
    refs = [tmp_path / "hero.png", tmp_path / "villain.png"]
    gemini_client.generate_panel(1, "two characters", refs, tmp_path, tmp_path / "run.log")
    assert calls[0][1] == refs
    assert "ONE character" not in calls[0][0]


def test_synthetic_label_cannot_be_removed(fixture):
    inputs, _, report, release = reviewed_release(fixture)
    with pytest.raises(QualityHold):
        release.model_copy(update={"synthetic": False}).verify(fixture["root"], inputs, report)


def test_cli_prepares_and_holds_invalid_contract(fixture, capsys):
    import json

    from scripts.run_webtoon_quality import main

    f = fixture
    document = {
        "evidence": f["bundle"].model_dump(mode="json"),
        "editorial": f["plan"].model_dump(mode="json"),
        "claims": [c.model_dump(mode="json") for c in f["claims"]],
        "canon": f["canon"].model_dump(mode="json"),
        "script": f["script"],
        "calculation": f["calculation"],
    }
    contract = f["root"] / "contract.json"
    contract.write_text(json.dumps(document))
    output = f["root"] / "prepared.json"
    argv = [
        "prepare",
        "--contract",
        str(contract),
        "--root",
        str(f["root"]),
        "--output",
        str(output),
    ]
    assert main(argv) == 0
    assert json.loads(output.read_text())["status"] == "awaiting_images_and_human_review"
    document["calculation"] = {}
    contract.write_text(json.dumps(document))
    assert main(argv) == 1
    assert "HOLD" in capsys.readouterr().out


def test_history_failure_does_not_mark_asset_published(monkeypatch):
    from unittest.mock import MagicMock

    from engine.common import supabase_client
    from engine.persist import asset_writer
    from engine.publish.history_writer import record_publish

    table = MagicMock()
    table.insert.return_value.execute.side_effect = RuntimeError("history unavailable")
    monkeypatch.setattr(supabase_client, "icg_table", lambda _: table)
    patch = MagicMock()
    monkeypatch.setattr(asset_writer, "patch_by_episode", patch)
    with pytest.raises(RuntimeError):
        record_publish("2026-09-25", "ICG-2026-09-25-002", "BATTLE", ["tweet"], False, 8, 0, 0, 1)
    patch.assert_not_called()


def test_history_targets_exact_episode(monkeypatch):
    from unittest.mock import MagicMock

    from engine.common import supabase_client
    from engine.persist import asset_writer
    from engine.publish.history_writer import record_publish

    monkeypatch.setattr(supabase_client, "icg_table", MagicMock())
    patch = MagicMock()
    monkeypatch.setattr(asset_writer, "patch_by_episode", patch)
    record_publish("2026-09-25", "ICG-2026-09-25-002", "BATTLE", ["tweet"], False, 8, 0, 0, 1)
    assert patch.call_args.args[:2] == ("2026-09-25", 2)
    with pytest.raises(ValueError):
        record_publish("2026-09-25", "ICG-2026-09-25-002", "BATTLE", [], False, 8, 0, 0, 1)


@pytest.mark.parametrize("dry_run,tg_success", [(True, True), (False, False), (False, True)])
def test_run_publish_history_and_episode_safety(monkeypatch, tmp_path, dry_run, tg_success):
    from unittest.mock import MagicMock

    from engine.common import logger as common_logger
    from engine.common import supabase_client
    from engine.publish import battle_video_publish, history_writer, telegram_publisher
    from scripts import run_publish

    Image.new("RGB", (2, 2)).save(tmp_path / "p1.png")
    query = MagicMock()

    def table(name):
        q = query if name == "episode_assets" else MagicMock()
        q.select.return_value = q
        q.eq.return_value = q
        q.order.return_value = q
        q.limit.return_value = q
        q.execute.return_value.data = (
            [
                {
                    "episode_no": 2,
                    "event_type": "BATTLE",
                    "status": "assembled",
                    "script_json": {},
                    "slides_json": [{"path": str(tmp_path / "p1.png")}],
                }
            ]
            if name == "episode_assets"
            else []
        )
        return q

    monkeypatch.setattr(supabase_client, "icg_table", table)
    monkeypatch.setattr(common_logger, "StepLogger", MagicMock())
    monkeypatch.setattr(
        battle_video_publish,
        "build_battle_video_plan",
        lambda **kwargs: MagicMock(enabled=False, reason="no video"),
    )
    monkeypatch.setattr(
        telegram_publisher,
        "publish_episode_telegram",
        lambda *args, **kwargs: {"test-channel": tg_success},
    )
    from engine.publish import claim_guard

    monkeypatch.setattr(claim_guard, "claim_publication", lambda *args: "test-claim")
    monkeypatch.setattr(claim_guard, "finish_publication", lambda *args: None)
    history = MagicMock()
    monkeypatch.setattr(history_writer, "record_publish", history)
    monkeypatch.setenv("DRY_RUN", "true" if dry_run else "false")
    monkeypatch.setenv("TELEGRAM_FREE_CHANNEL_ID", "test-channel")
    monkeypatch.setattr("sys.argv", ["run_publish", "--episode", "ICG-2026-09-25-002"])
    if not dry_run and not tg_success:
        with pytest.raises(QualityHold):
            run_publish.main()
    else:
        run_publish.main()
    assert history.call_count == (1 if not dry_run and tg_success else 0)
    query.eq.assert_any_call("episode_no", 2)
