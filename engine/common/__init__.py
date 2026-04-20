"""Common engine package exports."""

from . import supabase_client  # re-export for stable patch/import path in tests

__all__ = ["supabase_client"]
