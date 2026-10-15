"""Opt-in v5 worker: every paid/send admission requires a durable execution lease."""
from sidestory.market_talk.content import digest
from sidestory.market_talk.policy import PolicyError
from sidestory.market_talk.store import TalkStore
from sidestory.market_talk.store_v4 import TalkStoreV4


class TalkStoreV5(TalkStoreV4):
    context_version = "market-talk-5"

    def __init__(self, client, *, owner=None, mode="normal"):
        super().__init__(client)
        self.owner, self.mode = owner, mode

    def require_hardening(self):
        if self.rpc("talk_contract_version_v5") != 5:
            raise PolicyError("DB_CONTRACT_MISMATCH", "db_contract")

    def snapshot(self, page, day):
        return self.rpc("talk_snapshot_v5", p_page=page, p_day=day.isoformat())

    def ensure_schedule(self, page, day, due):
        return self.rpc("talk_schedule_ensure_v5", p_page=page,
                        p_day=day.isoformat(), p_due=due.isoformat())

    def preflight(self, page, day):
        return self.rpc("talk_preflight_v5", p_page=page, p_day=day.isoformat(),
                        p_mode=self.mode, p_owner=self.owner)

    def claim(self, page, day, run):
        return self.rpc("talk_execution_claim_v5", p_page=page, p_day=day.isoformat(),
                        p_mode=self.mode, p_owner=self.owner, p_run=run)

    def complete(self, page, day, report, retryable=False):
        reason = (report.get("blockers") or report.get("errors")
                  or [report["status"]])[0].upper()
        # Only safe diagnostic enums cross the RPC boundary.
        if not reason.replace("_", "").isalnum() or len(reason) > 100:
            reason = "UNEXPECTED_FAILURE"
        return self.rpc("talk_execution_finish_v5", p_page=page, p_day=day.isoformat(),
                        p_owner=self.owner, p_status=report["status"],
                        p_reason=reason, p_retryable=retryable)

    def begin(self, page_id, key, track, body, expires_at):
        return self.rpc("talk_begin_v5", p_page=page_id, p_key=key, p_track=track,
                        p_body_hash=digest(body), p_expires=expires_at,
                        p_owner=self.owner, p_mode=self.mode)

    def cost_reserve(self, page_id, key, amount):
        return self.rpc("talk_cost_reserve_v5", p_page=page_id, p_key=key,
                        p_amount=str(amount), p_owner=self.owner, p_mode=self.mode)

    def record_outcome(self, page, day, run, stage, report):
        # v4 event persistence accepts v5 saved slots and preserves their deadlines.
        return TalkStore.record_outcome(self, page, day, run, stage, report)
