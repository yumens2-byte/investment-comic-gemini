"""Offline review regressions: source holds, budget overruns and CAS fencing."""

import threading
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from types import SimpleNamespace

import pytest
from PIL import Image

from engine.publish.claim_guard import (
    PREFIX,
    claim_publication,
    finish_publication,
    require_no_publication_hold,
)
from engine.quality.contracts import QualityHold
from engine.quality.ledger import PilotLedger
from engine.quality.pipeline import business_status, generate_bounded
from engine.quality.publish_guard import guard_legacy_track, normalize_channels


class AtomicFakeTable:
    def __init__(self):
        self.row = dict(
            episode_date="2026-09-25", episode_no=2, status="assembled", error_message=None,
            updated_at="2026-09-25T00:00:00+00:00",
        )
        self.lock = threading.Lock()
        self.version = 0

    def update(self, values):
        owner = self

        class Query:
            def __init__(self):
                self.filters = {}

            def eq(self, column, value):
                self.filters[column] = value
                return self

            def is_(self, column, value):
                assert value == "null"
                return self.eq(column, None)

            def execute(self):
                with owner.lock:
                    if all(owner.row.get(k) == v for k, v in self.filters.items()):
                        owner.row.update(values)
                        # Mirrors icg.touch_updated_at: every UPDATE moves the row version.
                        owner.version += 1
                        owner.row["updated_at"] = f"2026-09-25T00:00:{owner.version:02d}+00:00"
                        return SimpleNamespace(data=[dict(owner.row)])
                    return SimpleNamespace(data=[])

        return Query()


def test_episode_compare_and_swap_and_fencing(monkeypatch):
    from engine.common import supabase_client

    table = AtomicFakeTable()
    initial = dict(table.row)
    monkeypatch.setattr(supabase_client, "icg_table", lambda _: table)

    def claim(_):
        try:
            return claim_publication(initial, "2026-09-25", 2)
        except QualityHold:
            return None

    with ThreadPoolExecutor(max_workers=8) as pool:
        tokens = [t for t in pool.map(claim, range(8)) if t]
    assert len(tokens) == 1
    with pytest.raises(QualityHold):
        require_no_publication_hold(table.row)
    with pytest.raises(QualityHold):
        finish_publication("2026-09-25", 2, "stale")
    assert table.row["error_message"] == tokens[0]
    finish_publication("2026-09-25", 2, tokens[0])
    assert table.row["error_message"] is None


def test_claim_database_failure_is_hold(monkeypatch):
    from engine.common import supabase_client

    def unavailable(_):
        raise RuntimeError("DB unavailable")

    monkeypatch.setattr(supabase_client, "icg_table", unavailable)
    with pytest.raises(RuntimeError):
        claim_publication({"status": "assembled"}, "2026-09-25", 2)


@pytest.mark.parametrize("value", ["typo", "x,typo", "", "x,"])
def test_channels_invalid_before_dispatch(value):
    with pytest.raises(QualityHold):
        normalize_channels(value)


def test_channel_normalization_and_quality_marker_presence():
    assert normalize_channels(" x, telegram, X ") == ["x", "telegram"]
    assert normalize_channels("all,x") == ["x", "telegram"]
    for marker in (
        {"_webtoon_quality": {}},
        {"_webtoon_quality": False},
        {"quality_release": None},
    ):
        with pytest.raises(QualityHold):
            guard_legacy_track(marker, {})


def test_cost_overrun_is_durable_and_not_completed(tmp_path):
    ref = tmp_path / "ref.png"
    Image.new("RGB", (2, 2)).save(ref)
    image = BytesIO()
    Image.new("RGB", (2, 2)).save(image, format="PNG")
    ledger = PilotLedger(tmp_path / "ledger.sqlite")
    calls = []

    def provider(*_):
        calls.append(1)
        return image.getvalue(), "1"

    limits = dict(
        estimate=".01", episode_cap=".02", daily_cap=".02", monthly_cap=".02", max_calls=4
    )
    args = dict(
        ledger=ledger,
        episode="e",
        panel=1,
        prompt="hero",
        refs=(ref,),
        output=tmp_path / "P1.png",
        provider=provider,
        limits=limits,
    )
    with pytest.raises(QualityHold):
        generate_bounded(**args)
    state = ledger.snapshot()
    assert state["calls"][0]["state"] == "over_budget"
    assert state["calls"][0]["amount"] == 1_000_000
    assert [e["kind"] for e in state["events"]] == ["cost_overrun"]
    assert not args["output"].exists()
    assert business_status(ledger, ["part"])["status"] == "hold"
    with pytest.raises(QualityHold):
        generate_bounded(**args)
    assert calls == [1]


