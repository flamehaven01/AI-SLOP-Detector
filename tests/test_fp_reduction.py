"""Phase 1 False-Positive reduction tests (v3.3.0).

Each test documents a known FP pattern and asserts it is now CLEAN.
Run with:  pytest tests/test_fp_reduction.py -v
"""

from __future__ import annotations

import ast
import textwrap

import pytest

from slop_detector.core import SlopDetector
from slop_detector.file_role import FileRole, classify_file
from slop_detector.metrics.ddc import DDCCalculator
from slop_detector.models import SlopStatus

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def detector():
    return SlopDetector()


@pytest.fixture
def ddc():
    from slop_detector.config import Config

    return DDCCalculator(Config())


# ---------------------------------------------------------------------------
# ① Annotation-only import — argparse.Namespace style FP
# ---------------------------------------------------------------------------

ANNOTATION_ONLY_SRC = textwrap.dedent("""
    import argparse
    import os

    def run(ns: argparse.Namespace) -> None:
        path = os.path.join("/tmp", "out")
        print(path)
""").strip()


def test_annotation_only_import_not_flagged_as_unused(ddc):
    """argparse used only in a type hint must NOT appear in ddc.unused."""
    tree = ast.parse(ANNOTATION_ONLY_SRC)
    result = ddc.calculate("<test>", ANNOTATION_ONLY_SRC, tree)
    assert (
        "argparse" not in result.unused
    ), f"argparse is used in a type annotation but was flagged unused: {result.unused}"


def test_annotation_only_import_usage_ratio_is_perfect(ddc):
    """usage_ratio must be 1.0 when all imports are used (some via annotations)."""
    tree = ast.parse(ANNOTATION_ONLY_SRC)
    result = ddc.calculate("<test>", ANNOTATION_ONLY_SRC, tree)
    assert result.usage_ratio == 1.0, f"Expected 1.0, got {result.usage_ratio}"


def test_annotation_only_file_is_clean(detector):
    """End-to-end: file using imports only in annotations must be CLEAN."""
    result = detector.analyze_code_string(ANNOTATION_ONLY_SRC, filename="test_annot.py")
    assert (
        result.status == SlopStatus.CLEAN
    ), f"Expected CLEAN, got {result.status}. warnings={result.warnings}"


# ---------------------------------------------------------------------------
# ② noqa: F401 — re-export pattern
# ---------------------------------------------------------------------------

NOQA_REEXPORT_SRC = textwrap.dedent("""
    from slop_detector.models import FileAnalysis  # noqa: F401
    from slop_detector.models import SlopStatus  # noqa: F401

    __version__ = "1.0.0"
""").strip()


def test_noqa_f401_imports_not_flagged(ddc):
    """Imports marked # noqa: F401 must not appear in ddc.unused."""
    tree = ast.parse(NOQA_REEXPORT_SRC)
    result = ddc.calculate("<test>", NOQA_REEXPORT_SRC, tree)
    assert not result.unused, f"Expected no unused imports, got: {result.unused}"


def test_noqa_f401_usage_ratio_is_perfect(ddc):
    tree = ast.parse(NOQA_REEXPORT_SRC)
    result = ddc.calculate("<test>", NOQA_REEXPORT_SRC, tree)
    assert result.usage_ratio == 1.0


# ---------------------------------------------------------------------------
# ③ __all__ re-export module
# ---------------------------------------------------------------------------

ALL_REEXPORT_SRC = textwrap.dedent("""
    from slop_detector.models import FileAnalysis
    from slop_detector.models import SlopStatus
    from slop_detector.models import ProjectAnalysis

    __all__ = ["FileAnalysis", "SlopStatus", "ProjectAnalysis"]
""").strip()


def test_all_reexport_imports_not_flagged(ddc):
    """Imports listed in __all__ must not appear in ddc.unused."""
    tree = ast.parse(ALL_REEXPORT_SRC)
    result = ddc.calculate("<test>", ALL_REEXPORT_SRC, tree)
    assert not result.unused, f"Expected no unused imports, got: {result.unused}"


