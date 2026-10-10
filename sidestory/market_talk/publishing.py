"""Page-wide durable gate shared by text and the existing eight-slide publisher."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sidestory.market_talk.diagnostics import DeliveryError, failure_report
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
        page = self.publisher.check()
        # Read-only preflight runs before Sidestory uploads any photos. It does
        # not reserve delivery or replace the atomic gate at send time.
        self._history()
        self._gate_call("page_gate_contract", self.store.require_hardening)
        return page

    def _gate_call(self, phase, fn, *args):
        try:
            return fn(*args)
        except Exception as exc:
            report = failure_report(exc, phase)
            code = report["blockers"][0]
            if code == "UNEXPECTED_FAILURE":
                code = "PAGE_HISTORY_UNAVAILABLE" if phase == "page_history" else "PAGE_GATE_UNAVAILABLE"
            # Never expose raw provider/DB messages, URLs, or access tokens.
            raise DeliveryError(f"{phase}:{code}", phase=phase) from None

    def _history(self):
        since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        return self._gate_call("page_history", self.publisher.recent_receipts, since)

    def upload_photo(self, path):
        return self.publisher.upload_photo(path)

    def find_recent_post(self, message, limit=10):
        # Page search is only a hint; absence is never proof of non-publication.
        return self.publisher.find_recent_post(message, limit)

    def get_post(self, post_id):
        return self.publisher.get_post(post_id)

    def create_post(self, message, photo_ids):
        receipts = self._history()
        self._gate_call("page_gate_observe", self.store.observe, self.page_id, receipts)
        claim = self._gate_call(
            "page_gate_begin", self.store.begin,
            self.page_id, self.key, self.track, message, self.expires_at,
        )
        if claim["status"] == "PUBLISHED":
            return claim["post_id"]
        if claim["status"] != "SENDING":
            code = (
                claim["status"]
                if claim["status"]
                in {
                    "UNKNOWN",
                    "CHANNEL_HOLD",
                    "OBSERVATION_REQUIRED",
                    "EXPIRED",
                    "PAGE_LIMIT",
                    "TALK_LIMIT",
                    "REJECTED",
                    "APPROVAL_OR_TIME_REQUIRED",
                }
                else "UNEXPECTED_GATE_RESULT"
            )
            raise DeliveryError(code, ambiguous=claim["status"] == "UNKNOWN", phase="page_gate")
        token = claim["token"]
        try:
            post_id = self.publisher.create_post(message, photo_ids)
        except PublishError as exc:
            state = "UNKNOWN" if exc.ambiguous else "REJECTED"
            # If this fails, the durable SENDING reservation still blocks the entire Page.
            try:
                self.store.finish(self.page_id, self.key, token, state, reason=state)
            except Exception:
                raise DeliveryError("DELIVERY_PERSISTENCE_FAILED", ambiguous=True) from None
            raise DeliveryError(
                "META_RESULT_UNKNOWN" if exc.ambiguous else "META_REQUEST_REJECTED",
                ambiguous=exc.ambiguous,
            ) from None
        except Exception:
            try:
                self.store.finish(
                    self.page_id, self.key, token, "UNKNOWN", reason="unexpected_provider_error"
                )
            finally:
                raise DeliveryError("META_RESULT_UNKNOWN", ambiguous=True) from None
        if not post_id:
            self.store.finish(self.page_id, self.key, token, "UNKNOWN", reason="missing_post_id")
            raise DeliveryError("META_RECEIPT_MISSING", ambiguous=True)
        try:
            self.store.finish(self.page_id, self.key, token, "PUBLISHED", post_id=str(post_id))
        except Exception:
            raise DeliveryError("DELIVERY_PERSISTENCE_FAILED", ambiguous=True) from None
        return str(post_id)
