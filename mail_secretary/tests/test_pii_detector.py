from app.security.pii_detector import detect_sensitive_content


def test_detect_medium_risk_for_phone() -> None:
    result = detect_sensitive_content("담당자 연락처는 010-1234-5678 입니다")
    assert result.risk_level == "medium"
    assert "phone" in result.findings


def test_detect_high_risk_for_api_key() -> None:
    result = detect_sensitive_content("api_key=abcd1234")
    assert result.risk_level == "high"
    assert result.block_external
