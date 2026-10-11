"""File Role Classifier — assigns a structural role to a Python source file.

Roles determine which metric checks apply (e.g. INIT files skip LDR/DDC).
This prevents systematic false-positives on legitimate structural patterns.
"""

from __future__ import annotations

import ast
from enum import Enum
from pathlib import Path
from typing import Optional

from slop_detector.ast_index import walk_nodes
from slop_detector.path_facts import PathFacts, facts_for


class FileRole(Enum):
    SOURCE = "source"  # ordinary source module — full analysis
    INIT = "init"  # __init__.py — skip LDR, skip DDC
    RE_EXPORT = "re_export"  # module whose body is only imports + __all__ — skip DDC
    TEST = "test"  # test file — already excluded by .slopconfig; kept for API
    MODEL = "model"  # has a @dataclass; descriptive only, skips no metric
    CORPUS = "corpus"  # intentional slop corpus (tests/corpus/**) — skip all
    STUB = "stub"  # Protocol/ABC interface stubs — skip LDR (bodies are `...`)


# Which metric checks to suppress per role.
# Keys map to the check names used in SlopDetector._calculate_slop_status and callers.
ROLE_SKIP: dict[FileRole, frozenset[str]] = {
    FileRole.SOURCE: frozenset(),
    FileRole.INIT: frozenset({"ldr", "ddc"}),
    FileRole.RE_EXPORT: frozenset({"ddc"}),
    FileRole.TEST: frozenset(),
    # MODEL skips nothing: jargon counts only in prose and is justified only by
    # structure, so a dataclass is no reason to drop the inflation metric.
    FileRole.MODEL: frozenset(),
    # CORPUS: analyzed normally — intentional slop fixtures are excluded during
    # self-scan via exclude_paths in .slopconfig.yaml ("tests/**").
    FileRole.CORPUS: frozenset(),
    FileRole.STUB: frozenset({"ldr", "patterns"}),
}


def classify_file(
    path: str, content: str, tree: ast.Module, facts: Optional[PathFacts] = None
) -> FileRole:
    """Classify *path* into a FileRole from its path facts and AST structure.

    Path decisions (corpus, test) come only from root-relative path facts
    (slop_detector.path_facts); without `facts` they are derived under the
    single-file root rule. The rest is structural, from the parsed tree.
    """
    p = Path(path)
    facts = facts if facts is not None else facts_for(p)

    # Corpus: intentional slop living under tests/corpus/
    if facts.is_corpus:
        return FileRole.CORPUS

    # Test file
    if facts.is_test:
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
    for node in walk_nodes(tree):
        if isinstance(node, ast.ClassDef):
            for deco in node.decorator_list:
                name = ""
                if isinstance(deco, ast.Name):
                    name = deco.id
                elif isinstance(deco, ast.Attribute):
                    name = deco.attr
                if name == "dataclass":
                    return FileRole.MODEL

    # STUB / INTERFACE: all top-level class definitions inherit from Protocol or ABC
    # and there are no top-level function definitions. These files consist entirely
    # of `...`-body stubs, so LDR is structurally near zero — not a logic deficit.
    _abstract_bases = frozenset({"Protocol", "ABC", "ABCMeta"})

    def _is_abstract_base(node: ast.ClassDef) -> bool:
        for base in node.bases:
            if isinstance(base, ast.Name) and base.id in _abstract_bases:
                return True
            if isinstance(base, ast.Attribute) and base.attr in _abstract_bases:
                return True
        return False

    class_nodes = [n for n in body_nodes if isinstance(n, ast.ClassDef)]
    if class_nodes and func_nodes == 0 and all(_is_abstract_base(c) for c in class_nodes):
        return FileRole.STUB

    return FileRole.SOURCE


# Nodes a static literal may contain (constants, containers of them, signed
# numbers). Anything else -- a name, call, operator, comprehension, f-string,
# unpacking -- is code that runs at import time.
_STATIC_LITERAL_NODES = (
    ast.Constant,
    ast.Dict,
    ast.List,
    ast.Tuple,
    ast.Set,
    ast.Load,
    ast.UnaryOp,
    ast.USub,
    ast.UAdd,
)


def _is_static_literal(value: ast.expr) -> bool:
    for node in ast.walk(value):
        if not isinstance(node, _STATIC_LITERAL_NODES):
            return False
        if isinstance(node, ast.UnaryOp) and not (
            isinstance(node.operand, ast.Constant)
            and isinstance(node.operand.value, (int, float, complex))
        ):
            return False
        # `**` in a dict display has no node of its own (its key is None), so a
        # literal unpacked into a literal passes the node check above.
        if isinstance(node, ast.Dict) and None in node.keys:
            return False
    return True


def is_static_literal_module(tree: ast.Module) -> bool:
    """True when the module is data, not code: only a module docstring,
    leading `from __future__` directives and assignments of static literals
    to plain names, at least one of them.

    Decided from the AST alone (nothing is evaluated). Such a module has no
    logic for the analysis to judge, so its score says nothing about code.
    A __future__ import is a compiler directive, not a dependency.
    """
    body = list(tree.body)
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
        if isinstance(body[0].value.value, str):
            body = body[1:]
    while (
        body
        and isinstance(body[0], ast.ImportFrom)
        and body[0].module == "__future__"
        and body[0].level == 0
    ):
        body = body[1:]
    if not body:
        return False
    return all(
        isinstance(stmt, ast.Assign)
        and all(isinstance(target, ast.Name) for target in stmt.targets)
        and _is_static_literal(stmt.value)
        for stmt in body
    )
