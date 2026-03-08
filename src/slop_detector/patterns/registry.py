"""Pattern registry for managing detection patterns."""

from __future__ import annotations

from typing import TYPE_CHECKING, Dict, List, Optional, Set

if TYPE_CHECKING:
    from slop_detector.patterns.base import BasePattern


class PatternRegistry:
    """Registry for managing detection patterns."""

    def __init__(self):
        self._patterns: Dict[str, BasePattern] = {}
        self._disabled: Set[str] = set()

    def register(self, pattern: BasePattern) -> None:
        """Register a pattern."""
        if not pattern.id:
            raise ValueError(f"Pattern {pattern} has no ID")

        if pattern.id in self._patterns:
            raise ValueError(f"Pattern {pattern.id} already registered")

        self._patterns[pattern.id] = pattern

    def register_all(self, patterns: List[BasePattern]) -> None:
        """Register multiple patterns."""
        for pattern in patterns:
            self.register(pattern)

    def disable(self, pattern_id: str) -> None:
        """Disable a pattern."""
        self._disabled.add(pattern_id)

    def enable(self, pattern_id: str) -> None:
        """Enable a pattern."""
        self._disabled.discard(pattern_id)

    def get(self, pattern_id: str) -> Optional[BasePattern]:
        """Get a pattern by ID."""
        return self._patterns.get(pattern_id)

    def get_all(self) -> List[BasePattern]:
        """Get all enabled patterns."""
        return [
            pattern
            for pattern_id, pattern in self._patterns.items()
            if pattern_id not in self._disabled
        ]

    def get_by_severity(self, severity: str) -> List[BasePattern]:
        """Get patterns by severity level."""
        return [pattern for pattern in self.get_all() if pattern.severity.value == severity]

    def get_by_axis(self, axis: str) -> List[BasePattern]:
        """Get patterns by axis."""
        return [pattern for pattern in self.get_all() if pattern.axis.value == axis]

    def __len__(self) -> int:
        return len(self._patterns) - len(self._disabled)

    def __repr__(self) -> str:
        return f"PatternRegistry({len(self)} patterns, {len(self._disabled)} disabled)"


# Global registry instance — eagerly initialized at module load
_global_registry: PatternRegistry = PatternRegistry()


def get_global_registry() -> PatternRegistry:
    """Get the global pattern registry."""
    return _global_registry
