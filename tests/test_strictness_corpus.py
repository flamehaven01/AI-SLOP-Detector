"""Structural checks for the labeled strictness corpus."""

from __future__ import annotations

import ast
from pathlib import Path

from tests.strictness_corpus import STRICTNESS_CASES


def test_strictness_corpus_is_parseable_and_has_unique_case_names():
    names = [case.name for case in STRICTNESS_CASES]

    assert len(names) == len(set(names))
    assert {case.family for case in STRICTNESS_CASES} == {"clone", "placeholder"}
    assert {case.expected for case in STRICTNESS_CASES} == {"detected", "not_detected"}
    for case in STRICTNESS_CASES:
        ast.parse(case.source)
        assert case.rationale


def test_clone_evidence_qualifies_same_named_strategy_methods():
    from slop_detector.patterns.python_clones import _qualified_clone_names

    source = next(
        case.source for case in STRICTNESS_CASES if case.name == "strategy_check_node_overrides"
    )
    names = _qualified_clone_names(ast.parse(source), ["check_node"] * 4)

    assert names == [
        "EmptyPattern.check_node",
        "ReturnPattern.check_node",
        "RaisePattern.check_node",
        "PassPattern.check_node",
    ]


def test_strictness_corpus_expected_decisions_hold():
    from slop_detector.patterns.placeholder import (
        EllipsisPlaceholderPattern,
        ReturnConstantStubPattern,
        ReturnNonePlaceholderPattern,
    )
    from slop_detector.patterns.python_clones import ExactDuplicatePairPattern, FunctionClonePattern

    patterns = {
        "clone": [ExactDuplicatePairPattern(), FunctionClonePattern()],
        "placeholder": [
            EllipsisPlaceholderPattern(),
            ReturnConstantStubPattern(),
            ReturnNonePlaceholderPattern(),
        ],
    }
    for case in STRICTNESS_CASES:
        tree = ast.parse(case.source)
        issues = [
            issue
            for pattern in patterns[case.family]
            for issue in pattern.check(tree, Path(f"{case.name}.py"), case.source)
        ]
        if case.expected == "detected":
            assert issues, case.name
        else:
            assert not issues, case.name
