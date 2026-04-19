"""
Video Track Budget Checker.

Purpose:
  Enforce monthly Veo API spending cap by querying Supabase icg.video_assets
  and summing veo_cost_usd for the current month before allowing new calls.

Environment:
  VIDEO_BUDGET_USD_MONTHLY  : Monthly cap in USD (default 80.0)
  SUPABASE_URL, SUPABASE_KEY : Supabase credentials

Usage:
  from engine.video.budget_checker import check_before_generation

  check_before_generation(estimated_cost_usd=0.64)  # raises BudgetExceededError

Design notes:
  - Month boundary is UTC (YYYY-MM-01 00:00Z to next month 00:00Z)
  - Query uses icg.video_assets.created_at (timestamptz with default now())
  - Fail-open on Supabase errors? NO — fail-closed (safety first).
    If we can't read the ledger, we don't spend money.
"""
import logging
import os
from datetime import datetime, timezone
from typing import Optional

VERSION = "1.0.0"
logger = logging.getLogger(__name__)

DEFAULT_BUDGET_USD = 80.0


class BudgetExceededError(RuntimeError):
    """Raised when the next generation would exceed the monthly budget cap."""


class BudgetCheckError(RuntimeError):
    """Raised when the budget check itself failed (e.g., Supabase unreachable)."""


def _current_month_bounds() -> tuple[str, str]:
    """Return (start_iso, end_iso) for the current UTC month."""
    now = datetime.now(timezone.utc)
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    # Next month's first day
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)
    return start.isoformat(), end.isoformat()


def get_monthly_cost_usd() -> float:
    """
    Query Supabase icg.video_assets for current-month total veo_cost_usd.

    Returns:
        Sum of veo_cost_usd for rows with created_at in current UTC month.
        Zero if no rows.

    Raises:
        BudgetCheckError if Supabase query fails.
    """
    try:
        from supabase import create_client
    except ImportError as e:
        raise BudgetCheckError(f"supabase package not installed: {e}") from e

    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    if not url or not key:
        raise BudgetCheckError("SUPABASE_URL or SUPABASE_KEY not set")

    start_iso, end_iso = _current_month_bounds()

    try:
        client = create_client(url, key)
        # schema="icg" sets the schema for this query
        result = (
            client.schema("icg")
            .table("video_assets")
            .select("veo_cost_usd")
            .gte("created_at", start_iso)
            .lt("created_at", end_iso)
            .execute()
        )
    except Exception as e:
        raise BudgetCheckError(f"Supabase query failed: {e}") from e

    rows = result.data or []
    total = sum(float(r.get("veo_cost_usd") or 0.0) for r in rows)
    logger.info(
        f"[budget_checker] v{VERSION} monthly cost: ${total:.4f} "
        f"(rows={len(rows)}, month={start_iso[:7]})"
    )
    return total


def check_before_generation(
    estimated_cost_usd: float,
    budget_cap_usd: Optional[float] = None,
) -> dict:
    """
    Validate that the estimated cost fits within the remaining monthly budget.

    Args:
        estimated_cost_usd : Cost of the upcoming generation (e.g., 0.64 for 8s @ $0.08)
        budget_cap_usd     : Override the env-based cap (primarily for testing)

    Returns:
        dict with keys: monthly_spent_usd, budget_cap_usd, remaining_usd, estimated_cost_usd

    Raises:
        BudgetExceededError if (monthly_spent + estimated) > budget_cap.
        BudgetCheckError on Supabase failure (fail-closed).
    """
    if budget_cap_usd is None:
        cap_str = os.environ.get("VIDEO_BUDGET_USD_MONTHLY", str(DEFAULT_BUDGET_USD))
        try:
            budget_cap_usd = float(cap_str)
        except ValueError:
            logger.warning(
                f"[budget_checker] invalid VIDEO_BUDGET_USD_MONTHLY='{cap_str}', "
                f"using default ${DEFAULT_BUDGET_USD}"
            )
            budget_cap_usd = DEFAULT_BUDGET_USD

    monthly_spent = get_monthly_cost_usd()
    projected_total = monthly_spent + estimated_cost_usd
    remaining = budget_cap_usd - monthly_spent

    summary = {
        "monthly_spent_usd": round(monthly_spent, 4),
        "budget_cap_usd": budget_cap_usd,
        "remaining_usd": round(remaining, 4),
        "estimated_cost_usd": estimated_cost_usd,
        "projected_total_usd": round(projected_total, 4),
    }

    if projected_total > budget_cap_usd:
        logger.error(
            f"[budget_checker] BUDGET EXCEEDED: "
            f"spent=${monthly_spent:.4f} + estimated=${estimated_cost_usd:.4f} "
            f"= ${projected_total:.4f} > cap=${budget_cap_usd:.2f}"
        )
        raise BudgetExceededError(
            f"Monthly budget ${budget_cap_usd:.2f} would be exceeded: "
            f"spent=${monthly_spent:.4f} + next=${estimated_cost_usd:.4f}"
        )

    logger.info(
        f"[budget_checker] OK: ${monthly_spent:.4f}/${budget_cap_usd:.2f} "
        f"(next +${estimated_cost_usd:.4f}, remaining after=${remaining - estimated_cost_usd:.4f})"
    )
    return summary
