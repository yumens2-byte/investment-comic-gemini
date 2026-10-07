from datetime import timedelta

from sidestory.market_talk.content import Draft, digest, validate
from sidestory.market_talk.publishing import ControlledPublisher
from sidestory.market_talk.service import publish
from sidestory.tests.market_talk.test_content_and_delivery import NOW, Provider, Store, sample


def compact(draft):
    return draft.model_copy(
        update={"context": draft.context.model_copy(update={"policy_version": "market-talk-2"})}
    )


def test_public_copy_contains_only_commentary_and_named_dialogue():
    original = sample()
    draft = compact(original)
    assert draft.body == original.text.commentary + "\n\nEDT : “" + original.text.dialogue + "”"
    assert draft.context.evidence == original.context.evidence
    assert draft.context.provenance_note == original.context.provenance_note
    assert draft.revision != original.revision
    assert draft.semantic_key == original.semantic_key


def test_legacy_payload_body_and_revision_remain_unchanged():
    original = sample()
    payload = original.model_dump(mode="json")
    restored = Draft.model_validate(payload)
    assert restored.body == original.body
    assert restored.revision == digest(payload)
    assert "기준 " in restored.body and "창작 대사" in restored.body


def test_compact_copy_does_not_bypass_freshness_canon_or_duplicate_checks():
    draft = compact(sample())
    assert "expired" in validate(
        draft,
        now=NOW + timedelta(days=1),
        current_canon="b" * 64,
        current_snapshot="a" * 64,
        recent=[],
    )
    assert "canon_changed" in validate(
        draft, now=NOW, current_canon="c" * 64, current_snapshot="a" * 64, recent=[]
    )
    assert "duplicate_content" in validate(
        draft,
        now=NOW,
        current_canon="b" * 64,
        current_snapshot="a" * 64,
        recent=[{"semantic_key": sample().semantic_key}],
    )


def test_pilot_publisher_receives_exact_public_copy_once():
    draft = compact(sample())
    store = Store(draft)

    class CaptureProvider(Provider):
        def create_post(self, message, photos):
            assert message == draft.body
            assert photos == []
            self.message = message
            return super().create_post(message, photos)

    provider = CaptureProvider()
    publisher = ControlledPublisher(provider, store, "123", draft.revision, "talk")
    args = dict(now=NOW, canon_hash="b" * 64, snapshot_hash="a" * 64)
    publish(draft.revision, store, publisher, **args)
    publish(draft.revision, store, publisher, **args)
    assert provider.calls == 1
    assert provider.message == draft.body
