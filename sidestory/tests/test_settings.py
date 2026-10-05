from __future__ import annotations

import pytest

from sidestory.app.settings import SettingsError, load_settings


def test_schema_must_be_icg_side(monkeypatch) -> None:
    monkeypatch.setenv("SUPABASE_SCHEMA", "icg")
    with pytest.raises(SettingsError):
        load_settings()
    monkeypatch.delenv("SUPABASE_SCHEMA")
    with pytest.raises(SettingsError):
        load_settings()


def test_defaults_and_facebook_secret_names(monkeypatch) -> None:
    monkeypatch.setenv("SUPABASE_SCHEMA", "icg_side")
    monkeypatch.delenv("DRY_RUN", raising=False)
    monkeypatch.setenv("FACE_PAGE_ID", "123")
    monkeypatch.setenv("FACE_PAGE_TOKEN", "tok")
    settings = load_settings()
    assert settings.dry_run is True
    assert settings.nn_stage == "E01"
    settings.require_facebook()
