import py_compile
from pathlib import Path


def test_run_market_compiles_after_continuity_logging_changes() -> None:
    py_compile.compile(str(Path("scripts/run_market.py")), doraise=True)
