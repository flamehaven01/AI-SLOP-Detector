"""Inline suppression parser and matcher for pattern issues."""

from __future__ import annotations

import re
from typing import List, Optional

from slop_detector.models import SuppressionDirective, SuppressionLedgerEntry

_SUPPRESSION_RE = re.compile(r"^\s*#\s*slop-(disable-next-line|disable|enable)\b(?:\s+(.+?))?\s*$")


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
            directives.append(
                SuppressionDirective(
                    scope="next_line" if kind == "disable-next-line" else "block",
                    action="enable" if kind == "enable" else "disable",
                    lineno=lineno,
                    rules=SuppressionHandler._parse_rules(payload),
                )
            )
        return directives

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
