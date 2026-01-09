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


def get_all_patterns() -> list[BasePattern]:
    """Get all registered patterns."""
    from slop_detector.patterns.cross_language import (
        CSharpLengthPattern,
        GoPrintPattern,
        JavaEqualsPattern,
        JavaScriptPushPattern,
        PHPStrlenPattern,
        RubyEachPattern,
    )
    from slop_detector.patterns.placeholder import (
        FixmeCommentPattern,
        PassPlaceholderPattern,
        TodoCommentPattern,
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
