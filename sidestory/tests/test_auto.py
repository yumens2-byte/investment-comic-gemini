"""Real stage integration with offline external providers."""
from datetime import date

import pytest

from sidestory.app.automation import run_auto
from sidestory.app.p1 import P1Deps
from sidestory.app.publish import PublishDeps
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


def test_missing_slide_refuses_upload(deps):
    from pathlib import Path

    p, pub = deps
    pub.live = False
    run_auto(DAY, p, pub)
    Path(p.store.get_episode(SID)['slides_json'][0]['path']).unlink()
    pub.live = True
    assert run_auto(DAY, p, pub)[-1].status == 'error'
    assert pub.publisher.uploads == []


def test_publication_store_failure_reconciles(deps):
    p, pub = deps
    original = p.store.insert_publication
    p.store.insert_publication = lambda _: (_ for _ in ()).throw(RuntimeError('DB unavailable'))
    assert run_auto(DAY, p, pub)[-1].status == 'error'
    assert p.store.get_episode(SID)['status'] == 'publishing'
    p.store.insert_publication = original
    pub.publisher.found = '123_999'
    assert run_auto(DAY, p, pub)[-1].ok
    assert len(pub.publisher.posts) == 1


def test_mismatched_store_refused(deps):
    p, pub = deps
    pub.store = FakeStore()
    with pytest.raises(ValueError, match='same feed and store'):
        run_auto(DAY, p, pub)
    assert p.llm.calls == [] and pub.publisher.posts == []


@pytest.mark.parametrize('argv,dry', [
    (['--stage', 'auto', '--no-persist'], 'true'),
    (['--stage', 'auto', '--live'], 'true'),
])
def test_auto_cli_invalid_flags(monkeypatch, capsys, argv, dry):
    from sidestory import __main__ as cli

    monkeypatch.setenv('SUPABASE_SCHEMA', 'icg_side')
    monkeypatch.setenv('DRY_RUN', dry)
    assert cli.main(argv) == 2
    assert 'usage_error' in capsys.readouterr().out
