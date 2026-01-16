"""Consent-based complexity decorators for AI-SLOP Detector.

This module provides decorators that allow developers to explicitly
whitelist intentional complexity, shifting responsibility from the
tool to the sovereign developer.

Version: 2.6.3
"""

from functools import wraps
from typing import Callable, List, Optional, TypeVar

F = TypeVar("F", bound=Callable)

# Registry to track ignored functions at runtime
_IGNORED_FUNCTIONS: dict = {}


class SlopIgnore:
    """Marker class for @slop.ignore decorated functions.

    This decorator signals that a function's complexity is intentional
    and should be excluded from slop analysis.

    Attributes:
        reason: Explanation of why complexity is necessary
        rules: Specific rules to ignore (empty = all rules)
    """

    def __init__(self, reason: str, rules: Optional[List[str]] = None):
        """Initialize the ignore marker.

        Args:
            reason: Required explanation for the complexity
            rules: Optional list of specific rules to ignore
                   (e.g., ["LDR", "INFLATION"]). If empty, ignores all.
        """
        if not reason or not reason.strip():
            raise ValueError("@slop.ignore requires a non-empty 'reason' argument")

        self.reason = reason.strip()
        self.rules = rules or []

    def __call__(self, func: F) -> F:
        """Apply the ignore marker to a function."""
        # Store metadata on the function
        func._slop_ignore = True  # type: ignore
        func._slop_ignore_reason = self.reason  # type: ignore
        func._slop_ignore_rules = self.rules  # type: ignore

        # Register in global registry for AST-independent detection
        func_id = f"{func.__module__}.{func.__qualname__}"
        _IGNORED_FUNCTIONS[func_id] = {
            "reason": self.reason,
            "rules": self.rules,
        }

        @wraps(func)
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)

        # Preserve markers on wrapper
        wrapper._slop_ignore = True  # type: ignore
        wrapper._slop_ignore_reason = self.reason  # type: ignore
        wrapper._slop_ignore_rules = self.rules  # type: ignore

        return wrapper  # type: ignore


def ignore(reason: str, rules: Optional[List[str]] = None) -> SlopIgnore:
    """Decorator to whitelist intentional complexity.

    Use this when a function's complexity is necessary and intentional,
    such as performance-critical algorithms or domain-specific logic.

    Args:
        reason: Required explanation of why complexity is needed
        rules: Optional list of specific rules to ignore
               Valid rules: "LDR", "INFLATION", "DDC", "PLACEHOLDER"
               If empty, all rules are ignored for this function.

    Returns:
        SlopIgnore decorator instance

    Example:
        @slop.ignore(reason="Bitwise optimization for O(1) performance")
        def fast_inverse_sqrt(number):
            # Complex but intentional implementation
            ...

        @slop.ignore(reason="Domain algorithm", rules=["LDR"])
        def complex_calculation():
            # Only ignore LDR check, other rules still apply
            ...

    Raises:
        ValueError: If reason is empty or None
    """
    return SlopIgnore(reason=reason, rules=rules)


def get_ignored_functions() -> dict:
    """Get all registered ignored functions.

    Returns:
        Dictionary mapping function IDs to their ignore metadata
    """
    return _IGNORED_FUNCTIONS.copy()


def is_function_ignored(func: Callable) -> bool:
    """Check if a function has the @slop.ignore decorator.

    Args:
        func: The function to check

    Returns:
        True if function is marked as ignored
    """
    return getattr(func, "_slop_ignore", False)


def get_ignore_reason(func: Callable) -> Optional[str]:
    """Get the ignore reason for a function.

    Args:
        func: The function to check

    Returns:
        The reason string if ignored, None otherwise
    """
    return getattr(func, "_slop_ignore_reason", None)


def get_ignore_rules(func: Callable) -> List[str]:
    """Get the specific rules ignored for a function.

    Args:
        func: The function to check

    Returns:
        List of ignored rules, empty list if all rules ignored
    """
    return getattr(func, "_slop_ignore_rules", [])


# Namespace for clean imports: import slop; @slop.ignore(...)
class _SlopNamespace:
    """Namespace class for slop.ignore syntax."""

    ignore = staticmethod(ignore)


# Create module-level namespace
slop = _SlopNamespace()
