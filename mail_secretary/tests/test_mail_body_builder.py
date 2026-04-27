from app.output.mail_body_builder import build_mail_body


def test_build_mail_body_removes_forbidden_phrases() -> None:
    text = "이 문서는 ChatGPT 자동 생성 결과입니다"
    out = build_mail_body(text)
    assert "ChatGPT" not in out
    assert "자동 생성" not in out


def test_build_mail_body_limits_length() -> None:
    text = "가" * 1200
    out = build_mail_body(text)
    assert len(out) == 1000