def test_all_reexport_file_is_clean(detector):
    """Re-export module must be CLEAN end-to-end."""
    result = detector.analyze_code_string(ALL_REEXPORT_SRC, filename="my_exports.py")
    assert (
        result.status == SlopStatus.CLEAN
    ), f"Expected CLEAN, got {result.status}. warnings={result.warnings}"


# ---------------------------------------------------------------------------
# ④ __init__.py — LDR + DDC checks suppressed
# ---------------------------------------------------------------------------

INIT_SRC = textwrap.dedent("""
    from .core import SlopDetector
    from .models import FileAnalysis, SlopStatus
    from .config import Config

    __all__ = ["SlopDetector", "FileAnalysis", "SlopStatus", "Config"]
    __version__ = "3.3.0"
""").strip()


def test_init_file_classified_as_init():
    tree = ast.parse(INIT_SRC)
    role = classify_file("slop_detector/__init__.py", INIT_SRC, tree)
    assert role == FileRole.INIT


def test_init_file_is_clean(detector):
    """__init__.py with only imports + __all__ must be CLEAN."""
    result = detector.analyze_code_string(INIT_SRC, filename="slop_detector/__init__.py")
    assert (
        result.status == SlopStatus.CLEAN
    ), f"Expected CLEAN, got {result.status}. warnings={result.warnings}"


# ---------------------------------------------------------------------------
# ⑤ File Role Classifier
# ---------------------------------------------------------------------------

DATACLASS_SRC = textwrap.dedent("""
    from dataclasses import dataclass, field
    from typing import List

    @dataclass
    class GateResult:
        passed: bool
        score: float
        issues: List[str] = field(default_factory=list)

    @dataclass
    class GateThresholds:
        max_deficit: float = 30.0
        min_ldr: float = 0.40
""").strip()


def test_dataclass_file_classified_as_model():
    tree = ast.parse(DATACLASS_SRC)
    role = classify_file("slop_detector/gate/models.py", DATACLASS_SRC, tree)
    assert role == FileRole.MODEL


CORPUS_SRC = textwrap.dedent("""
    # intentional slop for testing
    def foo():
        pass
    def bar():
        pass
""").strip()


def test_corpus_file_classified_as_corpus():
    tree = ast.parse(CORPUS_SRC)
    role = classify_file("tests/corpus/slop_example.py", CORPUS_SRC, tree)
    assert role == FileRole.CORPUS


def test_regular_source_classified_as_source():
    src = textwrap.dedent("""
        import os
        import sys

        def compute(x: int) -> int:
            return x * os.getpid() + sys.maxsize
    """).strip()
    tree = ast.parse(src)
    role = classify_file("src/mymodule/logic.py", src, tree)
    assert role == FileRole.SOURCE


# ---------------------------------------------------------------------------
# ⑥ Protocol / ABC stub file — STUB role (v3.4.1)
# ---------------------------------------------------------------------------

PROTOCOL_STUB_SRC = textwrap.dedent("""
    from typing import Any, Protocol

    class BuilderA(Protocol):
        def __call__(self, *, subject: Any, gate: str) -> list[Any]: ...

    class BuilderB(Protocol):
        def __call__(self, *, subject: Any, source: str) -> list[Any]: ...

    class Checker(Protocol):
        def __call__(self, text: str) -> tuple[int, list[str]]: ...
""").strip()


def test_protocol_stub_classified_as_stub():
    """Pure Protocol-stub files must be classified as STUB."""
    tree = ast.parse(PROTOCOL_STUB_SRC)
    role = classify_file("src/mymodule/interfaces.py", PROTOCOL_STUB_SRC, tree)
    assert role == FileRole.STUB, f"Expected STUB, got {role}"


# ---------------------------------------------------------------------------
# ⑦ phantom_import: sibling-module discovery (v3.7.4 regression)
# ---------------------------------------------------------------------------
# Flat-module projects (no pyproject.toml / __init__.py) import sibling .py
# files directly.  The detector must not flag them as phantom imports.


