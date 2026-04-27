FORBIDDEN_PHRASES = [
    "AI가 작성",
    "ChatGPT",
    "Claude",
    "Gemini",
    "자동 생성",
    "인공지능 답변",
]



def sanitize_forbidden_phrases(text: str) -> str:
    out = text
    for phrase in FORBIDDEN_PHRASES:
        out = out.replace(phrase, "")
    return " ".join(out.split())


def build_mail_body(summary: str, limit: int = 1000) -> str:
    cleaned = sanitize_forbidden_phrases(summary)
    return cleaned[:limit]
