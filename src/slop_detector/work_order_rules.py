"""The work-order ruleset (S0-P1): every rule an agent reads in the AI report
and the work order, as a versioned JSON file checked against its schema.

Schema /2 keeps the common rules free of any authority to change code and
puts what a reader may do in its mode: `auditor` (read-only, evidence
excerpts and their limits) or `agent` (no code copied, a source recheck per
item, preconditions that start NOT-MEASURED, changes only after approval).

The digest is the SHA-256 of the canonical JSON (keys sorted, no spaces): a
change to any rule changes it, a change of layout does not. A missing,
unreadable or invalid ruleset raises RulesetInvalidError; there is no default
text to fall back on, so a report is never written under unchecked rules.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    model_validator,
)
from typing_extensions import Annotated, Literal

RULESET_PATH = Path(__file__).parent / "config" / "work_order_rules.json"
SCHEMA = "ai-slop-work-order-rules/2"
MODES = ("auditor", "agent")

Text = Annotated[str, StringConstraints(min_length=1)]


class RulesetInvalidError(RuntimeError):
    """The ruleset is missing, unreadable or fails its schema."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Prove(_Strict):
    suggestion: Text
    expect: Text


class Verify(_Strict):
    FINDING: Text
    REVIEW_CANDIDATE: Text


class Claim(_Strict):
    rules_line: Text
    question: Text  # format fields: looked_for, why, resolves


class Auditor(_Strict):
    purpose: Text
    authority: Text
    code: Literal["excerpt"]
    allowed: List[Text] = Field(min_length=1)
    limits: List[Text] = Field(min_length=1)


class Agent(_Strict):
    purpose: Text
    authority: Text
    code: Literal["locator"]
    preconditions: List[Annotated[str, StringConstraints(pattern=r"^P[0-9]+ .+")]] = Field(
        min_length=1
    )
    precondition_rule: Text
    read: Annotated[str, StringConstraints(pattern=r".*[{]file[}].*[{]span[}].*")]
    allowed: List[Text] = Field(min_length=1)


class Modes(_Strict):
    auditor: Auditor
    agent: Agent


class Family(_Strict):
    rules: List[Text] = Field(min_length=1)
    question: Text


class Ruleset(_Strict):
    schema_: Literal["ai-slop-work-order-rules/2"] = Field(alias="schema")
    version: Annotated[str, StringConstraints(pattern=r"^[0-9]+[.][0-9]+[.][0-9]+$")]
    precedence: Text
    tags: Text
    empty_values: Text
    self_falsifier: Text
    loop: List[Text] = Field(min_length=1)
    verify_step: Text
    hold_if: List[Text] = Field(min_length=1)
    hard_stop: List[Text] = Field(min_length=1)
    forbid: List[Text] = Field(min_length=1)
    invariants: List[Text] = Field(min_length=1)
    prove: Prove
    verify: Verify
    claim: Claim
    families: Dict[Text, Family] = Field(min_length=1)
    modes: Modes

    @model_validator(mode="after")
    def _one_family_per_rule(self) -> "Ruleset":
        seen: Dict[str, str] = {}
        for name, family in self.families.items():
            for rule in family.rules:
                if rule in seen:
                    raise ValueError(
                        f"rule {rule!r} is in two families: {seen[rule]!r} and {name!r}"
                    )
                seen[rule] = name
        return self

    def question(self, rule: str, kind: str) -> str:
        """The VERIFY question for a rule; the kind's question when no family names it."""
        for family in self.families.values():
            if rule in family.rules:
                return family.question
        return getattr(self.verify, kind)


def canonical_digest(data: Any) -> str:
    text = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_ruleset(path: Optional[Path] = None) -> Tuple[Ruleset, str]:
    """(ruleset, canonical digest); RulesetInvalidError when it cannot be trusted."""
    source = Path(path) if path is not None else RULESET_PATH
    try:
        data = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RulesetInvalidError(
            f"the work-order ruleset {source.name} cannot be read: {type(exc).__name__}"
        ) from exc
    try:
        ruleset = Ruleset.model_validate(data)
    except ValidationError as exc:
        raise RulesetInvalidError(
            f"the work-order ruleset fails its schema: {exc.error_count()} error(s)"
        ) from exc
    return ruleset, canonical_digest(data)


def header_fields(ruleset: Ruleset, digest: str) -> Dict[str, Any]:
    """The ruleset's part of the AI report header."""
    return {
        "loop": list(ruleset.loop),
        "hold_if": list(ruleset.hold_if),
        "forbid": list(ruleset.forbid),
        "verify": ruleset.verify.model_dump(),
        "prove": ruleset.prove.model_dump(),
        "ruleset": {"schema": SCHEMA, "version": ruleset.version, "sha256": digest},
    }
