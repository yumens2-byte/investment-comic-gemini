from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SIDE_ROOT = REPO_ROOT / "sidestory"


@pytest.fixture
def repo_root() -> Path:
    return REPO_ROOT