@pytest.fixture
def legacy_run(monkeypatch, tmp_path):
    from unittest.mock import MagicMock

    from engine.common import logger as common_logger
    from engine.common import supabase_client
    from engine.publish import (
        battle_video_publish,
        claim_guard,
        history_writer,
        telegram_publisher,
        telegram_video_publisher,
        x_publisher,
        x_video_publisher,
    )
    from scripts import run_publish

    Image.new("RGB", (2, 2)).save(tmp_path / "slide.png")
    row = dict(
        episode_no=2,
        event_type="BATTLE",
        status="assembled",
        error_message=None,
        script_json={"caption_x_final": x_publisher.DISCLAIMER_REQUIRED},
        slides_json=[{"path": str(tmp_path / "slide.png")}],
    )
    calls = {"db": 0, "x": 0, "tg": 0, "history": 0, "tg_ok": True}

    def table(name):
        calls["db"] += 1
        q = MagicMock()
        q.select.return_value = q
        q.eq.return_value = q
        q.order.return_value = q
        q.limit.return_value = q
        q.execute.return_value.data = [dict(row)] if name == "episode_assets" else []
        return q

    def claim(*args):
        row["error_message"] = PREFIX + "test"
        return row["error_message"]

    def finish(*args):
        row["error_message"] = None

    def x(*args, **kwargs):
        calls["x"] += 1
        return ["posted"]

    def tg(*args, **kwargs):
        calls["tg"] += 1
        return {"tg": calls["tg_ok"]}

    def history(*args, **kwargs):
        calls["history"] += 1

    monkeypatch.setattr(supabase_client, "icg_table", table)
    monkeypatch.setattr(common_logger, "StepLogger", MagicMock())
    monkeypatch.setattr(
        battle_video_publish,
        "build_battle_video_plan",
        lambda **kwargs: SimpleNamespace(enabled=False, reason="none"),
    )
    monkeypatch.setattr(claim_guard, "claim_publication", claim)
    monkeypatch.setattr(claim_guard, "finish_publication", finish)
    monkeypatch.setattr(x_publisher, "publish_episode_x", x)
    monkeypatch.setattr(telegram_publisher, "publish_episode_telegram", tg)
    monkeypatch.setattr(history_writer, "record_publish", history)
    monkeypatch.setenv("DRY_RUN", "false")
    monkeypatch.setenv("TELEGRAM_FREE_CHANNEL_ID", "tg")
    for key in ("TELEGRAM_BOT_TOKEN", "X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN",
                "X_ACCESS_TOKEN_SECRET"):
        monkeypatch.setenv(key, "test-configured")
    monkeypatch.setenv("FORCE_REPUBLISH", "false")

    def run(channels="x, telegram", video=False):
        import sys

        argv = ["run_publish", "--episode", "ICG-2026-09-25-002", "--channels", channels]
        if video:
            argv.append("--video-only")
        monkeypatch.setattr(sys, "argv", argv)
        run_publish.main()

    return (
        run,
        calls,
        row,
        monkeypatch,
        battle_video_publish,
        x_video_publisher,
        telegram_video_publisher,
    )


def test_normalized_channels_use_same_dispatch_and_verdict(legacy_run):
    run, calls, row, *_ = legacy_run
    run()
    assert (calls["x"], calls["tg"], calls["history"]) == (1, 1, 1)
    assert row["error_message"] is None


def test_invalid_channels_make_no_db_or_external_calls(legacy_run):
    run, calls, *_ = legacy_run
    with pytest.raises(QualityHold):
        run("x,typo")
    assert (calls["db"], calls["x"], calls["tg"]) == (0, 0, 0)


