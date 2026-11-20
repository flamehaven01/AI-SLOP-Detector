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
    unknown_row,
    verify_imports,
)
from slop_detector.import_providers import (
    ARTIFACT_VERIFIED,
    MAPPING_SUPPORTED,
    PROVIDER_CONFLICT,
    PROVIDER_UNKNOWN,
    ProviderKnowledge,
    Requirement,
    evidence,
    find_target_environment,
    provides,
)
from slop_detector.patterns.base import Axis, BasePattern, Issue, Severity
from slop_detector.patterns.python_imports import (
    _handler_is_import_guard,
    _resolves_in_project,
    environment_exclusions,
    file_requirements,
    project_skip_context,
)
from slop_detector.project_resolution import has_location, resolution_roots


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
        skip_names, indexes = project_skip_context(file, self._allowlist)
        roots = resolution_roots(file)
        target = find_target_environment(roots) if has_location() else None
        knowledge = ProviderKnowledge(target)
        result = verify_imports(
            tree,
            skip_names,
            guarded_import_lines(tree, _handler_is_import_guard),
            skip_module=lambda dotted, names: _resolves_in_project(indexes, dotted, names),
            excluded=environment_exclusions(indexes),
            target_sites=tuple(str(site) for site in target.sites) if target is not None else (),
        )
        unknowns = list(result.unknowns)
        issues: List[Issue] = []
        conflicts: Dict[Tuple[int, str], List[Finding]] = {}
        requirements = file_requirements(file, roots)
        for finding in result.findings:
            top = finding.module.split(".")[0]
            installed = knowledge.installed_provider(top)
            declared = [
                req for req in requirements if provides(knowledge.view(req).names, finding.module)
            ]
            declared_keys = {req.dist for req in declared}
            if declared and installed and not declared_keys & set(installed):
                # the names were checked against a distribution the project does not ask for
                conflicts.setdefault((finding.line, top), []).append(finding)
                continue
            if declared and not installed:
                # which distribution supplied the checked files is not known: not a finding
                unknowns.append(
                    unknown_row(finding.line, finding.module, finding.name, "provider_unknown")
                )
                continue
            issues.append(self._issue(file, finding, knowledge, installed))
        for (line, top), findings in sorted(conflicts.items()):
            issues.append(self._conflict(file, findings, knowledge, requirements, top))
        self._unknowns[str(file)] = tuple(unknowns)
        return issues

    def take_unknowns(self, file: Path) -> List[Dict[str, object]]:
        """Unverified imports from the last check of `file` (removed once taken)."""
        return list(self._unknowns.pop(str(file), ()))

    def _issue(
        self, file: Path, finding: Finding, knowledge: ProviderKnowledge, installed: List[str]
    ) -> Issue:
        top = finding.module.split(".")[0]
        if knowledge.target is not None and installed:
            key = installed[0]
            where = f"{knowledge.display_of(key)} {knowledge.version_of(key)}".rstrip()
            described = f"{where} in the target environment ({knowledge.target.path.name})"
        else:
            described = describe_installed(top)
        if finding.name is None:
            message = f"No module '{finding.module}' in {described}"
        else:
            message = f"'{finding.name}' is not defined in '{finding.module}' ({described})"
        issue = self.create_issue(
            file=file,
            line=finding.line,
            column=finding.column,
            message=message,
            suggestion=(
                "Check the package's API for the installed version. The name may be "
                "invented, misspelled, or from a different version of the package."
            ),
        )
        # one import line can name several members
        issue.subject = (
            finding.module if finding.name is None else f"{finding.module}.{finding.name}"
        )
        state = (
            knowledge.target.states.get(installed[0], ARTIFACT_VERIFIED)
            if knowledge.target is not None and installed
            else MAPPING_SUPPORTED if installed else PROVIDER_UNKNOWN
        )
        provider = knowledge.display_of(installed[0]) if installed else None
        issue.evidence = evidence(finding.module, provider, state, knowledge.environment)
        if finding.name is not None:
            issue.evidence["member"] = finding.name
        return issue

    def _conflict(
        self,
        file: Path,
        findings: List[Finding],
        knowledge: ProviderKnowledge,
        requirements: Tuple[Requirement, ...],
        top: str,
    ) -> Issue:
        first = findings[0]
        installed = ", ".join(
            f"{knowledge.display_of(k)} {knowledge.version_of(k)}".rstrip()
            for k in knowledge.installed_provider(top)
        )
        declared = sorted(
            {
                f"'{req.written}' ({req.label})"
                for req in requirements
                if provides(knowledge.view(req).names, first.module)
            }
        )
        names = sorted({f.name or f.module for f in findings})
        issue = Issue(
            pattern_id="provider_conflict",
            severity=Severity.MEDIUM,
            axis=self.axis,
            file=file,
            line=first.line,
            column=first.column,
            message=(
                f"Provider conflict: the installed '{top}' comes from {installed}, but the project "
                f"declares {', '.join(declared)}; {', '.join(names)} could not be checked against "
                "the declared distribution"
            ),
            suggestion=(
                "Check which distribution the project means. Install the declared one where the "
                "analysis runs, then rerun; do not change the import on the strength of this finding."
            ),
            subject=first.module,
        )
        declared_written = next(
            (
                req.written
                for req in requirements
                if provides(knowledge.view(req).names, first.module)
            ),
            None,
        )
        issue.evidence = evidence(
            first.module, declared_written, PROVIDER_CONFLICT, knowledge.environment
        )
        return issue
