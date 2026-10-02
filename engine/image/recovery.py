"""Read-only eligibility for an explicitly reviewed terminal recovery receipt."""
from engine.common.supabase_client import get_client, get_schema
from engine.image.generation_guard import GenerationHold


def require_terminal_recovery(scope: str, revision: int) -> None:
    try:
        data = get_client().schema(get_schema()).rpc(
            'image_generation_recovery_preflight',
            {'p_scope': scope, 'p_revision': revision},
        ).execute().data
        if not isinstance(data, dict) or data.get('authorized') is not True or data.get('hold'):
            raise GenerationHold('Terminal recovery receipt absent or stale')
    except GenerationHold:
        raise
    except Exception as exc:
        raise GenerationHold('Terminal recovery receipt unavailable') from exc