def test_sibling_module_not_flagged_as_phantom(tmp_path):
    """Sibling .py files in same directory must not be flagged as phantom imports."""
    from slop_detector.patterns.python_imports import PhantomImportPattern

    helper = tmp_path / "my_helper.py"
    helper.write_text("def greet(): return 'hi'", encoding="utf-8")

    src = "from my_helper import greet\n\ndef run():\n    return greet()\n"
    target = tmp_path / "main.py"
    target.write_text(src, encoding="utf-8")

    tree = ast.parse(src)
    issues = PhantomImportPattern().check(tree, target, src)
    phantom_ids = [i.pattern_id for i in issues if i.pattern_id == "phantom_import"]
    assert not phantom_ids, f"Sibling module 'my_helper' must not be a phantom: {issues}"


def test_phantom_import_allowlist_respected(tmp_path):
    """Modules in the allowlist must never be flagged as phantom imports."""
    from slop_detector.patterns.python_imports import PhantomImportPattern

    src = "import totally_nonexistent_pkg\nimport another_fake_pkg\n"
    target = tmp_path / "script.py"
    target.write_text(src, encoding="utf-8")

    tree = ast.parse(src)
    pattern_with_allowlist = PhantomImportPattern(allowlist=["totally_nonexistent_pkg"])
    issues = pattern_with_allowlist.check(tree, target, src)

    flagged_names = {i.message for i in issues}
    assert not any(
        "totally_nonexistent_pkg" in m for m in flagged_names
    ), "Allowlisted module must not be flagged"
    assert any(
        "another_fake_pkg" in m for m in flagged_names
    ), "Non-allowlisted phantom must still be flagged"


def test_discover_sibling_modules_returns_stems(tmp_path):
    """_discover_sibling_modules returns stem names of sibling .py files."""
    from slop_detector.patterns.python_imports import _discover_sibling_modules

    (tmp_path / "alpha.py").write_text("x = 1", encoding="utf-8")
    (tmp_path / "beta.py").write_text("y = 2", encoding="utf-8")
    (tmp_path / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "readme.md").write_text("hi", encoding="utf-8")

    target = tmp_path / "main.py"
    target.write_text("", encoding="utf-8")
    siblings = _discover_sibling_modules(target)

    assert "alpha" in siblings
    assert "beta" in siblings
    assert "__init__" not in siblings, "__init__ should be excluded"
    assert "readme" not in siblings, "non-.py files must not appear"


def test_protocol_stub_is_clean(detector):
    """Protocol stub files must be CLEAN — ellipsis bodies and clone patterns are expected."""
    result = detector.analyze_code_string(PROTOCOL_STUB_SRC, filename="interfaces.py")
    assert (
        result.status == SlopStatus.CLEAN
    ), f"Expected CLEAN, got {result.status}. warnings={result.warnings}"


# ---------------------------------------------------------------------------
# ⑦ Domain terminology — proof/lemma/theorem are math vocabulary, not slop
# ---------------------------------------------------------------------------

PROOF_DOMAIN_SRC = textwrap.dedent("""
    from __future__ import annotations
    from pathlib import Path
    import json

    # Single source of truth — imported by proof_audit_probe.py and conftest.py
    PROOF_DIR: str = "proofs"
    LEMMA_SCHEMA_VERSION = "1.0"

    def load_proof(path: Path) -> dict:
        \"\"\"Load a proof bundle from disk.\"\"\"
        with open(path) as f:
            return json.load(f)

    def validate_lemma(lemma: dict) -> bool:
        \"\"\"Check lemma schema version.\"\"\"
        return lemma.get("version") == LEMMA_SCHEMA_VERSION

    def emit_theorem_record(theorem_id: str, proof: dict) -> dict:
        \"\"\"Emit an audit record for a verified theorem.\"\"\"
        return {"id": theorem_id, "proof": proof}
""").strip()


def test_proof_domain_terms_not_flagged_as_jargon():
    """proof/lemma/theorem are domain vocabulary in formal-methods code, not inflation."""
    import ast as _ast

    from slop_detector.config import Config
    from slop_detector.metrics.inflation import InflationCalculator

    tree = _ast.parse(PROOF_DOMAIN_SRC)
    calc = InflationCalculator(Config())
    result = calc.calculate("proof_custody.py", PROOF_DOMAIN_SRC, tree)
    academic_hits = [d for d in result.jargon_details if d["category"] == "academic"]
    assert academic_hits == [], f"Unexpected academic jargon hits: {academic_hits}"


