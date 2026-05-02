"""Pattern system for AI SLOP Detector v2.1.0"""

from __future__ import annotations

from slop_detector.patterns.base import Axis, BasePattern, Issue, Severity
from slop_detector.patterns.registry import PatternRegistry

__all__ = [
    "BasePattern",
    "Issue",
    "Severity",
    "Axis",
    "PatternRegistry",
    "get_all_patterns",
]


def get_all_patterns(
    god_function_config: dict | None = None,
    nested_complexity_config: dict | None = None,
) -> list[BasePattern]:
    """Get all registered patterns.

    Args:
        god_function_config: Optional dict from Config.get_god_function_config().
            Allows caller to pass per-project god_function thresholds and
            domain_overrides without coupling the pattern module to Config.
        nested_complexity_config: Optional dict from Config.get_nested_complexity_config().
            Allows per-function-name depth/cc threshold overrides for inherently
            complex domain functions (e.g., AST pattern matchers, metric calculators).
    """
    from slop_detector.patterns.cross_language import (
        CSharpLengthPattern,
        GoPrintPattern,
        JavaEqualsPattern,
        JavaScriptPushPattern,
        PHPStrlenPattern,
        RubyEachPattern,
    )
    from slop_detector.patterns.placeholder import (
        EllipsisPlaceholderPattern,
        EmptyExceptPattern,
        FixmeCommentPattern,
        HackCommentPattern,
        InterfaceOnlyClassPattern,
        NotImplementedPattern,
        PassPlaceholderPattern,
        ReturnConstantStubPattern,
        ReturnNonePlaceholderPattern,
        TodoCommentPattern,
        XXXCommentPattern,
    )
    from slop_detector.patterns.python_clones import FunctionClonePattern
    from slop_detector.patterns.python_complexity import (
        DeadCodePattern,
        DeepNestingPattern,
        GodFunctionPattern,
        NestedComplexityPattern,
    )
    from slop_detector.patterns.python_imports import PhantomImportPattern
    from slop_detector.patterns.python_lint import LintEscapePattern
    from slop_detector.patterns.python_naming import PlaceholderVariableNamingPattern
    from slop_detector.patterns.structural import (
        BareExceptPattern,
        GlobalStatementPattern,
        MutableDefaultArgPattern,
        StarImportPattern,
    )

    return [
        # Structural (Critical/High)
        BareExceptPattern(),
        MutableDefaultArgPattern(),
        StarImportPattern(),
        GlobalStatementPattern(),
        # Placeholder (Critical/High/Medium)
        EmptyExceptPattern(),
        NotImplementedPattern(),
        PassPlaceholderPattern(),
        EllipsisPlaceholderPattern(),
        HackCommentPattern(),
        ReturnNonePlaceholderPattern(),
        ReturnConstantStubPattern(),
        TodoCommentPattern(),
        FixmeCommentPattern(),
        InterfaceOnlyClassPattern(),
        XXXCommentPattern(),
        # Cross-language (High)
        JavaScriptPushPattern(),
        JavaEqualsPattern(),
        RubyEachPattern(),
        GoPrintPattern(),
        CSharpLengthPattern(),
        PHPStrlenPattern(),
        # Python Advanced (v2.8.0+)
        GodFunctionPattern(
            complexity_threshold=int((god_function_config or {}).get("complexity_threshold", 10)),
            lines_threshold=int((god_function_config or {}).get("lines_threshold", 50)),
            domain_overrides=(god_function_config or {}).get("domain_overrides", []),
        ),
        DeadCodePattern(),
        DeepNestingPattern(),
        NestedComplexityPattern(
            depth_threshold=int((nested_complexity_config or {}).get("depth_threshold", 4)),
            cc_threshold=int((nested_complexity_config or {}).get("cc_threshold", 5)),
            domain_overrides=(nested_complexity_config or {}).get("domain_overrides", []),
        ),
        LintEscapePattern(),
        # v2.9.0
        PhantomImportPattern(),
        # v3.1.0
        FunctionClonePattern(),
        PlaceholderVariableNamingPattern(),
    ]