def test_partial_success_blocks_all_automatic_reposts(legacy_run):
    run, calls, row, *_ = legacy_run
    calls["tg_ok"] = False
    with pytest.raises(QualityHold):
        run()
    assert row["error_message"].startswith(PREFIX)
    with pytest.raises(QualityHold):
        run()
    assert (calls["x"], calls["tg"], calls["history"]) == (1, 1, 0)


@pytest.mark.parametrize("missing", ["image", "telegram_config"])
def test_preflight_before_claim_and_first_send(legacy_run, missing):
    run, calls, row, monkeypatch, *_ = legacy_run
    if missing == "image":
        row["slides_json"][0]["path"] = "/missing/image.png"
    else:
        monkeypatch.delenv("TELEGRAM_FREE_CHANNEL_ID")
    with pytest.raises((QualityHold, ValueError, FileNotFoundError)):
        run()
    assert row["error_message"] is None
    assert (calls["x"], calls["tg"]) == (0, 0)


def test_video_only_failure_keeps_hold_and_does_not_report_success(legacy_run, tmp_path):
    run, calls, row, monkeypatch, planner, x_video, _ = legacy_run
    plan = SimpleNamespace(
        enabled=True,
        channels=("x",),
        video_path=tmp_path / "video.mp4",
        x_caption="clip",
        reason="enabled",
    )
    monkeypatch.setattr(planner, "build_battle_video_plan", lambda **kwargs: plan)

    def timeout(**kwargs):
        raise TimeoutError("ambiguous provider result")

    monkeypatch.setattr(x_video, "publish_video_to_x", timeout)
    with pytest.raises(RuntimeError, match="video-only publication failed"):
        run("x", True)
    assert row["error_message"].startswith(PREFIX)
    with pytest.raises(QualityHold):
        run("x", True)
    assert calls["history"] == 0


@pytest.mark.parametrize("channel,field", [("x", "tweet_id"), ("telegram", "message_id")])
def test_video_missing_id_does_not_release_hold(legacy_run, tmp_path, channel, field):
    run, calls, row, monkeypatch, planner, x_video, tg_video = legacy_run
    plan = SimpleNamespace(
        enabled=True,
        channels=(channel,),
        video_path=tmp_path / "clip.mp4",
        x_caption="clip",
        telegram_title="clip",
        hashtags=(),
        telegram_teaser="clip",
        reason="enabled",
    )
    monkeypatch.setattr(planner, "build_battle_video_plan", lambda **kwargs: plan)
    provider = x_video if channel == "x" else tg_video
    function = "publish_video_to_x" if channel == "x" else "publish_to_free_channel"
    monkeypatch.setattr(provider, function, lambda **kwargs: {field: None})
    with pytest.raises(RuntimeError, match="video-only publication failed"):
        run(channel, True)
    assert row["error_message"].startswith(PREFIX)
    assert calls["history"] == 0


@pytest.mark.parametrize("value", [None, "None", "", "null", 0, True, {}, []])
def test_invalid_publication_id(value):
    from engine.quality.publish_guard import require_publication_id

    with pytest.raises(QualityHold):
        require_publication_id({"tweet_id": value}, "tweet_id")


@pytest.mark.parametrize("missing", ["TELEGRAM_BOT_TOKEN", "X_API_KEY", "X_API_SECRET",
                                     "X_ACCESS_TOKEN", "X_ACCESS_TOKEN_SECRET"])
def test_missing_provider_config_never_claims_or_sends(legacy_run, missing):
    run, calls, row, monkeypatch, *_ = legacy_run
    monkeypatch.delenv(missing)
    with pytest.raises(QualityHold):
        run()
    assert row["error_message"] is None
    assert calls["x"] == calls["tg"] == calls["history"] == 0


@pytest.mark.parametrize("status", ["failed", "draft", "analyzed", "unknown"])
def test_direct_live_unready_status_never_claims_or_sends(legacy_run, status):
    run, calls, row, *_ = legacy_run
    row["status"] = status
    with pytest.raises(ValueError, match="not ready"):
        run()
    assert row["error_message"] is None
    assert calls["x"] == calls["tg"] == calls["history"] == 0
