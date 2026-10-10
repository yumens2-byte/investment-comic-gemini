"""Real stage integration with offline external providers."""
from datetime import date

import pytest

from sidestory.app.automation import run_auto
from sidestory.app.p1 import P1Deps
from sidestory.app.publish import PublishDeps
from sidestory.ports.publisher import PublishError
from sidestory.tests.fixtures import FakeFeed, FakeStore, main_row
from sidestory.tests.p1_fixtures import (FakeComposer, FakeImages, FakeInspector,
                                       FakeLLM, FakePrompts, make_refs, raw_script)
from sidestory.tests.test_p2_publish import FakePublisher

DAY = date(2026, 10, 6)
SID = 'SIDE-2026-10-06-01'


@pytest.fixture
def deps(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    feed = FakeFeed([main_row(DAY.isoformat())], fingerprints=('a' * 64,))
    store = FakeStore()
    production = P1Deps(feed=feed, store=store, llm=FakeLLM([raw_script()]),
                        prompts=FakePrompts(), images=FakeImages(), composer=FakeComposer(),
                        characters=make_refs(tmp_path), output_root=tmp_path / 'output/sidestory',
                        ref_root=tmp_path, inspector=FakeInspector())
    return production, PublishDeps(feed, store, FakePublisher(), live=True)


def test_full_pipeline_and_duplicate_prevention(deps):
    p, pub = deps
    results = run_auto(DAY, p, pub)
    assert [r.stage for r in results] == ['echo', 'narrative', 'image', 'assembly', 'publish', 'verify']
    assert all(r.ok for r in results)
    assert len(pub.publisher.uploads) == 8 and len(pub.publisher.posts) == 1
    calls = len(p.images.calls)
    assert run_auto(DAY, p, pub)[-1].detail['post']['id'] == '123_999'
    assert len(p.images.calls) == calls and len(pub.publisher.posts) == 1


def test_dry_run_without_facebook(deps):
    p, pub = deps
    pub.live = False
    pub.publisher = None
    results = run_auto(DAY, p, pub)
    assert results[-1].detail['dry_run'] is True
    assert p.store.get_episode(SID)['status'] == 'assembled'
    assert p.store.live_publication(SID, 'facebook') is None


def test_production_failure_never_publishes(deps):
    p, pub = deps
    p.images.hold_on = 1
    assert run_auto(DAY, p, pub)[-1].status == 'hold'
    assert pub.publisher.uploads == []


def test_safe_hold_requires_explicit_retry(deps):
    p, pub = deps
    pub.publisher.fail_upload_at = 3
    assert run_auto(DAY, p, pub)[-1].status == 'hold'
    calls = len(p.images.calls)
    assert run_auto(DAY, p, pub)[-1].status == 'hold'
    assert run_auto(DAY, p, pub, retry_hold=True)[-1].ok
    assert len(p.images.calls) == calls and len(pub.publisher.posts) == 1


def test_ambiguous_delivery_does_not_repost(deps):
    p, pub = deps
    pub.publisher.fail_post = PublishError('timeout', ambiguous=True)
    assert run_auto(DAY, p, pub)[-1].status == 'hold'
    uploads = len(pub.publisher.uploads)
    assert run_auto(DAY, p, pub, retry_hold=True)[-1].status == 'hold'
    assert len(pub.publisher.uploads) == uploads and pub.publisher.posts == []
    pub.publisher.found = '123_777'
    assert run_auto(DAY, p, pub, retry_hold=True)[-1].detail['post']['id'] == '123_777'
    assert len(pub.publisher.uploads) == uploads


def test_non_slot_skips_publish(deps):
    p, pub = deps
    results = run_auto(date(2026, 10, 7), p, pub)
    assert results[-1].status == 'skipped' and pub.publisher.uploads == []


def test_verification_failure_retry_only_reads(deps):
    p, pub = deps
    original = pub.publisher.get_post
    pub.publisher.get_post = lambda _: (_ for _ in ()).throw(PublishError('read failed'))
    assert run_auto(DAY, p, pub)[-1].status == 'error'
    pub.publisher.get_post = original
    assert run_auto(DAY, p, pub)[-1].ok
    assert len(pub.publisher.posts) == 1
