"""Common engine package exports.

Keep this package initializer lightweight.  Importing submodules such as
``engine.common.notion_loader`` must not require optional runtime dependencies
used by unrelated helpers (for example ``supabase``).
"""

from __future__ import annotations

import importlib
from types import ModuleType

__all__ = ["supabase_client"]


def __getattr__(name: str) -> ModuleType:
    """Lazily expose selected common submodules for stable patch paths."""
    if name == "supabase_client":
        return importlib.import_module(f"{__name__}.supabase_client")
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
