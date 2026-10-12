"""Additive Market Talk contract; shared Sidestory v3 remains unchanged."""

from sidestory.market_talk.policy import PolicyError
from sidestory.market_talk.store import TalkStore


class TalkStoreV4(TalkStore):
    def rpc(self, name, **params):
        names = {
            "facebook_begin": "talk_begin_v4",
            "facebook_finish": "talk_finish_v4",
            "facebook_set_hold": "talk_set_hold_v4",
            "facebook_resolve": "talk_resolve_v4",
            "talk_record_outcome": "talk_record_outcome_v4",
            "talk_hold": "talk_hold_v4",
            "talk_cost_reserve": "talk_cost_reserve_v4",
        }
        return super().rpc(names.get(name, name), **params)

    def require_hardening(self):
        if self.rpc("talk_contract_version_v4") != 4:
            raise PolicyError("DB_CONTRACT_MISMATCH", "db_contract")

    def optional_policy(self, page_id):
        rows = self.db.table("talk_policy").select("*").eq("page_id", page_id).execute().data
        if not isinstance(rows, list) or len(rows) > 1:
            raise PolicyError("TALK_POLICY_UNAVAILABLE", "policy")
        if not rows:
            return None
        policy = dict(rows[0])
        # Budget values remain owned by the original cost ledger policy.
        budgets = super().optional_policy(page_id) or {}
        for key in ("daily_budget_usd", "monthly_budget_usd"):
            policy[key] = budgets.get(key, 0)
        return policy

    def ensure_schedule(self, page, day, due):
        return self.rpc(
            "talk_schedule_ensure", p_page=page, p_day=day.isoformat(), p_due=due.isoformat()
        )

    def preflight(self, page, day):
        return self.rpc("talk_preflight_v4", p_page=page, p_day=day.isoformat())

    def get_slot(self, page, day):
        rows = (
            self.db.table("talk_slots")
            .select("*")
            .eq("page_id", page)
            .eq("slot_date", day)
            .execute()
            .data
        )
        if not isinstance(rows, list) or len(rows) > 1:
            raise PolicyError("SLOT_UNAVAILABLE", "slot")
        return rows[0] if rows else None
