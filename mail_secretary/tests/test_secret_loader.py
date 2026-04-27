import pytest

from app.common.errors import SecretNotFoundError
from app.config.secret_loader import load_required_secrets


def test_load_required_secrets_success() -> None:
    values = {
        "GMAIL_CLIENT_ID": "a",
        "GMAIL_CLIENT_SECRET": "b",
        "GMAIL_REFRESH_TOKEN": "c",
        "SYSTEM_MAIL_ACCOUNT": "d",
        "ALLOWED_COMMAND_SENDERS": "e",
        "OPENAI_API_KEY": "f",
        "CLAUDE_API_KEY": "g",
        "GEMINI_API_KEY": "h",
    }

    bundle = load_required_secrets(lambda k: values.get(k, ""))
    assert bundle.get("SYSTEM_MAIL_ACCOUNT") == "d"


def test_load_required_secrets_missing() -> None:
    with pytest.raises(SecretNotFoundError):
        load_required_secrets(lambda _: "")
