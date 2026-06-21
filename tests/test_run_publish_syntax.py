import py_compile
from pathlib import Path


def test_run_publish_compiles_after_channel_gate_changes() -> None:
    """Guard the STEP_8 publish script against malformed nested channel gates."""
    py_compile.compile(str(Path("scripts/run_publish.py")), doraise=True)
