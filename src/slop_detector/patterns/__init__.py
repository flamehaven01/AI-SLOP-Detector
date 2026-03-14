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


def get_all_patterns(god_function_config: dict | None = None) -> list[BasePattern]:
    """Get all registered patterns.

    Args:
        god_function_config: Optional dict from Config.get_god_function_config().
            Allows caller to pass per-project god_function thresholds and
            domain_overrides without coupling the pattern module to Config.
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
    from slop_detector.patterns.python_advanced import (  # v2.8.0+
        DeadCodePattern,
        DeepNestingPattern,
        GodFunctionPattern,
        LintEscapePattern,
        NestedComplexityPattern,
        PhantomImportPattern,
    )
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
        NestedComplexityPattern(),
        LintEscapePattern(),
        # v2.9.0
        PhantomImportPattern(),
    ]
