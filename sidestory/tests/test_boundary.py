"""DR-1..DR-4 import boundary (also the repo-split readiness check)."""
from __future__ import annotations

import ast
from pathlib import Path

from sidestory.tests.conftest import REPO_ROOT, SIDE_ROOT

ICG_ADAPTER = SIDE_ROOT / "adapters" / "icg"
# Vendor list for the future split. Keep in sync with adapters/icg/__init__.py.
ALLOWED_ENGINE_SYMBOLS = {
    "engine.image.gemini_client": {"generate_panel"},
    "engine.image.generation_guard": {"GenerationHold"},
    "engine.assembly.pil_composer": {"compose_episode"},
    "engine.narrative.claude_client": {"_extract_json", "_build_messages_create_kwargs"},
}


def _imports(path: Path) -> list[tuple[str, set[str]]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[tuple[str, set[str]]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found += [(alias.name, set()) for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.append((node.module, {alias.name for alias in node.names}))
    return found


def _py_files(root: Path) -> list[Path]:
    return [p for p in root.rglob("*.py") if "__pycache__" not in p.parts]


def test_dr1_main_never_imports_sidestory() -> None:
    offenders = []
    for top in ("engine", "scripts"):
        for path in _py_files(REPO_ROOT / top):
            for module, _ in _imports(path):
                if module == "sidestory" or module.startswith("sidestory."):
                    offenders.append(f"{path.relative_to(REPO_ROOT)} -> {module}")
    for path in REPO_ROOT.glob("*.py"):
        for module, _ in _imports(path):
            if module.startswith("sidestory"):
                offenders.append(f"{path.name} -> {module}")
    assert not offenders, offenders


def test_dr2_dr3_engine_imports_only_in_icg_adapter_and_whitelisted() -> None:
    offenders = []
    for path in _py_files(SIDE_ROOT):
        if "tests" in path.relative_to(SIDE_ROOT).parts:
            continue
        for module, names in _imports(path):
            if not (module == "engine" or module.startswith("engine.")):
                continue
            if ICG_ADAPTER not in path.parents:
                offenders.append(f"DR-2 {path.relative_to(REPO_ROOT)} -> {module}")
                continue
            allowed = ALLOWED_ENGINE_SYMBOLS.get(module)
            if allowed is None or not names or not names <= allowed:
                offenders.append(f"DR-3 {path.relative_to(REPO_ROOT)} -> {module}:{sorted(names)}")
    assert not offenders, offenders


def test_dr4_no_direct_main_schema_access() -> None:
    offenders = []
    for path in _py_files(SIDE_ROOT):
        if "tests" in path.relative_to(SIDE_ROOT).parts:
            continue
        text = path.read_text(encoding="utf-8")
        if 'schema("icg")' in text or "schema('icg')" in text or "icg_table(" in text:
            offenders.append(str(path.relative_to(REPO_ROOT)))
    assert not offenders, offenders


def test_split_ready_no_relative_escape() -> None:
    """Side code must not reach outside its package via relative imports."""
    for path in _py_files(SIDE_ROOT):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.level > 0:
                raise AssertionError(f"relative import in {path}")
