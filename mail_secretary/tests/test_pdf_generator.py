from app.output.pdf_generator import generate_simple_pdf


def test_generate_simple_pdf_signature() -> None:
    blob = generate_simple_pdf("제목", "본문")
    assert blob.startswith(b"%PDF-")
    assert blob.endswith(b"%%EOF\n")
