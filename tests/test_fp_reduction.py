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

ANNOTATION_ONLY_SRC = textwrap.dedent(
    """
    import argparse
    import os

    def run(ns: argparse.Namespace) -> None:
        path = os.path.join("/tmp", "out")
        print(path)
"""
).strip()


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

NOQA_REEXPORT_SRC = textwrap.dedent(
    """
    from slop_detector.models import FileAnalysis  # noqa: F401
    from slop_detector.models import SlopStatus  # noqa: F401

    __version__ = "1.0.0"
"""
).strip()


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

ALL_REEXPORT_SRC = textwrap.dedent(
    """
    from slop_detector.models import FileAnalysis
    from slop_detector.models import SlopStatus
    from slop_detector.models import ProjectAnalysis

    __all__ = ["FileAnalysis", "SlopStatus", "ProjectAnalysis"]
"""
).strip()


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

INIT_SRC = textwrap.dedent(
    """
    from .core import SlopDetector
    from .models import FileAnalysis, SlopStatus
    from .config import Config

    __all__ = ["SlopDetector", "FileAnalysis", "SlopStatus", "Config"]
    __version__ = "3.3.0"
"""
).strip()


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

DATACLASS_SRC = textwrap.dedent(
    """
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
"""
).strip()


def test_dataclass_file_classified_as_model():
    tree = ast.parse(DATACLASS_SRC)
    role = classify_file("slop_detector/gate/models.py", DATACLASS_SRC, tree)
    assert role == FileRole.MODEL


CORPUS_SRC = textwrap.dedent(
    """
    # intentional slop for testing
    def foo():
        pass
    def bar():
        pass
"""
).strip()


def test_corpus_file_classified_as_corpus():
    tree = ast.parse(CORPUS_SRC)
    role = classify_file("tests/corpus/slop_example.py", CORPUS_SRC, tree)
    assert role == FileRole.CORPUS


def test_regular_source_classified_as_source():
    src = textwrap.dedent(
        """
        import os
        import sys

        def compute(x: int) -> int:
            return x * os.getpid() + sys.maxsize
    """
    ).strip()
    tree = ast.parse(src)
    role = classify_file("src/mymodule/logic.py", src, tree)
    assert role == FileRole.SOURCE
