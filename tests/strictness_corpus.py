"""Labeled controls for strictness changes in clone and placeholder families."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


ExpectedDecision = Literal["detected", "not_detected", "informational"]


@dataclass(frozen=True)
class StrictnessCase:
    """A minimal review case with a human-confirmed expected decision."""

    name: str
    family: Literal["clone", "placeholder"]
    expected: ExpectedDecision
    source: str
    rationale: str


STRICTNESS_CASES = (
    StrictnessCase(
        name="alpha_renamed_copy",
        family="clone",
        expected="detected",
        source="""
def score_route(readings, offset):
    tally = offset
    for reading in readings:
        tally = (tally * 31 + reading) % 1_000_003
    return tally


def blend_samples(bucket, origin):
    marker = origin
    for sample in bucket:
        marker = (marker * 31 + sample) % 1_000_003
    return marker
""",
        rationale="Same compiled operation after local-name normalization is real copy-paste evidence.",
    ),
    StrictnessCase(
        name="symmetric_comparators",
        family="clone",
        expected="not_detected",
        source="""
def comes_before(left, right):
    return left.priority < right.priority


def comes_after(left, right):
    return left.priority > right.priority


def ties_with(left, right):
    return left.priority == right.priority


def differs_from(left, right):
    return left.priority != right.priority
""",
        rationale="Symmetric domain comparators share an AST shape but represent distinct public semantics.",
    ),
    StrictnessCase(
        name="declarative_constraint_factories",
        family="clone",
        expected="not_detected",
        source="""
class Constraint:
    def __init__(self, name, field):
        self.name = name
        self.field = field


def required(field):
    return Constraint("required", field)


def numeric(field):
    return Constraint("numeric", field)


def positive(field):
    return Constraint("positive", field)


def bounded(field):
    return Constraint("bounded", field)
""",
        rationale="Declarative factories are intentionally data-distinct even when their control flow is identical.",
    ),
    StrictnessCase(
        name="strategy_check_node_overrides",
        family="clone",
        expected="not_detected",
        source="""
class EmptyPattern:
    def check_node(self, node):
        return node.kind == "empty"


class ReturnPattern:
    def check_node(self, node):
        return node.kind == "return"


class RaisePattern:
    def check_node(self, node):
        return node.kind == "raise"


class PassPattern:
    def check_node(self, node):
        return node.kind == "pass"
""",
        rationale="Same-named strategy overrides are separate polymorphic implementations, not ambiguous duplicates.",
    ),
    StrictnessCase(
        name="protocol_marker",
        family="placeholder",
        expected="not_detected",
        source="""
from typing import Protocol


class Candidate(Protocol):
    def matches(self, value: str) -> bool: ...
""",
        rationale="Protocol ellipses define an interface and are not unfinished implementation.",
    ),
    StrictnessCase(
        name="context_manager_exit",
        family="placeholder",
        expected="not_detected",
        source="""
class TransactionBoundary:
    def __exit__(self, exc_type, exc_value, traceback):
        return False
""",
        rationale="Returning False from __exit__ preserves exception propagation by context-manager contract.",
    ),
)
