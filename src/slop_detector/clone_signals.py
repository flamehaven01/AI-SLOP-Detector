"""Shared clone-pattern identifiers and helpers.

Keeps exact-duplicate and clone-cluster naming aligned across patterns,
cleanup payloads, and human-facing renderers.
"""

from __future__ import annotations

from typing import Any

EXACT_DUPLICATE_PAIR_ID = "exact_duplicate_pair"
FUNCTION_CLONE_CLUSTER_ID = "function_clone_cluster"
CLONE_PATTERN_IDS = frozenset({EXACT_DUPLICATE_PAIR_ID, FUNCTION_CLONE_CLUSTER_ID})


def clone_pattern_id(issue: Any) -> str:
    return str(getattr(issue, "pattern_id", "") or "")


def is_clone_pattern(issue: Any) -> bool:
    return clone_pattern_id(issue) in CLONE_PATTERN_IDS


def is_exact_duplicate_pair(issue: Any) -> bool:
    return clone_pattern_id(issue) == EXACT_DUPLICATE_PAIR_ID
