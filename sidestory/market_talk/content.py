"""Versioned evidence and human-reviewed text contracts; no network or DB access."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

import yaml
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

DISCLAIMER = "캐릭터 대사는 창작이며, 투자 권유가 아닙니다."
POLICY_VERSION = "market-talk-1"


def digest(value) -> str:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(text.encode()).hexdigest()


def normalize(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKC", text).lower() if c.isalnum())


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Evidence(Strict):
    id: str = Field(min_length=1)
    statement: str = Field(min_length=1, max_length=500)
    source_url: str
    observed_at: AwareDatetime
    market_session: str = Field(min_length=1)

    @model_validator(mode="after")
    def source(self):
        u = urlparse(self.source_url)
        if u.scheme != "https" or not u.hostname or u.username or u.password:
            raise ValueError("evidence requires a public HTTPS source URL")
        if u.query or u.fragment:
            raise ValueError("source URL must not include query credentials or fragments")
        return self


class Context(Strict):
    topic: str = Field(min_length=1, max_length=120)
    claim_key: str = Field(min_length=1, max_length=120)
    kind: Literal["market_close", "concept", "episode"]
    snapshot_date: str
    snapshot_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    canon_version: str = Field(pattern=r"^[a-f0-9]{64}$")
    character_id: str
    character_name: str
    character_voice: dict
    evidence: list[Evidence] = Field(min_length=1, max_length=3)
    expires_at: AwareDatetime
    provenance_reviewer: str = Field(min_length=1)
    provenance_note: str = Field(min_length=1)
    policy_version: Literal["market-talk-1", "market-talk-2"] = POLICY_VERSION

    @model_validator(mode="after")
    def times(self):
        if len({e.id for e in self.evidence}) != len(self.evidence):
            raise ValueError("duplicate evidence IDs")
        if any(e.observed_at >= self.expires_at for e in self.evidence):
            raise ValueError("evidence must precede expiry")
        return self


class Copy(Strict):
    evidence_ids: list[str] = Field(min_length=1, max_length=3)
    commentary: str = Field(min_length=10, max_length=260)
    dialogue: str = Field(min_length=5, max_length=100)


class Draft(Strict):
    context: Context
    text: Copy
    due_at: AwareDatetime

    @property
    def revision(self):
        return digest(self.model_dump(mode="json"))

    @property
    def semantic_key(self):
        # Wording/character changes do not permit another post of the same claim/evidence.
        return digest(
            [
                normalize(self.context.topic),
                normalize(self.context.claim_key),
                sorted(e.id for e in self.context.evidence),
            ]
        )

    @property
    def body(self):
        if self.context.policy_version == "market-talk-2":
            return (
                f"{self.text.commentary}\n\n"
                f"{self.context.character_name} : “{self.text.dialogue}”"
            )
        selected = {e.id: e for e in self.context.evidence}
        facts = "\n".join(selected[i].statement for i in self.text.evidence_ids)
        sources = "\n".join(
            f"기준 {selected[i].observed_at.isoformat()} "
            f"({selected[i].market_session}) · {selected[i].source_url}"
            for i in self.text.evidence_ids
        )
        label = {"market_close": "장마감 기록", "concept": "금융 개념", "episode": "에피소드 해설"}[
            self.context.kind
        ]
        return (
            f"[{label}]\n{facts}\n\n{self.text.commentary}\n\n"
            f"{self.context.character_name} (창작 대사): “{self.text.dialogue}”\n\n"
            f"{sources}\n{DISCLAIMER}"
        )


def canon(path: Path, character_id: str, allowed: set[str]) -> dict:
    raw = path.read_bytes()
    data = yaml.safe_load(raw)
    if character_id not in allowed:
        raise ValueError("character is not approved for text publication")
    records = {**data.get("heroes", {}), **data.get("villains", {}), **data.get("anti_heroes", {})}
    c = records.get(character_id)
    if not c or not c.get("name_ko"):
        raise ValueError("unregistered character")
    return {
        "canon_version": hashlib.sha256(raw).hexdigest(),
        "character_id": character_id,
        "character_name": c["name_ko"],
        "character_voice": c.get("belief") or {"voice": c.get("voice", "")},
    }


def validate(
    draft: Draft, *, now: datetime, current_canon: str, current_snapshot: str, recent: list[dict]
) -> list[str]:
    errors = []
    ctx, copy = draft.context, draft.text
    if now.tzinfo is None:
        raise ValueError("timezone-aware clock required")
    kst = timezone(timedelta(hours=9))
    if draft.due_at.astimezone(kst).date() < now.astimezone(kst).date():
        errors.append("missed_slot")
    if now >= ctx.expires_at or draft.due_at >= ctx.expires_at:
        errors.append("expired")
    if any(e.observed_at > now for e in ctx.evidence):
        errors.append("future_evidence")
    if ctx.canon_version != current_canon:
        errors.append("canon_changed")
    if ctx.snapshot_hash != current_snapshot:
        errors.append("snapshot_changed")
    ids = [e.id for e in ctx.evidence]
    if not set(copy.evidence_ids) <= set(ids) or len(set(copy.evidence_ids)) != len(
        copy.evidence_ids
    ):
        errors.append("unknown_or_duplicate_evidence")
    creative = copy.commentary + " " + copy.dialogue
    # Deterministic screening supplements, never replaces, a fact/canon human review.
    if re.search(
        r"\d|[%$₩]|https?://|#|CHAR_|매수하세요|매도하세요|수익 보장|지금.{0,8}(급등|급락)|실시간|방금",
        creative,
    ):
        errors.append("unsupported_claim_or_realtime")
    if re.search(
        r"좋아요.{0,8}(눌러|누르)|공유.{0,8}(부탁|해주세요)|팔로우.{0,8}(해주세요|부탁)", creative
    ):
        errors.append("engagement_bait")
    if not errors:
        body_key = normalize(draft.body)
        for old in recent:
            if (
                old.get("semantic_key") == draft.semantic_key
                or SequenceMatcher(
                    None, normalize(old.get("creative", "")), normalize(creative)
                ).ratio()
                >= 0.85
                or old.get("body_hash") == digest(body_key)
            ):
                errors.append("duplicate_content")
                break
    return errors


def utcnow():
    return datetime.now(timezone.utc)
