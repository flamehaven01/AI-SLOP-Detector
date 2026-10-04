"""docs/PATTERNS.md's active pattern table matches what the detectors emit.

Only the block between the ACTIVE_PATTERN_REGISTRY markers is checked; prose,
examples, and history elsewhere in the document are not. This is a read-only
comparator: it never edits the document or a registry.

Authorities, kept apart per surface:
  Python  get_all_patterns() (id, class severity), plus ids the patterns emit
          directly with Issue(pattern_id=...), and autofix._PATCHERS
  JS/TS   JSIssue(...) calls in languages/js_analyzer.py
  Go      GoIssue(...) calls in languages/go_analyzer.py

A severity cell starts with the default severity; other severities a rule can
emit are written after it. Where an emit site's severity is a variable, every
severity assigned to it in that function must appear in the cell.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Dict, List, Set, Tuple

import slop_detector.patterns as patterns_pkg
from slop_detector.autofix.engine import _PATCHERS, FixEngine
from slop_detector.patterns import get_all_patterns

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "PATTERNS.md"
LANGUAGES = ROOT / "src" / "slop_detector" / "languages"
START, END = "<!-- ACTIVE_PATTERN_REGISTRY:START -->", "<!-- ACTIVE_PATTERN_REGISTRY:END -->"
SEVERITIES = ("critical", "high", "medium", "low")
Rule = Tuple[str, Set[str], str]  # language, severities (first = default), default


def _doc_rows() -> List[List[str]]:
    text = DOC.read_text(encoding="utf-8")
    assert START in text and END in text, "PATTERNS.md has no ACTIVE_PATTERN_REGISTRY block"
    block = text.split(START, 1)[1].split(END, 1)[0]
    rows = []
    for line in block.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 5 and cells[0].startswith("`"):
            rows.append(cells)
    return rows


def _severity_name(node: ast.AST) -> str:
    if isinstance(node, ast.Attribute):  # Severity.HIGH
        return node.attr.lower()
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value.lower()
    return ""


def _python_rules() -> Dict[str, Rule]:
    rules = {p.id: ("Python", {p.severity.value}, p.severity.value) for p in get_all_patterns()}
    for path in Path(patterns_pkg.__path__[0]).glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not (isinstance(node, ast.Call) and getattr(node.func, "id", "") == "Issue"):
                continue
            kw = {k.arg: k.value for k in node.keywords}
            pid = kw.get("pattern_id")
            if isinstance(pid, ast.Constant) and pid.value not in rules:
                severity = _severity_name(kw.get("severity"))
                rules[pid.value] = ("Python", {severity}, severity)
    return rules


def _assigned_severities(func: ast.AST, name: str) -> Set[str]:
    found: Set[str] = set()
    for node in ast.walk(func):
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == name for t in node.targets
        ):
            found |= {
                c.value
                for c in ast.walk(node.value)
                if isinstance(c, ast.Constant) and c.value in SEVERITIES
            }
    return found


def _analyzer_rules(module: str, issue_class: str, language: str) -> Dict[str, Rule]:
    tree = ast.parse((LANGUAGES / module).read_text(encoding="utf-8"))
    rules: Dict[str, Rule] = {}
    for func in ast.walk(tree):
        if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for node in ast.walk(func):
            if not (isinstance(node, ast.Call) and getattr(node.func, "id", "") == issue_class):
                continue
            pid, severity = node.args[0], node.args[1]
            if isinstance(severity, ast.Name):
                values = _assigned_severities(func, severity.id)
            else:
                values = {_severity_name(severity)}
            _, known, default = rules.get(pid.value, (language, set(), ""))
            # A variable severity escalates; its default is the least severe value.
            least = max(values, key=SEVERITIES.index)
            rules[pid.value] = (language, known | values, default or least)
    return rules


def _authority() -> Dict[str, Rule]:
    rules = _python_rules()
    rules.update(_analyzer_rules("js_analyzer.py", "JSIssue", "JS/TS"))
    rules.update(_analyzer_rules("go_analyzer.py", "GoIssue", "Go"))
    return rules


def test_every_active_id_is_documented_once_and_nothing_stale():
    ids = [row[0].strip("`") for row in _doc_rows()]
    authority = _authority()
    assert sorted({i for i in ids if ids.count(i) > 1}) == [], "duplicate ids"
    assert sorted(set(authority) - set(ids)) == [], "active ids missing from the table"
    assert sorted(set(ids) - set(authority)) == [], "table ids no detector emits"


def test_language_severity_and_autofix_match_the_detectors():
    authority = _authority()
    problems = []
    for pid_cell, language, severity, _category, autofix, *_ in _doc_rows():
        pid = pid_cell.strip("`")
        if pid not in authority:
            continue
        rule_language, severities, default = authority[pid]
        words = re.findall(r"[a-z]+", severity.lower())
        if language != rule_language:
            problems.append(f"{pid}: language {language} != {rule_language}")
        if not words or words[0] != default:
            problems.append(f"{pid}: default severity {severity} != {default}")
        if rule_language != "Python" and not severities <= set(words):
            problems.append(f"{pid}: severities {sorted(severities)} not all in {severity}")
        fixable = pid in _PATCHERS and pid not in FixEngine.UNFIXABLE_PATTERNS
        if autofix.lower().startswith("yes") != fixable:
            problems.append(f"{pid}: auto-fix {autofix} != {'Yes' if fixable else 'No'}")
    assert problems == []
