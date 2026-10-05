"""phantom_member: names that an installed package does not define.

`phantom_import` covers packages that are not installed at all. This pattern
covers the other half: the package is real, but the module or name imported
from it does not exist in the installed version. Evidence comes only from the
package's source files (slop_detector.external_members); nothing is imported.
Imports whose absence cannot be shown are not findings: they are returned as
unverified imports with a reason and no score effect.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Dict, FrozenSet, List, Optional, Tuple

from slop_detector.external_members import (
    Finding,
    describe_installed,
    guarded_import_lines,
    verify_imports,
)
from slop_detector.patterns.base import Axis, BasePattern, Issue, Severity
from slop_detector.patterns.python_imports import (
    _handler_is_import_guard,
    _resolves_in_project,
    environment_exclusions,
    project_skip_context,
)


class PhantomMemberPattern(BasePattern):
    """An import names a module or attribute the installed package does not define."""

    id = "phantom_member"
    severity = Severity.HIGH
    axis = Axis.QUALITY
    message = "Import names something the installed package does not define"

    def __init__(self, allowlist: Optional[List[str]] = None) -> None:
        self._allowlist: FrozenSet[str] = frozenset(allowlist or [])
        self._unknowns: Dict[str, Tuple[Dict[str, object], ...]] = {}

    def check(self, tree: ast.AST, file: Path, content: str) -> List[Issue]:
        if not isinstance(tree, ast.Module):
            return []
        skip_names, index = project_skip_context(file, self._allowlist)
        result = verify_imports(
            tree,
            skip_names,
            guarded_import_lines(tree, _handler_is_import_guard),
            skip_module=lambda dotted, names: _resolves_in_project(index, dotted, names),
            excluded=environment_exclusions(index),
        )
        self._unknowns[str(file)] = result.unknowns
        return [self._issue(file, finding) for finding in result.findings]

    def take_unknowns(self, file: Path) -> List[Dict[str, object]]:
        """Unverified imports from the last check of `file` (removed once taken)."""
        return list(self._unknowns.pop(str(file), ()))

    def _issue(self, file: Path, finding: Finding) -> Issue:
        installed = describe_installed(finding.module.split(".")[0])
        if finding.name is None:
            message = f"No module '{finding.module}' in {installed}"
        else:
            message = f"'{finding.name}' is not defined in '{finding.module}' ({installed})"
        return self.create_issue(
            file=file,
            line=finding.line,
            column=finding.column,
            message=message,
            suggestion=(
                "Check the package's API for the installed version. The name may be "
                "invented, misspelled, or from a different version of the package."
            ),
        )
