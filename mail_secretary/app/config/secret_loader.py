from dataclasses import dataclass
from typing import Callable, Dict

from app.common.errors import SecretNotFoundError


REQUIRED_SECRETS = [
    "GMAIL_CLIENT_ID",
    "GMAIL_CLIENT_SECRET",
    "GMAIL_REFRESH_TOKEN",
    "SYSTEM_MAIL_ACCOUNT",
    "ALLOWED_COMMAND_SENDERS",
    "OPENAI_API_KEY",
    "CLAUDE_API_KEY",
    "GEMINI_API_KEY",
]


@dataclass(frozen=True)
class SecretBundle:
    values: Dict[str, str]

    def get(self, name: str) -> str:
        return self.values[name]


def load_required_secrets(read_secret: Callable[[str], str]) -> SecretBundle:
    loaded = {}
    missing = []
    for key in REQUIRED_SECRETS:
        val = read_secret(key)
        if not val:
            missing.append(key)
        else:
            loaded[key] = val
    if missing:
        raise SecretNotFoundError(f"Missing secrets: {', '.join(missing)}")
    return SecretBundle(values=loaded)
