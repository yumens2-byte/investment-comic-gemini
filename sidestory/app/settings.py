"""Single place where the side track reads environment variables."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml

SIDE_SCHEMA = "icg_side"
CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"


class SettingsError(RuntimeError):
    pass


def _bool(name: str, default: str) -> bool:
    value = os.environ.get(name, default).strip().lower()
    if value not in {"true", "false"}:
        raise SettingsError(f"{name} must be true|false")
    return value == "true"


@dataclass(frozen=True)
class Settings:
    supabase_url: str
    supabase_key: str
    dry_run: bool
    nn_stage: str
    face_page_id: str
    face_page_token: str

    def require_db(self) -> None:
        if not self.supabase_url or not self.supabase_key:
            raise SettingsError("SUPABASE_URL / SUPABASE_KEY missing")

    def require_facebook(self) -> None:
        if not self.face_page_id or not self.face_page_token:
            raise SettingsError("FACE_PAGE_ID / FACE_PAGE_TOKEN missing")


def load_canon_state() -> dict:
    return yaml.safe_load((CONFIG_DIR / "canon_state.yaml").read_text(encoding="utf-8")) or {}


def load_characters() -> dict:
    return yaml.safe_load(
        (CONFIG_DIR / "characters_side.yaml").read_text(encoding="utf-8")) or {}


def load_settings() -> Settings:
    # The side track must never run against the main schema (K-1).
    schema = os.environ.get("SUPABASE_SCHEMA", "")
    if schema != SIDE_SCHEMA:
        raise SettingsError(f"SUPABASE_SCHEMA must be {SIDE_SCHEMA!r} (got {schema!r})")
    canon = load_canon_state()
    return Settings(
        supabase_url=os.environ.get("SUPABASE_URL", ""),
        supabase_key=os.environ.get("SUPABASE_KEY", ""),
        dry_run=_bool("DRY_RUN", "true"),
        nn_stage=str(canon.get("nn_stage", "E01")),
        face_page_id=os.environ.get("FACE_PAGE_ID", ""),
        face_page_token=os.environ.get("FACE_PAGE_TOKEN", ""),
    )
