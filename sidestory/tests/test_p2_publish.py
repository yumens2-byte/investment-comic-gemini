"""P2: publish / verify stages, Graph adapter, side disclaimer slide (offline, no network)."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests
from PIL import Image

from sidestory.adapters.facebook.graph import DEFAULT_VERSION, FacebookPagePublisher
from sidestory.app import disclaimer_slide
from sidestory.app.p1 import P1Deps, run_p1
from sidestory.app.publish import AMBIGUOUS, SAFE, PublishDeps, run_publish, run_verify
from sidestory.ports.publisher import PublishError
from sidestory.tests.fixtures import FakeFeed, FakeStore, main_row
from sidestory.tests.p1_fixtures import (
    FakeComposer,
    FakeImages,
    FakeInspector,
    FakeLLM,
    FakePrompts,
    make_refs,
    raw_script,
)

TUE = date(2026, 10, 6)
SID = "SIDE-2026-10-06-01"
FONT = Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc")


class FakePublisher:
    channel = "facebook"

    def __init__(self, *, fail_check=None, fail_upload_at=None, fail_post=None,
                 found=None, fail_find=None):
        self.fail_check, self.fail_upload_at = fail_check, fail_upload_at
        self.fail_post, self.found, self.fail_find = fail_post, found, fail_find
        self.uploads: list[str] = []
        self.posts: list[tuple[str, list[str]]] = []
        self.finds = 0

    def check(self):
        if self.fail_check:
            raise self.fail_check
        return {"id": "123", "name": "EDT Side"}

    def upload_photo(self, path):
        if self.fail_upload_at is not None and len(self.uploads) + 1 == self.fail_upload_at:
            self.fail_upload_at = None
            raise PublishError("HTTP 400 code=324 bad image")
        self.uploads.append(Path(path).name)
        return f"photo-{len(self.uploads)}"

    def create_post(self, message, photo_ids):
        if self.fail_post:
            exc, self.fail_post = self.fail_post, None
            raise exc
        self.posts.append((message, list(photo_ids)))
        return "123_999"

    def find_recent_post(self, message, limit=10):
        self.finds += 1
        if self.fail_find:
            raise self.fail_find
        return self.found

    def get_post(self, post_id):
        return {"id": post_id, "permalink_url": f"https://www.facebook.com/{post_id}"}


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    feed = FakeFeed([main_row("2026-10-06")], fingerprints=("a" * 64,))
    store = FakeStore()
    p1 = P1Deps(feed=feed, store=store, llm=FakeLLM([raw_script()]), prompts=FakePrompts(),
                images=FakeImages(), composer=FakeComposer(), characters=make_refs(tmp_path),
                output_root=tmp_path / "output/sidestory", ref_root=tmp_path,
                inspector=FakeInspector(), run_id="555")
    assert run_p1(TUE, p1)[-1].status == "assembled"
    return SimpleNamespace(feed=feed, store=store, tmp=tmp_path)


def deps(env, publisher=None, live=False):
    return PublishDeps(feed=env.feed, store=env.store, publisher=publisher, live=live)


def row(env):
    return env.store.get_episode(SID)


# ── dry run ──────────────────────────────────────────────────────────────────
def test_dry_run_without_credentials_changes_nothing(env) -> None:
    res = run_publish(TUE, deps(env))
    assert res.ok and res.status == "assembled" and res.detail["dry_run"] is True
    assert res.detail["slides"] == 8 and res.detail["page"] is None
    assert row(env)["status"] == "assembled"
    assert env.store.publications == [{"side_episode_id": SID, "channel": "facebook",
                                       "post_id": None, "photo_ids": [], "dry_run": True}]
    assert [g.gate for g in res.gates] == ["SG-1", "SG-6"]


def test_dry_run_checks_credentials_but_never_uploads(env) -> None:
    pub = FakePublisher()
    res = run_publish(TUE, deps(env, pub))
    assert res.ok and res.detail["page"]["name"] == "EDT Side"
    assert pub.uploads == [] and pub.posts == []


def test_dry_run_credential_failure_is_error(env) -> None:
    res = run_publish(TUE, deps(env, FakePublisher(fail_check=PublishError("HTTP 190"))))
    assert res.status == "error" and "credential" in res.detail["reason"]
    assert row(env)["status"] == "assembled"


def test_dry_run_copy_problem_is_error_not_hold(env) -> None:
    row(env)["script_json"]["caption_fb"] = "본편 결과는 OBSERVATION"   # no disclaimer, code
    res = run_publish(TUE, deps(env))
    assert res.status == "error" and "SG-5" in res.detail["reason"]
    assert "OBSERVATION" in res.detail["reason"] and row(env)["status"] == "assembled"


# ── live ─────────────────────────────────────────────────────────────────────
def test_live_publish_posts_once_in_slide_order(env) -> None:
    pub = FakePublisher()
    res = run_publish(TUE, deps(env, pub, live=True))
    assert res.status == "published" and res.detail["post_id"] == "123_999"
    assert pub.uploads == [f"S{i}.png" for i in range(1, 9)]
    assert pub.posts == [(row(env)["script_json"]["caption_fb"],
                          [f"photo-{i}" for i in range(1, 9)])]
    assert row(env)["status"] == "published" and row(env)["publish_hold"] is None
    live = env.store.live_publication(SID, "facebook")
    assert live["post_id"] == "123_999" and len(live["photo_ids"]) == 8
    assert [g.gate for g in res.gates] == ["SG-1", "SG-6", "SG-7"]
    # second run: no new call
    again = run_publish(TUE, deps(env, pub, live=True))
    assert again.ok and again.detail["reason"] == "already published" and len(pub.posts) == 1


def test_missing_slides_is_error_with_restore_hint(env) -> None:
    Path(row(env)["slides_json"][2]["path"]).unlink()
    res = run_publish(TUE, deps(env, FakePublisher(), live=True))
    assert res.status == "error" and "555" in res.detail["reason"]
    assert row(env)["status"] == "assembled"


def test_wrong_slide_count_is_error(env) -> None:
    r = row(env)
    r["slides_json"] = r["slides_json"][:7]
    r["manifest_json"]["slides"].pop("S8.png")
    res = run_publish(TUE, deps(env, live=True))
    assert res.status == "error" and "expected 8 slides" in res.detail["reason"]


def test_live_copy_problem_holds_safe(env) -> None:
    row(env)["script_json"]["caption_fb"] = "x"
    pub = FakePublisher()
    res = run_publish(TUE, deps(env, pub, live=True))
    assert res.status == "hold" and row(env)["publish_hold"].startswith(SAFE)
    assert pub.uploads == []


def test_upload_failure_holds_safe_then_retry_publishes(env) -> None:
    pub = FakePublisher(fail_upload_at=3)
    res = run_publish(TUE, deps(env, pub, live=True))
    assert res.status == "hold" and "S3" in res.detail["reason"]
    assert row(env)["publish_hold"].startswith(SAFE) and pub.posts == []
    assert row(env)["error_message"].startswith("publish:")
    # without the checkbox nothing happens
    assert run_publish(TUE, deps(env, pub, live=True)).status == "hold"
    res = run_publish(TUE, deps(env, pub, live=True), retry_hold=True)
    assert res.status == "published" and pub.finds == 0 and len(pub.posts) == 1


def test_rejected_post_is_safe(env) -> None:
    pub = FakePublisher(fail_post=PublishError("HTTP 400 code=100", ambiguous=False))
    res = run_publish(TUE, deps(env, pub, live=True))
    assert res.status == "hold" and row(env)["publish_hold"].startswith(SAFE)


def test_ambiguous_post_reconciles_instead_of_double_posting(env) -> None:
    pub = FakePublisher(fail_post=PublishError("ReadTimeout", ambiguous=True))
    res = run_publish(TUE, deps(env, pub, live=True))
    assert res.status == "hold" and row(env)["publish_hold"].startswith(AMBIGUOUS)
    pub.found = "123_777"        # the post did reach the Page
    uploads = len(pub.uploads)
    res = run_publish(TUE, deps(env, pub, live=True), retry_hold=True)
    assert res.status == "published" and res.detail["reconciled"] is True
    assert res.detail["post_id"] == "123_777" and pub.posts == []
    assert len(pub.uploads) == uploads


def test_ambiguous_post_not_found_posts_once(env) -> None:
    pub = FakePublisher(fail_post=PublishError("HTTP 500", ambiguous=True))
    run_publish(TUE, deps(env, pub, live=True))
    res = run_publish(TUE, deps(env, pub, live=True), retry_hold=True)
    assert res.status == "published" and res.detail["reconciled"] is False
    assert pub.finds == 1 and len(pub.posts) == 1


def test_ambiguous_and_page_unreadable_stays_hold(env) -> None:
    pub = FakePublisher(fail_post=PublishError("timeout", ambiguous=True),
                        fail_find=PublishError("HTTP 403"))
    run_publish(TUE, deps(env, pub, live=True))
    res = run_publish(TUE, deps(env, pub, live=True), retry_hold=True)
    assert res.status == "hold" and row(env)["publish_hold"].startswith(AMBIGUOUS)
    assert pub.posts == []


def test_lost_publication_row_is_recovered(env) -> None:
    pub = FakePublisher()
    real = env.store.insert_publication
    env.store.insert_publication = lambda r: (_ for _ in ()).throw(RuntimeError("db down"))
    res = run_publish(TUE, deps(env, pub, live=True))
    assert res.status == "error" and "POSTED as 123_999" in res.detail["reason"]
    assert row(env)["status"] == "publishing"
    # a dry run must not touch an interrupted live publish
    assert run_publish(TUE, deps(env, pub)).status == "error"
    env.store.insert_publication = real
    pub.found = "123_999"
    res = run_publish(TUE, deps(env, pub, live=True))
    assert res.status == "published" and len(pub.posts) == 1


def test_main_change_before_post_holds(env) -> None:
    env.feed._fps = ["a" * 64, "b" * 64]
    env.feed.calls = 0
    pub = FakePublisher()
    res = run_publish(TUE, deps(env, pub, live=True))
    assert res.status == "hold" and pub.posts == [] and "SG-7" in [g.gate for g in res.gates]


def test_cas_conflict_does_not_post(env) -> None:
    pub = FakePublisher()
    env.store.update_episode = lambda *a, **k: False
    res = run_publish(TUE, deps(env, pub, live=True))
    assert res.status == "error" and pub.uploads == []


def test_production_hold_is_not_released_by_publish(env) -> None:
    r = row(env)
    r.update(status="hold", error_message="assembly: P5 misdetection")
    res = run_publish(TUE, deps(env, FakePublisher(), live=True), retry_hold=True)
    assert res.status == "error" and "p1" in res.detail["reason"] and r["status"] == "hold"


def test_publish_requires_assembled(env) -> None:
    row(env)["status"] = "image_done"
    res = run_publish(TUE, deps(env))
    assert res.status == "error" and "assembled" in res.detail["reason"]


def test_live_without_publisher_is_error(env) -> None:
    assert run_publish(TUE, deps(env, None, live=True)).status == "error"


# ── verify ───────────────────────────────────────────────────────────────────
def test_verify(env) -> None:
    assert run_verify(TUE, deps(env)).status == "error"
    res = run_verify(TUE, deps(env, FakePublisher()))
    assert res.ok and res.detail["page"]["id"] == "123" and "post" not in res.detail
    run_publish(TUE, deps(env, FakePublisher(), live=True))
    res = run_verify(TUE, deps(env, FakePublisher()))
    assert res.detail["post"]["permalink_url"].endswith("123_999")


# ── Graph adapter ────────────────────────────────────────────────────────────
class _Resp:
    def __init__(self, status, body):
        self.status_code, self._body = status, body

    def json(self):
        if self._body is None:
            raise ValueError("no json")
        return self._body


class _Session:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def _next(self, method, url, **kw):
        self.calls.append((method, url, kw))
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def get(self, url, **kw):
        return self._next("GET", url, **kw)

    def post(self, url, **kw):
        return self._next("POST", url, **kw)


TOKEN = "EAAsecret-token-value"


def _fb(*responses):
    s = _Session(*responses)
    return FacebookPagePublisher("123", TOKEN, session=s), s


def test_graph_requires_credentials() -> None:
    with pytest.raises(PublishError):
        FacebookPagePublisher("", "x")


def test_graph_check_and_version() -> None:
    fb, s = _fb(_Resp(200, {"id": "123", "name": "EDT"}))
    assert fb.check() == {"id": "123", "name": "EDT"}
    method, url, kw = s.calls[0]
    assert url == f"https://graph.facebook.com/{DEFAULT_VERSION}/123"
    assert kw["params"]["fields"] == "id,name" and kw["params"]["access_token"] == TOKEN
    fb2, _ = _fb(_Resp(200, {"id": "999"}))
    with pytest.raises(PublishError, match="does not resolve"):
        fb2.check()


def test_graph_upload_is_unpublished_png(tmp_path) -> None:
    p = tmp_path / "S1.png"
    Image.new("RGB", (8, 8)).save(p)
    fb, s = _fb(_Resp(200, {"id": "ph1"}))
    assert fb.upload_photo(p) == "ph1"
    _, url, kw = s.calls[0]
    assert url.endswith("/123/photos") and kw["data"]["published"] == "false"
    assert kw["files"]["source"][0] == "S1.png" and kw["files"]["source"][2] == "image/png"


def test_graph_post_attaches_media_in_order() -> None:
    fb, s = _fb(_Resp(200, {"id": "123_1"}))
    assert fb.create_post("본문", ["a", "b"]) == "123_1"
    data = s.calls[0][2]["data"]
    assert data["message"] == "본문" and data["access_token"] == TOKEN
    assert json.loads(data["attached_media[0]"]) == {"media_fbid": "a"}
    assert json.loads(data["attached_media[1]"]) == {"media_fbid": "b"}


@pytest.mark.parametrize("item,ambiguous", [
    (requests.ReadTimeout("read timed out"), True),
    (requests.ConnectTimeout("connect timed out"), False),
    (_Resp(500, {"error": {"message": "unknown", "code": 2}}), True),
    (_Resp(400, {"error": {"message": "bad", "code": 100}}), False),
    (_Resp(200, {}), True),                              # no id back
])
def test_graph_post_ambiguity(item, ambiguous) -> None:
    fb, _ = _fb(item)
    with pytest.raises(PublishError) as err:
        fb.create_post("m", ["a"])
    assert err.value.ambiguous is ambiguous


def test_graph_upload_is_never_ambiguous(tmp_path) -> None:
    p = tmp_path / "S1.png"
    Image.new("RGB", (8, 8)).save(p)
    fb, _ = _fb(requests.ReadTimeout("x"))
    with pytest.raises(PublishError) as err:
        fb.upload_photo(p)
    assert err.value.ambiguous is False


def test_graph_errors_never_leak_the_token() -> None:
    fb, _ = _fb(requests.ConnectionError(f"https://graph.facebook.com/x?access_token={TOKEN}"))
    with pytest.raises(PublishError) as err:
        fb.check()
    assert TOKEN not in str(err.value) and "***" in str(err.value)
    fb, _ = _fb(_Resp(400, {"error": {"message": f"bad token {TOKEN}", "code": 190}}))
    with pytest.raises(PublishError) as err:
        fb.check()
    assert TOKEN not in str(err.value) and "code=190" in str(err.value)
    fb, _ = _fb(_Resp(502, None))
    with pytest.raises(PublishError, match="HTTP 502"):
        fb.check()


def test_graph_find_recent_post() -> None:
    fb, s = _fb(_Resp(200, {"data": [{"id": "1", "message": "other"},
                                      {"id": "2", "message": " 본문 \n"}]}))
    assert fb.find_recent_post("본문") == "2"
    assert s.calls[0][1].endswith("/123/feed")
    fb, _ = _fb(_Resp(200, {"data": []}))
    assert fb.find_recent_post("본문") is None


def test_graph_get_post() -> None:
    fb, s = _fb(_Resp(200, {"id": "123_1", "permalink_url": "u"}))
    assert fb.get_post("123_1")["permalink_url"] == "u"
    assert "permalink_url" in s.calls[0][2]["params"]["fields"]


# ── side disclaimer slide ────────────────────────────────────────────────────
def test_disclaimer_text_is_font_safe() -> None:
    for text in disclaimer_slide.ALL_TEXT:
        assert disclaimer_slide.unsupported_chars(text) == []
    assert disclaimer_slide.unsupported_chars("⚠ 경고 ☒") == ["⚠", "☒"]
    assert disclaimer_slide.LINES[0].startswith(disclaimer_slide.DISCLAIMER)


@pytest.mark.skipif(not FONT.is_file(), reason="NotoSansCJK not installed")
def test_disclaimer_render(tmp_path) -> None:
    out = disclaimer_slide.render(tmp_path / "S8.png", FONT)
    with Image.open(out) as img:
        assert img.size == (1080, 1350)
        assert img.convert("RGB").getpixel((5, 5)) == disclaimer_slide.BG


def test_disclaimer_render_refuses_unsafe_glyphs(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(disclaimer_slide, "ALL_TEXT", ("⚠ 주의",))
    with pytest.raises(ValueError, match="font-safe"):
        disclaimer_slide.render(tmp_path / "S8.png", FONT)


def test_assembly_replaces_last_slide_and_hashes_it(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    seen = []

    def fake_disclaimer(path):
        seen.append(path)
        Image.new("RGB", (1080, 1350), (1, 2, 3)).save(path)
        return path

    store = FakeStore()
    p1 = P1Deps(feed=FakeFeed([main_row("2026-10-06")], fingerprints=("a" * 64,)), store=store,
                llm=FakeLLM([raw_script()]), prompts=FakePrompts(), images=FakeImages(),
                composer=FakeComposer(), characters=make_refs(tmp_path),
                output_root=tmp_path / "output/sidestory", ref_root=tmp_path,
                inspector=FakeInspector(), disclaimer=fake_disclaimer)
    assert run_p1(TUE, p1)[-1].status == "assembled"
    assert [p.name for p in seen] == ["S8.png"]
    r = store.get_episode(SID)
    s8 = next(s for s in r["slides_json"] if s["name"] == "S8.png")
    from sidestory.app.p1 import sha256_file
    assert r["manifest_json"]["slides"]["S8.png"] == sha256_file(Path(s8["path"])) == s8["sha256"]


def test_assembly_holds_when_disclaimer_fails(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    def broken(path):
        raise OSError("font missing")

    p1 = P1Deps(feed=FakeFeed([main_row("2026-10-06")], fingerprints=("a" * 64,)),
                store=FakeStore(), llm=FakeLLM([raw_script()]), prompts=FakePrompts(),
                images=FakeImages(), composer=FakeComposer(), characters=make_refs(tmp_path),
                output_root=tmp_path / "output/sidestory", ref_root=tmp_path,
                inspector=FakeInspector(), disclaimer=broken)
    res = run_p1(TUE, p1)
    assert res[-1].status == "hold" and "disclaimer" in res[-1].detail["reason"]


# ── CLI ──────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("argv,env_dry", [
    (["--stage", "publish", "--live"], "true"),       # live needs DRY_RUN=false
    (["--stage", "p1", "--live"], "false"),           # live only for publish
])
def test_cli_live_usage_errors(monkeypatch, capsys, argv, env_dry) -> None:
    from sidestory import __main__ as cli

    monkeypatch.setenv("SUPABASE_SCHEMA", "icg_side")
    monkeypatch.setenv("DRY_RUN", env_dry)
    assert cli.main(argv) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "usage_error"
