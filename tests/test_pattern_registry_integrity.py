"""Every concrete pattern class is a default detector (registry integrity).

A concrete pattern class that `get_all_patterns()` does not instantiate is a
detector that never runs, while its id can still appear in docs, autofix, or a
corpus as if it did. Seven such classes sat in the tree from v2.5.0 until the
reconciliation that measured and removed them. A deliberately non-default
pattern needs an explicit mechanism with its own reason and tests, not a
silent orphan class.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
from typing import Set, Type

import slop_detector.patterns as patterns_pkg
from slop_detector.patterns import get_all_patterns
from slop_detector.patterns.base import BasePattern


def _concrete_pattern_classes() -> Set[Type[BasePattern]]:
    found: Set[Type[BasePattern]] = set()
    for info in pkgutil.iter_modules(patterns_pkg.__path__):
        module = importlib.import_module(f"{patterns_pkg.__name__}.{info.name}")
        for _, obj in inspect.getmembers(module, inspect.isclass):
            if (
                issubclass(obj, BasePattern)
                and obj.__module__ == module.__name__
                and getattr(obj, "id", "")
                and not inspect.isabstract(obj)
            ):
                found.add(obj)
    return found


def test_every_concrete_pattern_class_is_a_default_detector():
    default = {type(pattern) for pattern in get_all_patterns()}
    orphans = sorted(cls.__name__ for cls in _concrete_pattern_classes() - default)
    assert orphans == []


def test_the_module_scan_sees_every_default_detector():
    """Guards the guard: a scan that found nothing would pass the test above."""
    default = {type(pattern) for pattern in get_all_patterns()}
    assert default and default <= _concrete_pattern_classes()
