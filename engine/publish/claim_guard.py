"""Conservative episode-level hold using an existing episode_assets column.

This is not a part journal or provider reconciliation adapter. An ambiguous run
keeps its hold until an operator verifies external posts and clears it. Conditional
UPDATE prevents two publishers from entering the same episode simultaneously.
"""

from __future__ import annotations

import uuid

from engine.quality.contracts import QualityHold

PREFIX = "PUBLISH_HOLD:"


def require_no_publication_hold(row: dict) -> None:
    from engine.quality.content_qc import require_content_ready

    require_content_ready(row.get("script_json") or {}, row)
    if str(row.get("error_message") or "").startswith(PREFIX):
        raise QualityHold("previous publication is unresolved; reconcile before retry")


MAX_SAFE_URL = 8192


def _claim_query(row: dict, episode_date: str, episode_no: int, token: str):
    from engine.common.supabase_client import icg_table

    query = (
        icg_table("episode_assets")
        .update({"error_message": token})
        .eq("episode_date", episode_date)
        .eq("episode_no", episode_no)
        .eq("status", row.get("status"))
    )
    old = row.get("error_message")
    # Fence on the trigger-maintained row version. A jsonb equality filter cannot be
    # sent as a URL parameter (dict repr is not JSON and large scripts exceed URL limits).
    version = row.get("updated_at")
    if not isinstance(version, str) or not version:
        raise QualityHold("publication claim requires the episode row version; no external send")
    query = query.eq("updated_at", version)
    return query.is_("error_message", "null") if old is None else query.eq("error_message", old)


def _release_query(episode_date: str, episode_no: int, token: str):
    from engine.common.supabase_client import icg_table

    return (
        icg_table("episode_assets")
        .update({"error_message": None})
        .eq("episode_date", episode_date)
        .eq("episode_no", episode_no)
        .eq("error_message", token)
    )


def claim_publication(row: dict, episode_date: str, episode_no: int) -> str:
    require_no_publication_hold(row)
    token = PREFIX + str(uuid.uuid4())
    response = _claim_query(row, episode_date, episode_no, token).execute()
    rows = response.data
    if not isinstance(rows, list) or len(rows) != 1 or rows[0].get("error_message") != token:
        raise QualityHold("publication claim not acquired; no external send allowed")
    return token


def rehearse_publication_requests(row: dict, episode_date: str, episode_no: int) -> list[str]:
    """Build (never send) the claim and release HTTP requests and report shape defects."""
    issues: list[str] = []
    token = PREFIX + "00000000-0000-0000-0000-000000000000"
    for name, build in (("claim", lambda: _claim_query(row, episode_date, episode_no, token)),
                        ("release", lambda: _release_query(episode_date, episode_no, token))):
        try:
            config = build().request
            request = config.session.build_request(
                config.http_method, str(config.path), json=config.json, params=config.params)
        except QualityHold as exc:
            issues.append(f"{name}_request_invalid:{exc}")
            continue
        except Exception as exc:  # httpx.InvalidURL and serialization defects
            issues.append(f"{name}_request_invalid:{type(exc).__name__}")
            continue
        url = str(request.url)
        if len(url) >= MAX_SAFE_URL:
            issues.append(f"{name}_request_url_too_long:{len(url)}")
        if "%7B%27" in url or "%5B%27" in url:
            issues.append(f"{name}_request_python_repr_filter")
    return issues


def finish_publication(episode_date: str, episode_no: int, token: str) -> None:
    response = _release_query(episode_date, episode_no, token).execute()
    if not isinstance(response.data, list) or len(response.data) != 1:
        raise QualityHold("publication completed but claim release failed; reconcile history")
