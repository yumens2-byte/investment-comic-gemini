"""Second market data source for redundancy (F3 dollar index)."""
from __future__ import annotations

from datetime import date
from typing import Protocol

from sidestory.core.dollar import DollarCandidate


class DxySource(Protocol):
    def dxy_close(self, on_or_before: date) -> DollarCandidate | None:
        """Latest ICE DXY daily close with bar date <= on_or_before; None if unavailable."""
        ...