def test_proof_filename_in_comment_not_matched():
    """'proof_audit_probe.py' in a comment must not trigger the 'proof' jargon signal."""
    import ast as _ast

    from slop_detector.config import Config
    from slop_detector.metrics.inflation import InflationCalculator

    src = textwrap.dedent("""
        # Imported by proof_audit_probe.py and tap_autoloop.py
        README_CANDIDATES = ["README.md", "docs/index.md"]
        PROOF_DIR = "proofs"
    """).strip()
    tree = _ast.parse(src)
    calc = InflationCalculator(Config())
    result = calc.calculate("shared.py", src, tree)
    assert result.inflation_score < 1.0, (
        f"inflation_score={result.inflation_score:.3f} — filename reference in comment "
        f"should not trigger jargon: {result.jargon_details}"
    )


# ---------------------------------------------------------------------------
# ⑧ CLI dispatcher — cmd_* functions with dispatch table must not clone-flag
# ---------------------------------------------------------------------------

CLI_DISPATCHER_SRC = textwrap.dedent("""
    import argparse

    def cmd_init(args: argparse.Namespace) -> int:
        print("init")
        return 0

    def cmd_status(args: argparse.Namespace) -> int:
        print("status")
        return 0

    def cmd_probe(args: argparse.Namespace) -> int:
        print("probe")
        return 0

    def cmd_apply(args: argparse.Namespace) -> int:
        print("apply")
        return 0

    def cmd_pack(args: argparse.Namespace) -> int:
        print("pack")
        return 0

    def cmd_release(args: argparse.Namespace) -> int:
        print("release")
        return 0

    def main() -> int:
        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="command")
        sub.add_parser("init")
        sub.add_parser("status")
        sub.add_parser("probe")
        sub.add_parser("apply")
        sub.add_parser("pack")
        sub.add_parser("release")
        args = parser.parse_args()
        dispatch = {
            "init": cmd_init,
            "status": cmd_status,
            "probe": cmd_probe,
            "apply": cmd_apply,
            "pack": cmd_pack,
            "release": cmd_release,
        }
        return dispatch[args.command](args)
""").strip()


def test_cli_dispatcher_not_flagged_as_clone_cluster():
    """cmd_* functions dispatched via a table must not trigger function_clone_cluster."""
    import ast as _ast

    from slop_detector.patterns.python_clones import FunctionClonePattern

    tree = _ast.parse(CLI_DISPATCHER_SRC)
    pattern = FunctionClonePattern()
    issues = pattern.check(tree, "cli.py", CLI_DISPATCHER_SRC)
    clone_issues = [i for i in issues if i.pattern_id == "function_clone_cluster"]
    assert (
        clone_issues == []
    ), f"CLI dispatcher pattern wrongly flagged as clone cluster: {[i.message for i in clone_issues]}"


# ---------------------------------------------------------------------------
# ⑨ Argparse god function — declarative setup with complexity < 4 must not fire
# ---------------------------------------------------------------------------

