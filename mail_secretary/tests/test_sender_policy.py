from app.mail.sender_policy import is_allowed_sender


def test_allowed_sender_accepts_case_insensitive_address() -> None:
    allowed = {"jaewon.yu@hcs.com", "ops@example.com"}
    assert is_allowed_sender("Yu <Jaewon.Yu@hcs.com>", allowed)


def test_allowed_sender_rejects_unknown_sender() -> None:
    allowed = {"jaewon.yu@hcs.com"}
    assert not is_allowed_sender("bad@example.com", allowed)
