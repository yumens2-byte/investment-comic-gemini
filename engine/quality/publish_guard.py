"""Safety boundary between the existing SNS workflow and offline quality pilot."""

from engine.quality.contracts import QualityHold


def guard_legacy_track(script: dict, row: dict) -> None:
    if any(
        key in obj
        for obj, key in (
            (script, "_webtoon_quality"),
            (row, "quality_release"),
            (script, "quality_release"),
        )
    ):
        raise QualityHold("quality pilot release requires a production database publisher adapter")


def require_channel_success(channels: list[str], tweet_ids: list[str], telegram_sent: bool) -> None:
    normalized = set(normalize_channels(channels))
    if not normalized or not normalized <= {"all", "x", "telegram"}:
        raise QualityHold("invalid requested publication channels")
    if ("x" in normalized or "all" in normalized) and not tweet_ids:
        raise QualityHold("requested X publication incomplete")
    if ("telegram" in normalized or "all" in normalized) and not telegram_sent:
        raise QualityHold("requested Telegram publication incomplete")


def normalize_channels(channels: str | list[str]) -> list[str]:
    values = channels.split(",") if isinstance(channels, str) else channels
    normalized = [c.strip().lower() for c in values]
    if not normalized or not set(normalized) <= {"all", "x", "telegram"}:
        raise QualityHold("invalid requested publication channels")
    if "all" in normalized:
        return ["x", "telegram"]
    return list(dict.fromkeys(normalized))


def require_publication_id(result: object, key: str) -> str:
    if not isinstance(result, dict):
        raise QualityHold("publication response must contain a verified external ID")
    value = result.get(key)
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise QualityHold("publication external ID missing")
    external_id = str(value).strip()
    if not external_id or external_id.lower() in {"none", "null", "0"}:
        raise QualityHold("publication external ID invalid")
    return external_id