ARGPARSE_MAIN_SRC = textwrap.dedent("""
    import argparse
    import sys

    def main() -> int:
        parser = argparse.ArgumentParser(description="TAP CLI")
        sub = parser.add_subparsers(dest="command", required=True)

        p_init = sub.add_parser("init", help="Initialise")
        p_init.add_argument("--target", default=".")
        p_init.add_argument("--force", action="store_true")

        p_status = sub.add_parser("status", help="Show status")
        p_status.add_argument("--verbose", action="store_true")
        p_status.add_argument("--format", choices=["text", "json"], default="text")

        p_probe = sub.add_parser("probe", help="Run probe")
        p_probe.add_argument("--timeout", type=int, default=60)
        p_probe.add_argument("--dry-run", action="store_true")

        p_apply = sub.add_parser("apply", help="Apply changes")
        p_apply.add_argument("--patch", required=True)
        p_apply.add_argument("--confirm", action="store_true")

        p_pack = sub.add_parser("pack", help="Pack bundle")
        p_pack.add_argument("--output", default="dist/")
        p_pack.add_argument("--sign", action="store_true")

        p_release = sub.add_parser("release", help="Release")
        p_release.add_argument("--version", required=True)
        p_release.add_argument("--tag", action="store_true")
        p_release.add_argument("--push", action="store_true")

        p_ribbon = sub.add_parser("ribbon", help="Ribbon")
        p_ribbon.add_argument("--chain", default="main")

        p_propose = sub.add_parser("propose", help="Propose")
        p_propose.add_argument("--title", required=True)
        p_propose.add_argument("--body", default="")
        p_propose.add_argument("--draft", action="store_true")

        args = parser.parse_args()
        return 0

    if __name__ == "__main__":
        sys.exit(main())
""").strip()


def test_argparse_main_not_flagged_as_god_function():
    """main() dominated by argparse declarations (complexity < 4) must not fire god_function."""
    import ast as _ast
    from pathlib import Path

    from slop_detector.patterns.python_complexity import GodFunctionPattern

    tree = _ast.parse(ARGPARSE_MAIN_SRC)
    pattern = GodFunctionPattern()
    issues = pattern.check(tree, Path("cli.py"), ARGPARSE_MAIN_SRC)
    god_issues = [i for i in issues if i.pattern_id == "god_function" and "main" in i.message]
    assert (
        god_issues == []
    ), f"Argparse-heavy main() wrongly flagged: {[i.message for i in god_issues]}"


# ---------------------------------------------------------------------------
# ⑩ ABC / abstract method FP suite (v3.7.4)
# ---------------------------------------------------------------------------

ABC_STUB_SRC = textwrap.dedent("""
    from abc import ABC, abstractmethod
    from typing import Optional

    class MetadataStore(ABC):
        @abstractmethod
        def ensure_store(self, name: str) -> None: ...

        @abstractmethod
        def add_doc(self, store_name: str, doc: dict) -> None: ...

        @abstractmethod
        def find_docs(self, store_name: str, query: dict) -> list: ...

    class NullIAMProvider(ABC):
        @abstractmethod
        def validate_admin_token(self, token: str) -> Optional[str]:
            return None

    class ConcreteStore(MetadataStore):
        def ensure_store(self, name: str) -> None:
            pass

        def add_doc(self, store_name: str, doc: dict) -> None:
            pass

        def find_docs(self, store_name: str, query: dict) -> list:
            return []
""").strip()


def test_abstract_ellipsis_not_flagged_as_ellipsis_placeholder():
    """@abstractmethod with ... body must NOT trigger ellipsis_placeholder."""
    import ast as _ast
    from pathlib import Path

    from slop_detector.patterns.placeholder import EllipsisPlaceholderPattern

    tree = _ast.parse(ABC_STUB_SRC)
    pattern = EllipsisPlaceholderPattern()
    issues = pattern.check(tree, Path("storage.py"), ABC_STUB_SRC)
    assert issues == [], f"Abstract ellipsis stubs wrongly flagged: {[i.message for i in issues]}"


def test_abstract_class_not_flagged_as_interface_only():
    """ABC with all @abstractmethod methods must NOT trigger interface_only_class."""
    import ast as _ast
    from pathlib import Path

    from slop_detector.patterns.placeholder import InterfaceOnlyClassPattern

    tree = _ast.parse(ABC_STUB_SRC)
    pattern = InterfaceOnlyClassPattern()
    issues = pattern.check(tree, Path("storage.py"), ABC_STUB_SRC)
    abc_issues = [
        i for i in issues if "MetadataStore" in i.message or "NullIAMProvider" in i.message
    ]
    assert (
        abc_issues == []
    ), f"Abstract base class wrongly flagged as interface_only: {[i.message for i in abc_issues]}"


