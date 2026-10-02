"""Evidence, claims, dramatic beats, and human review contracts.

These validators validate declared evidence, not the truth of a provider or a
human's judgement. Missing provenance or review is never treated as approval.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from engine.quality.policy import advisory_qc


class QualityHold(ValueError):
    """A required condition is failed or unverified; publication must stop."""


def digest(value: object) -> str:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    encoded = json.dumps(
        value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class Evidence(StrictModel):
    evidence_id: str = Field(min_length=1)
    metric: str = Field(min_length=1)
    value: Decimal
    change: Decimal | None = None
    unit: str = Field(min_length=1)
    semantic_type: Literal["price", "rate", "spread", "index", "event"]
    instrument: str = Field(min_length=1)
    price_basis: str = Field(min_length=1)
    source: str = Field(min_length=1)
    observed_at: datetime
    trading_date: date
    fallback: bool = False
    confidence: float = Field(ge=0, le=1)
    causal_support: bool = False

    @model_validator(mode="after")
    def validate_time(self):
        if self.observed_at.tzinfo is None:
            raise ValueError("observed_at must include a timezone")
        if not self.value.is_finite() or (self.change is not None and not self.change.is_finite()):
            raise ValueError("non-finite evidence")
        return self


class EvidenceBundle(StrictModel):
    version: Literal["evidence-1"] = "evidence-1"
    requested_date: date
    resolved_trading_date: date
    calendar_policy: str = Field(min_length=1)
    resolution_reason: str = ""
    collected_at: datetime
    synthetic: bool = False
    evidence: tuple[Evidence, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_provenance(self):
        if self.collected_at.tzinfo is None:
            raise ValueError("collected_at must include a timezone")
        if self.resolved_trading_date > self.requested_date:
            raise ValueError("resolved trading date cannot be in the future")
        if self.requested_date != self.resolved_trading_date and not self.resolution_reason.strip():
            raise ValueError("calendar resolution reason required")
        ids = [e.evidence_id for e in self.evidence]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate evidence IDs")
        for e in self.evidence:
            if e.trading_date != self.resolved_trading_date:
                raise ValueError(f"trading day mismatch: {e.evidence_id}")
            if e.observed_at > self.collected_at:
                raise ValueError("observation after collection")
        return self


class MetricScale(StrictModel):
    metric: str
    unit: str
    price_basis: str
    reference_scale: Decimal = Field(gt=0)
    valid_as_of: date
    policy_version: str = Field(min_length=1)


def rank_evidence(bundle: EvidenceBundle, scales: list[MetricScale], limit: int = 3) -> list[dict]:
    if not 1 <= limit <= 3:
        raise QualityHold("visible evidence limit must be 1..3")
    by_metric = {s.metric: s for s in scales}
    if len(by_metric) != len(scales):
        raise QualityHold("duplicate metric scales")
    ranked = []
    for e in bundle.evidence:
        scale = by_metric.get(e.metric)
        if scale is None or scale.unit != e.unit or scale.price_basis != e.price_basis:
            raise QualityHold(f"approved matching scale missing: {e.metric}")
        if scale.valid_as_of > bundle.resolved_trading_date:
            raise QualityHold("scale contains future information")
        if e.change is None:
            raise QualityHold(f"change missing: {e.metric}")
        score = float(abs(e.change) / scale.reference_scale) * e.confidence
        if not math.isfinite(score):
            raise QualityHold("invalid normalized score")
        ranked.append(
            {
                "evidence_id": e.evidence_id,
                "score": score,
                "reason": f"abs(change)/{scale.reference_scale} * confidence",
                "policy_version": scale.policy_version,
            }
        )
    return sorted(ranked, key=lambda r: (-r["score"], r["evidence_id"]))[:limit]


class Claim(StrictModel):
    claim_id: str = Field(min_length=1)
    panel_idx: int = Field(ge=1, le=8)
    field: Literal["key_text", "narration", "market_ref"]
    text: str = Field(min_length=1)
    kind: Literal["fact", "interpretation", "metaphor", "causal", "forecast"]
    evidence_ids: tuple[str, ...] = ()
    quoted_value: Decimal | None = None
    quoted_unit: str | None = None
    quoted_basis: str | None = None
    asserted: bool = False


@advisory_qc("claim_evidence")
def validate_claims(bundle: EvidenceBundle, claims: list[Claim], panels: list[dict]) -> None:
    evidence = {e.evidence_id: e for e in bundle.evidence}
    panels_by_idx = {p["idx"]: p for p in panels}
    if len({c.claim_id for c in claims}) != len(claims):
        raise QualityHold("duplicate claim IDs")
    # Coverage is deliberately structural: every displayed non-empty field is
    # classified. A human factuality review remains required for prose meaning.
    for p in panels:
        for field in ("key_text", "narration", "market_ref"):
            text = p.get(field) or ""
            if text and not any(
                c.panel_idx == p["idx"] and c.field == field and c.text == text for c in claims
            ):
                raise QualityHold(f"unclassified text: panel {p['idx']}.{field}")
    for claim in claims:
        p = panels_by_idx.get(claim.panel_idx)
        if p is None or p.get(claim.field) != claim.text:
            raise QualityHold("claim text does not match rendered script")
        if any(i not in evidence for i in claim.evidence_ids):
            raise QualityHold("unknown claim evidence")
        if claim.kind in {"fact", "causal"} and not claim.evidence_ids:
            raise QualityHold("factual or causal claim needs evidence")
        if claim.kind == "forecast" and claim.asserted:
            raise QualityHold("asserted market forecast prohibited")
        if (
            claim.kind == "causal"
            and claim.asserted
            and not all(evidence[i].causal_support for i in claim.evidence_ids)
        ):
            raise QualityHold("co-movement is not causal evidence")
        if (
            re.search(r"\d", claim.text)
            and claim.kind in {"fact", "causal"}
            and claim.quoted_value is None
        ):
            raise QualityHold("numeric fact needs an exact structured quote")
        if claim.quoted_value is not None:
            if len(claim.evidence_ids) != 1:
                raise QualityHold("numeric quote requires one unambiguous evidence")
            e = evidence[claim.evidence_ids[0]]
            if (claim.quoted_value, claim.quoted_unit, claim.quoted_basis) != (
                e.value,
                e.unit,
                e.price_basis,
            ):
                raise QualityHold("quoted value/unit/instrument basis mismatch")
        if re.search(r"\d", claim.text) and claim.kind in {"metaphor", "interpretation"}:
            raise QualityHold("numeric prose must be classified as sourced fact")


class DramaticBeat(StrictModel):
    panel_idx: int = Field(ge=1, le=7)
    goal: str = Field(min_length=1)
    action: str = Field(min_length=1)
    resistance: str = Field(min_length=1)
    cost: str = Field(min_length=1)
    visible_state_change: str = Field(min_length=1)
    causal_from_panel: int | None = Field(default=None, ge=1, le=7)
    evidence_ids: tuple[str, ...] = ()
    required_cast: tuple[str, ...] = Field(min_length=1)


class ThreadPayoff(StrictModel):
    thread_id: str = Field(min_length=1)
    panel_idx: int | None = Field(default=None, ge=1, le=7)
    visible_result: str = ""
    deferred_reason: str = ""
    new_due_date: date | None = None

    @model_validator(mode="after")
    def validate_resolution(self):
        payoff = self.panel_idx is not None and bool(self.visible_result.strip())
        deferred = bool(self.deferred_reason.strip()) and self.new_due_date is not None
        if payoff == deferred:
            raise ValueError("thread requires either visible payoff or documented deferral")
        return self


class EditorialPlan(StrictModel):
    thesis: str = Field(min_length=1)
    top_evidence_ids: tuple[str, ...] = Field(min_length=1, max_length=3)
    beats: tuple[DramaticBeat, ...] = Field(min_length=7, max_length=7)
    due_threads: tuple[str, ...] = ()
    payoffs: tuple[ThreadPayoff, ...] = ()
    new_threads: tuple[str, ...] = Field(max_length=1, default=())

    @model_validator(mode="after")
    def validate_causality(self):
        if [b.panel_idx for b in self.beats] != list(range(1, 8)):
            raise ValueError("dramatic beats must be 1..7 in sequence")
        for b in self.beats:
            if b.causal_from_panel is not None and b.causal_from_panel >= b.panel_idx:
                raise ValueError("causal link must point to an earlier panel")
            if not b.evidence_ids and b.causal_from_panel is None:
                raise ValueError("state change needs evidence or an earlier action")
        if len({p.thread_id for p in self.payoffs}) != len(self.payoffs):
            raise ValueError("duplicate thread payoff")
        if set(self.due_threads) != {p.thread_id for p in self.payoffs}:
            raise ValueError("due thread coverage mismatch")
        return self


@advisory_qc("editorial_plan")
def validate_plan(
    plan: EditorialPlan, bundle: EvidenceBundle, script: dict, calculation: dict
) -> None:
    panels = script.get("panels") or []
    if [p.get("idx") for p in panels] != list(range(1, 9)):
        raise QualityHold("quality track requires exactly 8 ordered slides")
    if panels[-1].get("panel_type") != "DISCLAIMER":
        raise QualityHold("slide 8 must be disclaimer")
    known = {e.evidence_id for e in bundle.evidence}
    for evidence_id in (*plan.top_evidence_ids, *(i for b in plan.beats for i in b.evidence_ids)):
        if evidence_id not in known:
            raise QualityHold("unknown editorial evidence")
    for payoff in plan.payoffs:
        if (
            payoff.deferred_reason.strip()
            and payoff.new_due_date is not None
            and payoff.new_due_date <= bundle.resolved_trading_date
        ):
            raise QualityHold("deferred thread deadline must follow the episode trading date")
    for beat, panel in zip(plan.beats, panels[:7]):
        cast = {c["char_id"] for c in panel.get("characters", [])}
        if not set(beat.required_cast) <= cast:
            raise QualityHold("required dramatic cast missing")
    if script.get("fixed_outcome") != calculation.get("outcome"):
        raise QualityHold("script changed deterministic outcome")
    if calculation.get("outcome") == "PEACEFUL_GROWTH" and any(
        p.get("panel_type") in {"BATTLE", "CLIMAX"} for p in panels
    ):
        raise QualityHold("NO_BATTLE cannot contain battle panels")
