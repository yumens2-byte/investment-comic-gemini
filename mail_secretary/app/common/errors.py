class MailSecretaryError(Exception):
    """Base error for mail secretary."""


class SecretNotFoundError(MailSecretaryError):
    """Raised when a required secret cannot be loaded."""


class ForbiddenSenderError(MailSecretaryError):
    """Raised when sender is not allowed."""
