"""Dollar-index redundancy (F3): pick which dollar value the side story may quote.

Facts behind the rules (verified 2026-10-05):
  * Main ``daily_snapshots.dollar_index`` is FRED DTWEXBGS (engine/data/fred_fetcher.py:33),
    the Fed *broad* trade-weighted index (~118–121), not ICE DXY (~100).
  * In production it changes about once a week and is carried forward between changes
    (2026-09: changes on 09-10, 09-15, 09-22, 09-29; identical values in between).
    The snapshot date therefore is NOT the observation date.
  * No other populated DXY source exists in the DB (kr/public DXY tables empty or stale).

Policy:
  1. ICE DXY daily close (second source, own bar date) is the primary quote: readers read
     "달러인덱스" as DXY.
  2. The main broad index is the fallback, always labelled as the broad index, with its
     inferred as-of date (first day of its current carried-forward run).
  3. When both are valid their direction over the overlapping window is cross-checked;
     a disagreement is flagged (informational, never blocks).
  4. Neither valid → omit the dollar from the story (None + reason). Never guess.
"""
from __future__ import annotations

from datetime import date
from enum import Enum

from pydantic import BaseModel, Field


class DollarIndexKind(str, Enum):
    DXY = "DXY"        # ICE U.S. Dollar Index (6 majors)
    BROAD = "BROAD"    # Fed nominal broad dollar index (trade-weighted)


LABEL_KO = {DollarIndexKind.DXY: "달러인덱스", DollarIndexKind.BROAD: "광의 달러지수"}

# Plausibility bands (reject unit/series mix-ups such as USD/KRW or a broad value as DXY).
RANGE = {DollarIndexKind.DXY: (70.0, 130.0), DollarIndexKind.BROAD: (90.0, 150.0)}
# DXY: completed daily close strictly before the main KST date (see _validate).
# Allow weekend + one holiday between bar date and main date.
DXY_MAX_AGE_DAYS = 4
# BROAD: weekly cadence observed in production → a run older than 9 days missed an update.
BROAD_MAX_RUN_AGE_DAYS = 9
# Direction cross-check only when both moved meaningfully (percent).
DIRECTION_MIN_MOVE_PCT = 0.3
# Both bands overlap (~90–130), so a broad value relabelled as DXY would pass the band.
# When both sources exist, a "DXY" within this distance of the broad value is a series mix-up
# (production: DXY≈100 vs broad≈120, i.e. ~17% apart).
MIX_UP_MAX_GAP_PCT = 3.0


class DollarCandidate(BaseModel):
    kind: DollarIndexKind
    value: float
    as_of: str                      # ISO date of the observation (or inferred run start)
    source: str                     # internal provenance — never printed in copy
    change_pct_1w: float | None = None


class DollarDecision(BaseModel):
    chosen: DollarCandidate | None
    label_ko: str | None = None
    rejected: dict[str, str] = Field(default_factory=dict)
    flags: list[str] = Field(default_factory=list)

    @property
    def value(self) -> float | None:
        return round(self.chosen.value, 2) if self.chosen else None


def infer_broad_from_history(history: list[tuple[str, float | None]]) -> DollarCandidate | None:
    """Build the BROAD candidate from main snapshot history [(snapshot_date, value)].

    as_of = first snapshot date of the latest carried-forward run (identical values).
    change_pct_1w = latest run value vs the previous distinct run value.
    """
    rows = sorted((d, v) for d, v in history if v is not None)
    if not rows:
        return None
    latest_value = rows[-1][1]
    run_start = rows[-1][0]
    previous_value: float | None = None
    for snapshot_date, value in reversed(rows):
        if value == latest_value:
            run_start = snapshot_date
        else:
            previous_value = value
            break
    change = None
    if previous_value:
        change = (latest_value - previous_value) / previous_value * 100.0
    return DollarCandidate(kind=DollarIndexKind.BROAD, value=float(latest_value),
                           as_of=run_start, source="main.daily_snapshots.dollar_index",
                           change_pct_1w=change)


def _age_days(as_of: str, reference: date) -> int:
    return (reference - date.fromisoformat(as_of)).days


def _validate(c: DollarCandidate, reference: date) -> str | None:
    low, high = RANGE[c.kind]
    if not (low <= c.value <= high):
        return f"out of range {c.value} not in [{low}, {high}]"
    try:
        age = _age_days(c.as_of, reference)
    except ValueError:
        return f"invalid as_of {c.as_of!r}"
    if age < 0:
        return f"as_of {c.as_of} is after reference {reference}"
    if c.kind is DollarIndexKind.DXY and age == 0:
        # Main episode of KST date D is generated at 01:36 KST (= US D-1 midday), so it can
        # never contain US session D. A DXY bar dated D is an in-progress bar, not a close
        # (observed 2026-10-05: 102.29 fetched at 02:13 ET while main used Fri 10-02 data).
        return f"in-progress bar {c.as_of} (same date as main episode)"
    limit = DXY_MAX_AGE_DAYS if c.kind is DollarIndexKind.DXY else BROAD_MAX_RUN_AGE_DAYS
    if age > limit:
        return f"stale: {age}d > {limit}d"
    return None


def select_dollar(
    reference: date,
    dxy: DollarCandidate | None,
    broad: DollarCandidate | None,
) -> DollarDecision:
    """Reference = the anchored main episode date (the story's market day)."""
    rejected: dict[str, str] = {}
    valid: dict[DollarIndexKind, DollarCandidate] = {}
    for kind, cand in ((DollarIndexKind.DXY, dxy), (DollarIndexKind.BROAD, broad)):
        if cand is None:
            rejected[kind.value] = "unavailable"
            continue
        if cand.kind is not kind:
            rejected[kind.value] = f"kind mismatch: {cand.kind.value}"
            continue
        reason = _validate(cand, reference)
        if reason:
            rejected[kind.value] = reason
        else:
            valid[kind] = cand

    flags: list[str] = []
    a, b = valid.get(DollarIndexKind.DXY), valid.get(DollarIndexKind.BROAD)
    if a and b and abs(a.value - b.value) / b.value * 100.0 < MIX_UP_MAX_GAP_PCT:
        rejected[DollarIndexKind.DXY.value] = (
            f"series mix-up suspected: DXY {a.value} within {MIX_UP_MAX_GAP_PCT}% of broad {b.value}")
        valid.pop(DollarIndexKind.DXY)
        a = None
    if a and b and a.change_pct_1w is not None and b.change_pct_1w is not None:
        if (abs(a.change_pct_1w) >= DIRECTION_MIN_MOVE_PCT
                and abs(b.change_pct_1w) >= DIRECTION_MIN_MOVE_PCT
                and (a.change_pct_1w > 0) != (b.change_pct_1w > 0)):
            flags.append("direction_divergence")

    chosen = a or b
    if chosen is None:
        flags.append("dollar_omitted")
    elif chosen.kind is DollarIndexKind.BROAD:
        flags.append("fallback_broad_index")
    return DollarDecision(chosen=chosen, label_ko=LABEL_KO[chosen.kind] if chosen else None,
                          rejected=rejected, flags=flags)
