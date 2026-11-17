"""Inline suppression parser and matcher for pattern issues.

`# slop-disable-next-line <rule> fp: <reason>` declares the finding a false
positive (the user's judgment). Everything after `fp:` is the reason: its words
are never rule ids. The declaration is valid for exactly one rule, a non-empty
reason and the next-line form; otherwise the directive is a plain suppression
of the rules before `fp:`. Only the reason's SHA-256 is kept.
"""

from __future__ import annotations

import hashlib
import re
from typing import List, Optional, Tuple

from slop_detector.models import SuppressionDirective, SuppressionLedgerEntry

_SUPPRESSION_RE = re.compile(r"^\s*#\s*slop-(disable-next-line|disable|enable)\b(?:\s+(.+?))?\s*$")
_FP_MARK = re.compile(r"(?:^|[\s,])fp:", re.IGNORECASE)


class SuppressionHandler:
    """Parses and applies inline comment-based suppressions."""

    @staticmethod
    def parse_comment_suppressions(content: str) -> List[SuppressionDirective]:
        directives: List[SuppressionDirective] = []
        for lineno, line in enumerate(content.splitlines(), start=1):
            match = _SUPPRESSION_RE.match(line)
            if not match:
                continue
            kind, payload = match.groups()
            scope = "next_line" if kind == "disable-next-line" else "block"
            rules, reason = SuppressionHandler._split_payload(payload)
            declared = (
                reason is not None
                and scope == "next_line"
                and len(rules) == 1
                and rules[0] != "all"
            )
            directives.append(
                SuppressionDirective(
                    scope=scope,
                    action="enable" if kind == "enable" else "disable",
                    lineno=lineno,
                    rules=rules,
                    declared_false_positive=declared,
                    reason_sha256=(
                        hashlib.sha256(reason.encode("utf-8")).hexdigest() if declared else None
                    ),
                )
            )
        return directives

    @staticmethod
    def _split_payload(payload: Optional[str]) -> Tuple[List[str], Optional[str]]:
        """The rule ids and the `fp:` reason (None when absent or empty)."""
        if not payload:
            return ["all"], None
        mark = _FP_MARK.search(payload)
        if mark is None:
            return SuppressionHandler._parse_rules(payload), None
        ids, reason = payload[: mark.start()], payload[mark.end() :].strip()
        # No rule before fp: names nothing (the words were unknown ids before).
        rules = SuppressionHandler._parse_rules(ids) if ids.strip() else []
        return rules, reason or None

    @staticmethod
    def _parse_rules(payload: Optional[str]) -> List[str]:
        if not payload:
            return ["all"]
        normalized = payload.replace(",", " ")
        rules = [part.strip().lower() for part in normalized.split() if part.strip()]
        return rules or ["all"]

    @staticmethod
    def match_issue(
        file_path: str,
        issue_line: int,
        pattern_id: str,
        directives: List[SuppressionDirective],
    ) -> Optional[SuppressionLedgerEntry]:
        pattern_id = pattern_id.lower()

        for directive in directives:
            if (
                directive.action == "disable"
                and directive.scope == "next_line"
                and directive.lineno + 1 == issue_line
                and SuppressionHandler._matches_rule(pattern_id, directive.rules)
            ):
                return SuppressionLedgerEntry(
                    file_path=file_path,
                    directive_line=directive.lineno,
                    suppressed_line=issue_line,
                    pattern_id=pattern_id,
                    scope=directive.scope,
                    matched_rule="all" if "all" in directive.rules else pattern_id,
                    declared_false_positive=directive.declared_false_positive,
                    reason_sha256=directive.reason_sha256,
                )

        active_all = False
        active_all_line = 0
        active_rules: dict[str, int] = {}

        for directive in directives:
            if directive.scope != "block" or directive.lineno > issue_line:
                continue
            if directive.action == "disable":
                if "all" in directive.rules:
                    active_all = True
                    active_all_line = directive.lineno
                else:
                    for rule in directive.rules:
                        active_rules[rule] = directive.lineno
            else:
                if "all" in directive.rules:
                    active_all = False
                    active_all_line = 0
                    active_rules.clear()
                else:
                    for rule in directive.rules:
                        active_rules.pop(rule, None)

        if active_all:
            return SuppressionLedgerEntry(
                file_path=file_path,
                directive_line=active_all_line,
                suppressed_line=issue_line,
                pattern_id=pattern_id,
                scope="block",
                matched_rule="all",
            )
        if pattern_id in active_rules:
            return SuppressionLedgerEntry(
                file_path=file_path,
                directive_line=active_rules[pattern_id],
                suppressed_line=issue_line,
                pattern_id=pattern_id,
                scope="block",
                matched_rule=pattern_id,
            )
        return None

    @staticmethod
    def _matches_rule(pattern_id: str, rules: List[str]) -> bool:
        return "all" in rules or pattern_id in rules
