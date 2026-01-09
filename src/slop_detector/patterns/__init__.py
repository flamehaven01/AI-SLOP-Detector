"""Pattern system for AI SLOP Detector v2.1.0"""

from slop_detector.patterns.base import BasePattern, Issue, Severity, Axis
from slop_detector.patterns.registry import PatternRegistry

__all__ = [
    "BasePattern",
    "Issue",
    "Severity",
    "Axis",
    "PatternRegistry",
    "get_all_patterns",
]


def get_all_patterns() -> list[BasePattern]:
    """Get all registered patterns."""
    from slop_detector.patterns.structural import (
        BareExceptPattern,
        MutableDefaultArgPattern,
        StarImportPattern,
        GlobalStatementPattern,
    )
    from slop_detector.patterns.placeholder import (
        PassPlaceholderPattern,
        TodoCommentPattern,
        FixmeCommentPattern,
    )
    from slop_detector.patterns.cross_language import (
        JavaScriptPushPattern,
        JavaEqualsPattern,
        RubyEachPattern,
        GoPrintPattern,
        CSharpLengthPattern,
        PHPStrlenPattern,
    )

    return [
        # Structural (Critical/High)
        BareExceptPattern(),
        MutableDefaultArgPattern(),
        StarImportPattern(),
        GlobalStatementPattern(),
        # Placeholder (High/Medium)
        PassPlaceholderPattern(),
        TodoCommentPattern(),
        FixmeCommentPattern(),
        # Cross-language (High)
        JavaScriptPushPattern(),
        JavaEqualsPattern(),
        RubyEachPattern(),
        GoPrintPattern(),
        CSharpLengthPattern(),
        PHPStrlenPattern(),
    ]
