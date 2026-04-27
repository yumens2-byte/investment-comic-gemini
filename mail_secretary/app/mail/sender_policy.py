from email.utils import parseaddr


def is_allowed_sender(sender_header: str, allowed_senders: set[str]) -> bool:
    _, email_addr = parseaddr(sender_header)
    normalized = email_addr.lower().strip()
    allow_norm = {s.lower().strip() for s in allowed_senders}
    return normalized in allow_norm
