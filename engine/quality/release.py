"""Hash-bound QC and release authorization. No score can override a hard gate."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import Field

from engine.quality.canon import file_hash, safe_asset
from engine.quality.contracts import QualityHold, StrictModel, digest

RUBRIC = {
    "facts": ("trading_day", "provenance", "numbers", "claim_evidence", "fact_metaphor"),
    "canon": ("appearance", "props_hands", "direction_duplicates", "approved_refs", "continuity"),
    "story": ("goal_hook", "causality_cost", "turn_outcome", "thread_payoff"),
    "art": ("action_contact", "axis_gaze", "staging_mechanics", "visual_variation"),
    "mobile": ("text_readability", "protected_regions"),
}
FLOORS = {"facts": 20, "canon": 20, "story": 14, "art": 14, "mobile": 7}
ROLES = frozenset(
    {"market", "editor", "writer", "canon", "art", "ux", "architect", "sre", "qa", "product"}
)
REQUIRED_CHECKS = frozenset(
    {"facts", "calculation", "canon", "actual_images", "mobile_render", "budget", "publishing"}
)


class ReviewItem(StrictModel):
    domain: str
    criterion: str
    score: int = Field(ge=0, le=5)
    evidence: str = Field(min_length=1)
    panel_idx: int | None = Field(default=None, ge=1, le=8)


class RoleReview(StrictModel):
    role: str
    reviewer_id: str = Field(min_length=1)
    method: Literal["human", "model", "deterministic"]
    reviewed_at: datetime
    evidence: str = Field(min_length=1)
    verdict: Literal["pass", "fail", "unverified"]


class QualityReport(StrictModel):
    rubric_version: Literal["webtoon-qc-1"] = "webtoon-qc-1"
    content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    items: tuple[ReviewItem, ...]
    roles: tuple[RoleReview, ...]
    checks: dict[str, Literal["pass", "fail", "unverified"]]
    critical_findings: tuple[str, ...] = ()
    major_findings: tuple[str, ...] = ()

    def approve(self, now: datetime | None = None) -> int:
        now = now or datetime.now(timezone.utc)
        if self.critical_findings or self.major_findings:
            raise QualityHold("blocking QC findings")
        if set(self.checks) != REQUIRED_CHECKS or any(v != "pass" for v in self.checks.values()):
            raise QualityHold("failed or unverified required checks")
        expected = {(domain, item) for domain, items in RUBRIC.items() for item in items}
        actual = [(i.domain, i.criterion) for i in self.items]
        if set(actual) != expected or len(actual) != len(expected):
            raise QualityHold("rubric coverage missing or duplicated")
        for domain, floor in FLOORS.items():
            if sum(i.score for i in self.items if i.domain == domain) < floor:
                raise QualityHold(f"domain below floor: {domain}")
        if {r.role for r in self.roles} != ROLES or len(self.roles) != len(ROLES):
            raise QualityHold("ten role reviews required")
        for r in self.roles:
            if r.verdict != "pass" or r.reviewed_at.tzinfo is None or r.reviewed_at > now:
                raise QualityHold("invalid role review")
            if r.role in {"market", "editor", "writer", "canon", "art", "ux", "qa"}:
                if r.method != "human":
                    raise QualityHold(
                        "actual content needs human inspection; model score is insufficient"
                    )
        score = sum(i.score for i in self.items)
        if score < 80:
            raise QualityHold("overall score below 80")
        return score


class ReleaseManifest(StrictModel):
    schema_version: Literal["webtoon-release-1"] = "webtoon-release-1"
    episode_id: str = Field(pattern=r"^ICG-\d{4}-\d{2}-\d{2}-\d{3}$")
    release_version: int = Field(ge=1)
    synthetic: bool
    input_hashes: dict[str, str]
    artifacts: dict[str, str]
    required_channels: tuple[Literal["x", "telegram"], ...] = Field(min_length=1)
    quality_report_hash: str
    approved_by: str = Field(min_length=1)
    approved_at: datetime
    content_hash: str

    def verify(
        self, root: Path, inputs: dict, report: QualityReport, *, live: bool = False
    ) -> None:
        validate_release_inputs(inputs, root)
        if bool(inputs.get("evidence", {}).get("synthetic")) != self.synthetic:
            raise QualityHold("release synthetic provenance mismatch")
        if live and self.synthetic:
            raise QualityHold("synthetic fixtures must never be published")
        if self.approved_at.tzinfo is None or self.approved_at > datetime.now(timezone.utc):
            raise QualityHold("invalid approval time")
        if len(set(self.required_channels)) != len(self.required_channels):
            raise QualityHold("duplicate required channels")
        hashes = {k: digest(v) for k, v in inputs.items()}
        if hashes != self.input_hashes:
            raise QualityHold("release inputs changed")
        if self.quality_report_hash != digest(report):
            raise QualityHold("quality report changed")
        report.approve()
        required_slides = {f"slides/P{i}.png" for i in range(1, 9)}
        required_previews = {
            f"slides/P{i}-preview-{w}.png" for i in range(1, 9) for w in (360, 390)
        }
        if not (required_slides | required_previews) <= self.artifacts.keys():
            raise QualityHold("all eight slides and both mobile previews must be approved")
        for relative, expected in self.artifacts.items():
            if file_hash(safe_asset(root, relative)) != expected:
                raise QualityHold(f"approved artifact changed: {relative}")
        actual = digest(
            {
                "episode_id": self.episode_id,
                "version": self.release_version,
                "inputs": hashes,
                "artifacts": self.artifacts,
                "channels": self.required_channels,
                "synthetic": self.synthetic,
            }
        )
        if self.content_hash != actual or report.content_hash != actual:
            raise QualityHold("content and QC are not bound to the same release")


def build_release(
    *,
    episode_id: str,
    version: int,
    synthetic: bool,
    inputs: dict,
    artifacts: dict[str, str],
    channels: tuple[str, ...],
    report: QualityReport,
    approved_by: str,
    approved_at: datetime,
) -> ReleaseManifest:
    hashes = {k: digest(v) for k, v in inputs.items()}
    content_hash = digest(
        {
            "episode_id": episode_id,
            "version": version,
            "inputs": hashes,
            "artifacts": artifacts,
            "channels": channels,
            "synthetic": synthetic,
        }
    )
    if report.content_hash != content_hash:
        raise QualityHold("review must reference the exact content hash")
    report.approve()
    return ReleaseManifest(
        episode_id=episode_id,
        release_version=version,
        synthetic=synthetic,
        input_hashes=hashes,
        artifacts=artifacts,
        required_channels=channels,
        quality_report_hash=digest(report),
        approved_by=approved_by,
        approved_at=approved_at,
        content_hash=content_hash,
    )


def validate_release_inputs(inputs: dict, root: Path) -> None:
    """Recheck required source contracts at the final gate, not merely their hashes."""
    from engine.quality.canon import CanonManifest
    from engine.quality.contracts import Claim, EditorialPlan, EvidenceBundle
    from engine.quality.pipeline import prepare

    required = {"evidence", "editorial", "claims", "canon", "script", "calculation"}
    if not isinstance(inputs, dict) or not required <= inputs.keys():
        raise QualityHold("required release source contracts missing")
    if not isinstance(inputs["script"], dict) or not isinstance(inputs["calculation"], dict):
        raise QualityHold("script and calculation must be objects")
    prepare(
        bundle=EvidenceBundle.model_validate(inputs["evidence"]),
        plan=EditorialPlan.model_validate(inputs["editorial"]),
        claims=[Claim.model_validate(c) for c in inputs["claims"]],
        canon=CanonManifest.model_validate(inputs["canon"]),
        script=inputs["script"],
        calculation=inputs["calculation"],
        root=root,
    )
