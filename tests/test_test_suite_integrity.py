from __future__ import annotations

import ast
from pathlib import Path

TEST_ROOT = Path(__file__).resolve().parent


def test_top_level_test_function_names_are_unique_per_file() -> None:
    duplicates: dict[str, list[str]] = {}

    for path in sorted(TEST_ROOT.glob("test_*.py")):
        seen: dict[str, int] = {}
        module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

        for node in module.body:
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            if not node.name.startswith("test_"):
                continue

            if node.name in seen:
                duplicates.setdefault(path.name, []).append(
                    f"{node.name} first_line={seen[node.name]} duplicate_line={node.lineno}"
                )
            else:
                seen[node.name] = node.lineno

    assert not duplicates, f"Duplicate top-level test functions found: {duplicates}"
