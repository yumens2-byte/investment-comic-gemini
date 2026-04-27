from datetime import datetime


def _escape_pdf_text(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def generate_simple_pdf(title: str, body: str) -> bytes:
    content = f"{title}\n\n{body}\nGenerated: {datetime.utcnow().isoformat()}"
    safe = _escape_pdf_text(content)
    stream = f"BT /F1 12 Tf 50 780 Td ({safe}) Tj ET"

    pdf = [
        "%PDF-1.4\n",
        "1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n",
        "2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n",
        "3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >> endobj\n",
        "4 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj\n",
        f"5 0 obj << /Length {len(stream)} >> stream\n{stream}\nendstream endobj\n",
        "xref\n0 6\n0000000000 65535 f \n",
        "trailer << /Root 1 0 R /Size 6 >>\nstartxref\n0\n%%EOF\n",
    ]
    return "".join(pdf).encode("latin-1", errors="ignore")
