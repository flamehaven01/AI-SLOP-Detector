"""Framework-aware masking for deterministic boilerplate noise reduction."""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any, Iterable, List, Optional, Tuple

from slop_detector.models import MaskedIssue
from slop_detector.patterns.base import Issue, Severity

_PYTHON_TEST_PATH_RE = re.compile(r"(^|[\\/])(tests?|__tests__)([\\/]|$)")
_PYTHON_TEST_FILE_RE = re.compile(r"(^test_.*\.py$|.*_test\.py$)")
_JS_TEST_PATH_RE = re.compile(r"(^|[\\/])(__tests__|tests)([\\/]|$)")
_JS_TEST_FILE_RE = re.compile(r".*\.(test|spec)\.(js|jsx|ts|tsx)$")
_JS_NOOP_HOOK_RE = re.compile(
    r"\b(beforeEach|afterEach|beforeAll|afterAll|before|after)\s*\(\s*(?:async\s*)?\(\s*\)\s*=>\s*\{\s*\}\s*\)"
)
_PYTEST_NOOP_HOOKS = frozenset(
    {
        "setup_module",
        "teardown_module",
        "setup_function",
        "teardown_function",
        "setup_method",
        "teardown_method",
        "pytest_runtest_setup",
        "pytest_runtest_teardown",
        "pytest_sessionstart",
        "pytest_sessionfinish",
    }
)


class FrameworkMasker:
    """Masks a narrow set of deterministic framework boilerplate findings."""

    @staticmethod
    def _is_python_test_file(file_path: Path) -> bool:
        normalized = str(file_path).replace("\\", "/")
        name = file_path.name
        return bool(
            file_path.name == "conftest.py"
            or _PYTHON_TEST_PATH_RE.search(normalized)
            or _PYTHON_TEST_FILE_RE.match(name)
        )

    @staticmethod
    def _is_js_test_file(file_path: Path) -> bool:
        normalized = str(file_path).replace("\\", "/")
        return bool(_JS_TEST_PATH_RE.search(normalized) or _JS_TEST_FILE_RE.match(file_path.name))

    @staticmethod
    def _line_text(content: str, line_number: int) -> str:
        lines = content.splitlines()
        if 1 <= line_number <= len(lines):
            return lines[line_number - 1]
        return ""

    @staticmethod
    def _python_function_name_at_line(tree: ast.AST, line_number: int) -> Optional[str]:
        for node in ast.walk(tree):
            if (
                isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.lineno == line_number
            ):
                return node.name
        return None

    @classmethod
    def mask_python_issue(
        cls, file_path: Path, issue: Issue, content: str, tree: ast.AST
    ) -> Optional[MaskedIssue]:
        del content
        if issue.severity == Severity.CRITICAL:
            return None
        if (
            issue.pattern_id == "pass_placeholder"
            and cls._is_python_test_file(file_path)
            and cls._python_function_name_at_line(tree, issue.line) in _PYTEST_NOOP_HOOKS
        ):
            return MaskedIssue(
                file_path=str(file_path),
                masked_line=issue.line,
                pattern_id=issue.pattern_id,
                framework="pytest",
                rule_id="pytest_noop_hook",
                reason="empty pytest lifecycle hooks are treated as framework boilerplate",
            )
        return None

    @classmethod
    def apply_python_masking(
        cls, file_path: Path, content: str, tree: ast.AST, issues: Iterable[Issue]
    ) -> Tuple[List[Issue], List[MaskedIssue]]:
        visible: List[Issue] = []
        masked: List[MaskedIssue] = []
        for issue in issues:
            masked_issue = cls.mask_python_issue(file_path, issue, content, tree)
            if masked_issue is not None:
                masked.append(masked_issue)
                continue
            visible.append(issue)
        return visible, masked

    @classmethod
    def mask_js_issue(cls, file_path: Path, issue: Any, content: str) -> Optional[MaskedIssue]:
        line_text = cls._line_text(content, getattr(issue, "line", 0))
        if getattr(issue, "pattern_id", "") == "js_console_log" and cls._is_js_test_file(file_path):
            return MaskedIssue(
                file_path=str(file_path),
                masked_line=getattr(issue, "line", 0),
                pattern_id=issue.pattern_id,
                framework="test_harness",
                rule_id="js_test_console",
                reason="console output in test/spec files is treated as harness noise",
            )
        if (
            getattr(issue, "pattern_id", "") == "js_empty_arrow"
            and cls._is_js_test_file(file_path)
            and _JS_NOOP_HOOK_RE.search(line_text)
        ):
            return MaskedIssue(
                file_path=str(file_path),
                masked_line=getattr(issue, "line", 0),
                pattern_id=issue.pattern_id,
                framework="jest_vitest",
                rule_id="js_noop_test_hook",
                reason="empty lifecycle hooks in test harness setup are treated as boilerplate",
            )
        return None

    @classmethod
    def apply_js_masking(
        cls, file_path: str | Path, content: str, issues: Iterable[Any]
    ) -> Tuple[List[Any], List[MaskedIssue]]:
        path = Path(file_path)
        visible: List[Any] = []
        masked: List[MaskedIssue] = []
        for issue in issues:
            masked_issue = cls.mask_js_issue(path, issue, content)
            if masked_issue is not None:
                masked.append(masked_issue)
                continue
            visible.append(issue)
        return visible, masked
