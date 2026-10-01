"""Read-only SNS inspection. A successful inspection is not a delivered publication."""
from __future__ import annotations

import os
import re
from datetime import date
from pathlib import Path


def parse_dry_run(value: str) -> bool:
    value = value.strip().lower()
    if value not in {'true', 'false'}:
        raise ValueError('DRY_RUN must be true or false')
    return value == 'true'


def configuration_issues(channels: list[str]) -> list[str]:
    issues = []
    if 'x' in channels and not all(os.environ.get(k) for k in (
        'X_API_KEY', 'X_API_SECRET', 'X_ACCESS_TOKEN', 'X_ACCESS_TOKEN_SECRET'
    )):
        issues.append('x_configuration_missing')
    if 'telegram' in channels and not all(os.environ.get(k) for k in (
        'TELEGRAM_BOT_TOKEN', 'TELEGRAM_FREE_CHANNEL_ID'
    )):
        issues.append('telegram_configuration_missing')
    return issues


def inspect_publish(episode: str | None, requested_date: str | None, channels: str,
                    *, dry_run: bool, video_only: bool = False) -> dict:
    from engine.common.supabase_client import icg_table
    from engine.quality.contracts import QualityHold
    from engine.quality.publish_guard import guard_legacy_track, normalize_channels
    from scripts.resolve_episode import resolve

    requested_channels = normalize_channels(channels)
    if not episode and not requested_date:
        episode = resolve('')['episode_id']
    if episode:
        match = re.fullmatch(r'ICG-(\d{4}-\d{2}-\d{2})-(\d{3})', episode)
        if not match or int(match[2]) < 1:
            raise ValueError('Invalid episode ID')
        episode_date, episode_no = match[1], int(match[2])
        if requested_date and requested_date != episode_date:
            raise ValueError('episode/date mismatch')
    else:
        episode_date, episode_no = requested_date, 1
        episode = f'ICG-{episode_date}-{episode_no:03d}'
    if date.fromisoformat(episode_date).isoformat() != episode_date:
        raise ValueError('Date must use YYYY-MM-DD')

    def read(table, fields, filters):
        query = icg_table(table).select(fields)
        for column, value in filters.items():
            query = query.eq(column, value)
        rows = query.limit(2 if table == 'episode_assets' else 1).execute().data
        if not isinstance(rows, list) or any(not isinstance(r, dict) for r in rows):
            raise RuntimeError('Invalid publication inspection response')
        if table == 'episode_assets' and len(rows) > 1:
            raise RuntimeError('Ambiguous episode identity')
        return rows

    rows = read('episode_assets', '*', {'episode_date': episode_date, 'episode_no': episode_no})
    if not rows:
        raise ValueError('Episode not found')
    row = rows[0]
    script = row.get('script_json') or {}
    if not isinstance(script, dict):
        raise ValueError('Malformed narrative metadata')
    reasons = []
    try:
        guard_legacy_track(script, row)
    except QualityHold:
        reasons.append('quality_track_requires_adapter')
    if str(row.get('error_message') or '').startswith('PUBLISH_HOLD:'):
        reasons.append('unresolved_publication_hold')
    if row.get('status') == 'published':
        reasons.append('already_published')
    elif row.get('status') not in {'assembled', 'image_generated'}:
        reasons.append('episode_not_ready')
    history = read('published_comics', 'id', {'publish_date': episode_date,
                   'episode_no': episode_no, 'comic_type': row.get('event_type', 'NORMAL')})
    if history:
        reasons.append('publication_history_exists')
    from scripts.run_publish import is_major_event

    if not is_major_event(row.get('event_type', 'NORMAL')) and os.environ.get(
        'PUBLISH_NON_MAJOR', 'false'
    ).strip().lower() != 'true':
        reasons.append('non_major_event_policy')
    assets = row.get('slides_json') or []
    valid_metadata = isinstance(assets, list) and bool(assets) and all(
        isinstance(asset, dict) and isinstance(asset.get('path'), str) and asset['path']
        for asset in assets
    )
    paths = [Path(a['path']) for a in assets] if valid_metadata else []
    files_present = bool(paths) and all(p.is_file() for p in paths)
    files_valid = False
    if files_present:
        from engine.publish.telegram_publisher import _validate_slides

        try:
            _validate_slides(paths)
            files_valid = True
        except (ValueError, OSError):
            pass
    readiness = []
    if not files_valid:
        readiness.append('slides_missing_or_invalid')
    if 'x' in requested_channels:
        from engine.common.exceptions import DisclaimerMissing
        from engine.publish.x_publisher import _guard_disclaimer

        try:
            _guard_disclaimer(script.get('caption_x_final', ''))
        except DisclaimerMissing:
            readiness.append('x_disclaimer_missing')
    readiness.extend(configuration_issues(requested_channels))
    if video_only:
        readiness.append('video_only_preflight_not_supported')
    ready = not reasons and not readiness
    return {'mode': 'dry_run' if dry_run else 'live_preflight',
            'status': 'blocked' if reasons else ('ready' if ready else 'incomplete'),
            'inspection_status': 'pass', 'episode_id': episode, 'episode_date': episode_date,
            'episode_status': row.get('status'), 'channels': requested_channels,
            'allowed': ready and not dry_run, 'live_publish_ready': ready,
            'block_reasons': reasons, 'readiness_issues': readiness,
            'slides_metadata_present': bool(valid_metadata), 'slides_files_present': files_present,
            'slides_files_valid': files_valid, 'database_writes': 0, 'paid_calls': 0, 'publishes': 0,
            'unverified': ['provider_authentication', 'actual_delivery', 'visual_comic_quality']}
