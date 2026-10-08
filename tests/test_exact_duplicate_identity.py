"""Exact duplicates: one body identity and one eligibility floor for both reports.

Identity is the function body only: the leading docstring, the function name,
decorators and annotations are not part of it; parameters and local names are
canonicalized; operators, call targets and attributes are kept, and `def` and
`async def` stay distinct. Eligibility is a separate floor of semantic body
nodes (8), so leaf bodies and single delegating calls are not duplicates. The
same-file pattern (`exact_duplicate_pair`) and the cross-file report use the
same helper. In the dogfood, 59 of 107 same-file groups were single-statement
bodies (9 CRITICAL, among them `pass` x5), while renamed copies across files
were missed because the cross-file hash included the name and docstring.
"""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

from slop_detector.analysis.cross_file import CrossFileAnalyzer, _hash_function_body
from slop_detector.clone_identity import MIN_SEMANTIC_NODES, body_fingerprint
from slop_detector.patterns.python_clones import ExactDuplicatePairPattern

# Metadata that the old whole-definition identity counted toward its 12-node
# floor: annotations and a docstring make a trivial body "big enough".
HEADER = "def {name}(self, key: int, value: int) -> None:\n" '    """{doc}"""\n'


def _pair(body: str, docs=("Doc.", "Doc.")) -> str:
    return "".join(
        HEADER.format(name=name, doc=doc) + body + "\n"
        for name, doc in zip(("first", "second"), docs)
    )


def _issues(source: str):
    return ExactDuplicatePairPattern().check(ast.parse(source), Path("m.py"), source)


def test_pass_body_is_not_a_duplicate():
    assert _issues(_pair("    pass")) == []


def test_raise_not_implemented_is_not_a_duplicate():
    assert _issues(_pair("    raise NotImplementedError")) == []


def test_return_constant_or_name_is_not_a_duplicate():
    assert _issues(_pair("    return 0")) == []
    assert _issues(_pair("    return key")) == []


def test_single_delegating_call_is_not_a_duplicate():
    assert _issues(_pair("    return self._inner.get(key)")) == []


def test_composite_single_expression_is_a_duplicate():
    """Control: one statement, but real composition (16 semantic nodes)."""
    issues = _issues(_pair("    return self.w2(silu(self.w1(key)) * self.w3(value))"))
    assert len(issues) == 1


COMPOSITE = (
    "    total = 0\n" "    for item in key:\n" "        total += item * value\n" "    return total"
)
# The same body written with other parameter and local names.
RENAMED = (
    COMPOSITE.replace("total", "acc")
    .replace("item", "x")
    .replace("key", "rows")
    .replace("value", "factor")
)


def test_different_docstrings_are_the_same_body():
    issues = _issues(_pair(COMPOSITE, docs=("Sum things.", "Another description.")))
    assert len(issues) == 1


def test_different_annotations_are_the_same_body():
    source = (
        "def first(key: int, value: int) -> int:\n" + COMPOSITE + "\n"
        "def second(key: list, value: float) -> float:\n" + COMPOSITE + "\n"
    )
    assert len(_issues(source)) == 1


def test_different_parameter_and_local_names_are_the_same_body():
    source = "def first(key, value):\n" + COMPOSITE + "\ndef second(rows, factor):\n"
    source += RENAMED + "\n"
    assert len(_issues(source)) == 1


def test_different_operator_is_a_different_body():
    source = (
        "def first(key, value):\n" + COMPOSITE + "\n"
        "def second(key, value):\n" + COMPOSITE.replace("item * value", "item + value") + "\n"
    )
    assert _issues(source) == []


def test_different_call_target_is_a_different_body():
    body = "    result = load(key)\n    result.update(value)\n    return result.items()"
    source = (
        "def first(key, value):\n" + body + "\n"
        "def second(key, value):\n" + body.replace("load(", "fetch(") + "\n"
    )
    assert _issues(source) == []


def test_def_and_async_def_are_different_bodies():
    source = (
        "def first(key, value):\n" + COMPOSITE + "\n"
        "async def second(key, value):\n" + COMPOSITE + "\n"
    )
    assert _issues(source) == []


ADAPTER = (
    "    def visit_{kind}(self, node):\n"
    '        """Visit {kind}."""\n'
    "        self._check_patterns(node)\n"
    "        self.generic_visit(node)\n"
)


def _visitor(class_name: str, kinds) -> str:
    return f"class {class_name}(ast.NodeVisitor):\n" + "".join(
        ADAPTER.format(kind=kind) for kind in kinds
    )


def test_visitor_adapter_methods_are_not_duplicates():
    source = _visitor("Analyzer", ("Call", "Import", "ClassDef", "FunctionDef"))
    assert _issues(source) == []


def test_substantive_visitor_duplicates_are_reported():
    method = (
        "    def visit_{kind}(self, node):\n"
        "        if node.lineno > self.limit:\n"
        "            self.findings.append((node.lineno, type(node).__name__))\n"
        "        self.generic_visit(node)\n"
    )
    source = "class Analyzer(ast.NodeVisitor):\n" + "".join(
        method.format(kind=kind) for kind in ("Call", "Import")
    )
    assert len(_issues(source)) == 1


def test_call_only_visitor_methods_without_generic_visit_are_reported():
    source = _visitor("Analyzer", ("Call", "Import")).replace(
        "self.generic_visit(node)", "self._emit(node.lineno)"
    )
    assert len(_issues(source)) == 1


def test_adapter_bodies_across_classes_are_reported():
    source = _visitor("First", ("Call",)) + _visitor("Second", ("Call",))
    assert len(_issues(source)) == 1


def test_adapter_bodies_without_the_visit_prefix_are_reported():
    source = _visitor("Analyzer", ("Call", "Import")).replace("def visit_", "def on_")
    assert len(_issues(source)) == 1


def _function(source: str) -> ast.FunctionDef:
    node = ast.parse(source).body[0]
    assert isinstance(node, ast.FunctionDef)
    return node


def test_cross_file_ignores_name_and_docstring():
    first = _function('def total(key, value):\n    """Sum."""\n' + COMPOSITE)
    second = _function('def accumulate(rows, factor):\n    """Other."""\n' + RENAMED)
    assert _hash_function_body(first) == _hash_function_body(second) != ""


def test_cross_file_skips_bodies_below_the_floor():
    assert _hash_function_body(_function("def stub(self):\n    pass")) == ""


def test_cross_file_and_same_file_share_the_identity():
    func = _function("def total(key, value):\n" + COMPOSITE)
    identity, size = body_fingerprint(func)
    assert size >= MIN_SEMANTIC_NODES
    assert _hash_function_body(func) == identity


def test_cross_file_report_finds_a_renamed_copy(tmp_path):
    (tmp_path / "a.py").write_text("def total(key, value):\n" + COMPOSITE + "\n", "utf-8")
    (tmp_path / "b.py").write_text("def accumulate(rows, factor):\n" + RENAMED + "\n", "utf-8")
    files = [
        SimpleNamespace(file_path=str(p), deficit_score=0.0) for p in sorted(tmp_path.glob("*.py"))
    ]
    report = CrossFileAnalyzer().analyze(str(tmp_path), files)
    assert {(d.func_a, d.func_b) for d in report.duplicates} in (
        {("total", "accumulate")},
        {("accumulate", "total")},
    )
