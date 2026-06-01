import py_compile
from pathlib import Path


def test_run_video_trailer_compiles() -> None:
    py_compile.compile("scripts/run_video_trailer.py", doraise=True)


def test_pre_op_payload_preview_uses_escaped_newline() -> None:
    source = Path("scripts/run_video_trailer.py").read_text(encoding="utf-8")

    assert 'logger.debug("[PRE-OP] payload preview:\\n%s", message)' in source
    assert 'payload preview:\n{message}' not in source
