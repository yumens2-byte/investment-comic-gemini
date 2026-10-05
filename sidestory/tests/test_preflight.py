"""Regression for the 2026-10-05 gate run: PGRST106 surfaced as a raw stack trace."""
from __future__ import annotations

import pytest

from sidestory.adapters.supabase.client import SideSetupError, preflight


class _APIError(Exception):  # shape of postgrest.exceptions.APIError
    def __init__(self, payload: dict):
        super().__init__(payload)
        self.code = payload.get("code")


class _Query:
    def __init__(self, error):
        self._error = error

    def select(self, *_):
        return self

    def limit(self, *_):
        return self

    def execute(self):
        if self._error:
            raise self._error
        return type("R", (), {"data": []})()


class _Client:
    def __init__(self, error=None, rpc_error=None):
        self._error, self._rpc_error = error, rpc_error

    def schema(self, _name):
        return self

    def table(self, _name):
        return _Query(self._error)

    def rpc(self, *_):
        return _Query(self._rpc_error)


@pytest.mark.parametrize(("code", "needle"), [
    ("PGRST106", "Exposed schemas"),
    ("PGRST205", "0001_icg_side_schema.sql"),
    ("42P01", "0001_icg_side_schema.sql"),
])
def test_setup_errors_are_actionable(code: str, needle: str) -> None:
    err = _APIError({"message": "x", "code": code})
    with pytest.raises(SideSetupError) as info:
        preflight(_Client(error=err))
    assert needle in str(info.value) and code in str(info.value)


def test_missing_fingerprint_function() -> None:
    with pytest.raises(SideSetupError, match="PGRST202"):
        preflight(_Client(rpc_error=_APIError({"code": "PGRST202"})))


def test_unknown_errors_propagate_and_ready_passes() -> None:
    with pytest.raises(_APIError):
        preflight(_Client(error=_APIError({"code": "XX000"})))
    preflight(_Client())
