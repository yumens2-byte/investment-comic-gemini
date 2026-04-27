import re
from dataclasses import dataclass

PII_PATTERNS = {
    "resident_id": re.compile(r"\b\d{6}-\d{7}\b"),
    "phone": re.compile(r"\b01[0-9]-?\d{3,4}-?\d{4}\b"),
    "card": re.compile(r"\b\d{4}-\d{4}-\d{4}-\d{4}\b"),
    "api_key": re.compile(r"(?i)(api[_-]?key|token|password|oauth[_-]?secret)\s*[:=]\s*\S+"),
    "internal_url": re.compile(r"\bhttps?://(?:10\.|172\.(?:1[6-9]|2\d|3[0-1])\.|192\.168\.)\S*"),
}

HIGH_RISK_KEYS = {"api_key"}


@dataclass(frozen=True)
class ScanResult:
    findings: list[str]
    risk_level: str

    @property
    def block_external(self) -> bool:
        return self.risk_level == "high"


def detect_sensitive_content(text: str) -> ScanResult:
    findings: list[str] = []
    for name, pattern in PII_PATTERNS.items():
        if pattern.search(text):
            findings.append(name)
    if any(key in HIGH_RISK_KEYS for key in findings):
        level = "high"
    elif findings:
        level = "medium"
    else:
        level = "low"
    return ScanResult(findings=findings, risk_level=level)
