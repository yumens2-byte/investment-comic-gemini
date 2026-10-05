"""Publish cadence (Tue/Thu KST) and main-episode anchor selection."""
from __future__ import annotations

from datetime import date, timedelta

from sidestory.core.models import MainEpisodeRow

# Master decision 2026-10-05: side publishes twice a week, Tue and Thu (KST).
PUBLISH_WEEKDAYS: frozenset[int] = frozenset({1, 3})  # Monday=0 → Tue=1, Thu=3
# Window looked back when the main track skipped the slot date (non-major policy).
ANCHOR_LOOKBACK_DAYS = 3


def is_publish_day(day: date) -> bool:
    return day.weekday() in PUBLISH_WEEKDAYS


def previous_slot(day: date) -> date:
    """Most recent publish slot strictly before ``day``."""
    probe = day - timedelta(days=1)
    while not is_publish_day(probe):
        probe -= timedelta(days=1)
    return probe


def select_anchor(
    side_day: date,
    published_main: list[MainEpisodeRow],
    already_anchored: set[str],
) -> MainEpisodeRow | None:
    """Pick the main episode the side story echoes.

    Order: same-day main episode first, then the latest main episode inside the
    lookback window that is after the previous slot and not anchored yet.
    Returns None when nothing qualifies (gate SG-0 → SKIP).
    """
    floor = max(side_day - timedelta(days=ANCHOR_LOOKBACK_DAYS), previous_slot(side_day))
    candidates = []
    for row in published_main:
        try:
            row_day = date.fromisoformat(row.episode_date)
        except ValueError:
            continue
        if row.main_episode_id in already_anchored:
            continue
        if floor < row_day <= side_day:
            candidates.append((row_day, row.episode_no, row))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return candidates[0][2]