def test_optional_return_none_not_flagged_as_placeholder():
    """Function returning None with Optional[T] annotation must NOT trigger return_none_placeholder."""
    import ast as _ast
    from pathlib import Path

    from slop_detector.patterns.placeholder import ReturnNonePlaceholderPattern

    tree = _ast.parse(ABC_STUB_SRC)
    pattern = ReturnNonePlaceholderPattern()
    issues = pattern.check(tree, Path("auth.py"), ABC_STUB_SRC)
    assert (
        issues == []
    ), f"Optional-annotated return None wrongly flagged: {[i.message for i in issues]}"


def test_abstract_methods_excluded_from_clone_cluster():
    """ABC with 6 @abstractmethod stubs must NOT generate a clone cluster."""
    import ast as _ast

    from slop_detector.patterns.python_clones import FunctionClonePattern

    src = textwrap.dedent("""
        from abc import ABC, abstractmethod

        class BigInterface(ABC):
            @abstractmethod
            def op_alpha(self) -> None: ...

            @abstractmethod
            def op_beta(self) -> None: ...

            @abstractmethod
            def op_gamma(self) -> None: ...

            @abstractmethod
            def op_delta(self) -> None: ...

            @abstractmethod
            def op_epsilon(self) -> None: ...

            @abstractmethod
            def op_zeta(self) -> None: ...

        def real_work(x: int) -> int:
            total = 0
            for i in range(x):
                total += i * i
            return total
    """).strip()

    tree = _ast.parse(src)
    pattern = FunctionClonePattern()
    issues = pattern.check(tree, "interfaces.py", src)
    clone_issues = [i for i in issues if i.pattern_id == "function_clone_cluster"]
    assert (
        clone_issues == []
    ), f"Abstract method stubs wrongly triggered clone cluster: {[i.message for i in clone_issues]}"


def test_fastapi_router_not_flagged_as_clone_cluster():
    """FastAPI route handlers sharing try/except+HTTPException structure must not be clone-flagged."""
    import ast as _ast

    from slop_detector.patterns.python_clones import FunctionClonePattern

    src = textwrap.dedent("""
        from fastapi import APIRouter, HTTPException

        router = APIRouter()

        @router.get("/items/{item_id}")
        async def get_item(item_id: int):
            try:
                return {"id": item_id}
            except Exception:
                raise HTTPException(status_code=404)

        @router.post("/items")
        async def create_item(data: dict):
            try:
                return {"created": True}
            except Exception:
                raise HTTPException(status_code=400)

        @router.put("/items/{item_id}")
        async def update_item(item_id: int, data: dict):
            try:
                return {"updated": item_id}
            except Exception:
                raise HTTPException(status_code=404)

        @router.delete("/items/{item_id}")
        async def delete_item(item_id: int):
            try:
                return {"deleted": item_id}
            except Exception:
                raise HTTPException(status_code=404)

        @router.get("/users")
        async def list_users():
            try:
                return []
            except Exception:
                raise HTTPException(status_code=500)

        @router.post("/users")
        async def create_user(data: dict):
            try:
                return {"created": True}
            except Exception:
                raise HTTPException(status_code=400)
    """).strip()

    tree = _ast.parse(src)
    pattern = FunctionClonePattern()
    issues = pattern.check(tree, "api.py", src)
    clone_issues = [i for i in issues if i.pattern_id == "function_clone_cluster"]
    assert (
        clone_issues == []
    ), f"FastAPI router wrongly flagged as clone cluster: {[i.message for i in clone_issues]}"


def test_extras_declared_optional_dep_not_flagged_as_phantom():
    """psycopg[binary] in optional-deps: 'import psycopg' must not be flagged when declared."""
    from slop_detector.patterns.python_imports import _add_dep_names

    packages: set = set()
    _add_dep_names(["psycopg[binary]>=3.1.0", "psycopg2-binary>=2.9"], packages)
    assert (
        "psycopg" in packages
    ), f"psycopg not extracted from 'psycopg[binary]>=3.1.0': packages={packages}"
    assert (
        "psycopg2_binary" in packages or "psycopg2" in packages
    ), f"psycopg2 variant not extracted from 'psycopg2-binary>=2.9': packages={packages}"
