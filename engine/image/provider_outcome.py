"""Versioned settlement receipts separate content review from uncertain billing."""
from __future__ import annotations

import math
import os
from dataclasses import dataclass

from engine.image.generation_guard import GenerationHold


def outcome_v3_enabled() -> bool:
    value = os.environ.get("ICG_IMAGE_OUTCOME_V3_ENABLED", "false").lower()
    if value not in {"true", "false"}:
        raise GenerationHold("Invalid outcome feature flag")
    return value == "true"


@dataclass(frozen=True)
class SettlementReceipt:
    result_code: str
    state: str
    cost_usd: float | None
    hold_code: str | None

    @classmethod
    def parse(cls, value: dict):
        if (value.get("settled") is not True
                or value.get("state") not in {"success", "failed", "terminal", "unknown"}
                or value.get("result_code") not in {"IMAGE_SUCCESS", "INVALID_IMAGE",
                    "CONTENT_REVIEW_REQUIRED", "PROVIDER_TERMINAL", "PROVIDER_OUTCOME_UNKNOWN"}
                or value.get("retry_allowed") is not False):
            raise GenerationHold("Settlement not confirmed")
        receipt = cls(value["result_code"], value["state"], value.get("cost_usd"),
                      value.get("hold_code"))
        expected = {"IMAGE_SUCCESS": "success", "INVALID_IMAGE": "failed",
                    "CONTENT_REVIEW_REQUIRED": "terminal", "PROVIDER_TERMINAL": "terminal",
                    "PROVIDER_OUTCOME_UNKNOWN": "unknown"}
        if receipt.state != expected[receipt.result_code] or (
                receipt.cost_usd is not None and (type(receipt.cost_usd) not in (int, float)
                    or not math.isfinite(receipt.cost_usd) or receipt.cost_usd < 0)):
            raise GenerationHold("Invalid settlement receipt")
        if receipt.state != "unknown" and receipt.cost_usd is None:
            raise GenerationHold("Settlement usage missing")
        if receipt.hold_code and receipt.hold_code != "CONTENT_REVIEW_REQUIRED":
            raise GenerationHold(receipt.hold_code)
        return receipt


def content_isolation_v4_enabled() -> bool:
    """Explicit rollout; missing DB capability must never fall back to legacy calls."""
    value = os.environ.get("ICG_IMAGE_CONTENT_ISOLATION_V4_ENABLED", "false").lower()
    if value not in {"true", "false"}:
        raise GenerationHold("Invalid content isolation feature flag")
    if value == "true" and not outcome_v3_enabled():
        raise GenerationHold("Content isolation requires outcome v3")
    return value == "true"
