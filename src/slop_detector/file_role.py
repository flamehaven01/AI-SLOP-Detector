"""File Role Classifier — assigns a structural role to a Python source file.

Roles determine which metric checks apply (e.g. INIT files skip LDR/DDC).
This prevents systematic false-positives on legitimate structural patterns.
"""

from __future__ import annotations

import ast
from enum import Enum
from pathlib import Path


class FileRole(Enum):
    SOURCE = "source"  # ordinary source module — full analysis
    INIT = "init"  # __init__.py — skip LDR, skip DDC
    RE_EXPORT = "re_export"  # module whose body is only imports + __all__ — skip DDC
    TEST = "test"  # test file — already excluded by .slopconfig; kept for API
    MODEL = "model"  # dataclass-heavy, minimal function bodies — relax inflation
    CORPUS = "corpus"  # intentional slop corpus (tests/corpus/**) — skip all


# Which metric checks to suppress per role.
# Keys map to the check names used in SlopDetector._calculate_slop_status and callers.
ROLE_SKIP: dict[FileRole, frozenset[str]] = {
    FileRole.SOURCE: frozenset(),
    FileRole.INIT: frozenset({"ldr", "ddc"}),
    FileRole.RE_EXPORT: frozenset({"ddc"}),
    FileRole.TEST: frozenset(),
    FileRole.MODEL: frozenset({"inflation"}),
    # CORPUS: analyzed normally — intentional slop fixtures are excluded during
    # self-scan via exclude_paths in .slopconfig.yaml ("tests/**").
    FileRole.CORPUS: frozenset(),
}


def classify_file(path: str, content: str, tree: ast.AST) -> FileRole:
    """Classify *path* into a FileRole based on its name and AST structure.

    The classification is purely structural and fast — no I/O beyond the
    already-parsed tree.
    """
    p = Path(path)
    parts = {part.lower() for part in p.parts}

    # Corpus: intentional slop living under tests/corpus/
    if "corpus" in parts and ("test" in parts or "tests" in parts):
        return FileRole.CORPUS

    # Test file
    if p.name.startswith("test_") or p.name.endswith("_test.py") or "tests" in parts:
        return FileRole.TEST

    # __init__.py — even if it has some logic, its primary role is re-export
    if p.name == "__init__.py":
        return FileRole.INIT

    # Analyse AST top-level body to determine RE_EXPORT or MODEL
    body_nodes = tree.body  # top-level only — nested stmts must not skew ratios
    if not body_nodes:
        return FileRole.SOURCE

    total = len(body_nodes)
    import_nodes = sum(1 for n in body_nodes if isinstance(n, (ast.Import, ast.ImportFrom)))
    assign_nodes = sum(
        1 for n in body_nodes if isinstance(n, (ast.Assign, ast.AugAssign, ast.AnnAssign))
    )
    func_nodes = sum(
        1 for n in body_nodes if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    )

    # RE_EXPORT: ≥70% of body is import statements (+ optional __all__ assign)
    if total > 0 and (import_nodes + assign_nodes) / total >= 0.70 and func_nodes == 0:
        return FileRole.RE_EXPORT

    # MODEL: dataclass-heavy file — check for @dataclass decorator before RE_EXPORT ratio
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for deco in node.decorator_list:
                name = ""
                if isinstance(deco, ast.Name):
                    name = deco.id
                elif isinstance(deco, ast.Attribute):
                    name = deco.attr
                if name == "dataclass":
                    return FileRole.MODEL

    return FileRole.SOURCE
