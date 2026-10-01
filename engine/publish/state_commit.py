"""Pre-send database readiness and durable per-batch delivery receipts."""
from engine.quality.contracts import QualityHold


def _rpc(name: str, params: dict) -> dict:
    from engine.common.supabase_client import get_client, get_schema

    try:
        result = get_client().schema(get_schema()).rpc(name, params).execute().data
    except Exception as exc:
        raise QualityHold("publication state contract unavailable; no automatic resend") from exc
    if not isinstance(result, dict):
        raise QualityHold("invalid publication state receipt")
    return result


def require_state_ready(episode_date: str, episode_no: int, candidate: dict) -> None:
    result = _rpc("publication_state_preflight", {
        "p_date": episode_date, "p_no": episode_no, "p_candidate": candidate,
    })
    if result.get("ready") is not True:
        raise QualityHold("confirmed story state changed or publication adapter unavailable")


def record_delivery(episode_date: str, episode_no: int, token: str,
                    channel: str, ids: list[str | int]) -> None:
    result = _rpc("record_episode_delivery", {
        "p_date": episode_date, "p_no": episode_no, "p_token": token,
        "p_channel": channel, "p_ids": ids,
    })
    if result.get("recorded") is not True:
        raise QualityHold("delivery occurred but receipt save failed; reconcile without resending")
