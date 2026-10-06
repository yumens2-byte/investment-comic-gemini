"""Page-wide durable gate shared by text and the existing eight-slide publisher."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sidestory.ports.publisher import PublishError


class ControlledPublisher:
    channel = "facebook"

    def __init__(self, publisher, store, page_id, key, track, expires_at=None):
        self.publisher, self.store = publisher, store
        self.page_id, self.key, self.track = page_id, key, track
        self.expires_at = (
            expires_at or (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        )

    def check(self):
        return self.publisher.check()

    def upload_photo(self, path):
        return self.publisher.upload_photo(path)

    def find_recent_post(self, message, limit=10):
        # Page search is only a hint; absence is never proof of non-publication.
        return self.publisher.find_recent_post(message, limit)

    def get_post(self, post_id):
        return self.publisher.get_post(post_id)

    def create_post(self, message, photo_ids):
        try:
            since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
            self.store.observe(self.page_id, self.publisher.recent_receipts(since))
            claim = self.store.begin(self.page_id, self.key, self.track, message, self.expires_at)
        except Exception as exc:
            raise PublishError("Page gate unavailable; no post attempted") from exc
        if claim["status"] == "PUBLISHED":
            return claim["post_id"]
        if claim["status"] != "SENDING":
            raise PublishError(
                "Page gate blocked: " + claim["status"], ambiguous=claim["status"] == "UNKNOWN"
            )
        token = claim["token"]
        try:
            post_id = self.publisher.create_post(message, photo_ids)
        except PublishError as exc:
            state = "UNKNOWN" if exc.ambiguous else "REJECTED"
            # If this fails, the durable SENDING reservation still blocks the entire Page.
            try:
                self.store.finish(self.page_id, self.key, token, state, reason=state)
            except Exception:
                raise PublishError(
                    "Result persistence failed; reconcile before retry", ambiguous=True
                ) from None
            raise
        except Exception:
            try:
                self.store.finish(
                    self.page_id, self.key, token, "UNKNOWN", reason="unexpected_provider_error"
                )
            finally:
                raise PublishError(
                    "Uncertain provider result; reconcile before retry", ambiguous=True
                ) from None
        if not post_id:
            self.store.finish(self.page_id, self.key, token, "UNKNOWN", reason="missing_post_id")
            raise PublishError("Missing receipt; reconcile before retry", ambiguous=True)
        try:
            self.store.finish(self.page_id, self.key, token, "PUBLISHED", post_id=str(post_id))
        except Exception:
            raise PublishError(
                "Posted but receipt persistence failed; reconcile before retry", ambiguous=True
            ) from None
        return str(post_id)
