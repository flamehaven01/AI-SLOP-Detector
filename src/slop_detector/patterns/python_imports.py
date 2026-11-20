"""Phantom import detection pattern and module resolution helpers."""

from __future__ import annotations

import ast
import logging
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, FrozenSet, List, Optional, Sequence, Tuple

from slop_detector.ast_index import walk_nodes
from slop_detector.dependency_declarations import (
    declaration_files,
    declared_requirements,
    root_declaration_files,
)
from slop_detector.environment_resolution import State, environment_state, find_installed_spec
from slop_detector.external_members import unknown_row
from slop_detector.import_providers import (
    ARTIFACT_VERIFIED,
    METADATA_DECLARED,
    PROVIDER_UNKNOWN,
    ProviderKnowledge,
    Requirement,
    candidate_names,
    evidence,
    find_target_environment,
    marker_active,
    marker_environment,
    parse_requirement,
    platform_guard_lines,
    provides,
    shipped_table,
)
from slop_detector.patterns.base import Axis, BasePattern, Issue, Severity
from slop_detector.project_context import fingerprint_for_roots, is_importable_directory
from slop_detector.project_resolution import (
    ProjectModuleIndex,
    discover_project_packages,
    get_module_index,
    has_location,
    resolution_roots,
)

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------
# Module resolution index (one per environment state)
# ------------------------------------------------------------------

_RESOLVABLE_MODULES_STORE: Dict[State, FrozenSet[str]] = {}

# ------------------------------------------------------------------
# Project-local package discovery
# ------------------------------------------------------------------

# Both keyed by (directory or root, project-context fingerprint): a changed
# context is a new key, so a long-running process never reuses a stale answer.
_SIBLING_MODULES_CACHE: Dict[Tuple[str, str], FrozenSet[str]] = {}

_ROOT_REQUIREMENTS_CACHE: Dict[Tuple[str, str], Tuple[Requirement, ...]] = {}


def _discover_sibling_modules(file_path: Path, fingerprint: Optional[str] = None) -> FrozenSet[str]:
    """Names importable from the file's directory: sibling .py files and, for a
    script outside a regular package, sibling package directories (regular or
    namespace), since a script's directory is on sys.path when it runs.

    Inside a regular package `import name` is absolute, so a subpackage next
    to the module is not what it loads."""
    if fingerprint is None:
        fingerprint = fingerprint_for_roots(file_path, resolution_roots(file_path))
    key = (str(file_path.parent), fingerprint)
    if key in _SIBLING_MODULES_CACHE:
        return _SIBLING_MODULES_CACHE[key]
    script_directory = not (file_path.parent / "__init__.py").is_file()
    try:
        result: FrozenSet[str] = frozenset(
            p.stem if p.is_file() else p.name
            for p in file_path.parent.iterdir()
            if (p.suffix == ".py" and p.stem != "__init__" and p.is_file())
            or (script_directory and is_importable_directory(p))
        )
    except OSError:
        result = frozenset()
    _SIBLING_MODULES_CACHE[key] = result
    return result


_IMPORT_GUARD_EXC_NAMES: FrozenSet[str] = frozenset(
    {"ImportError", "ModuleNotFoundError", "Exception", "BaseException"}
)


_EXTRAS_RE = re.compile(r"\[.*?\]")


def _dependency_import_names(dependency: str) -> FrozenSet[str]:
    """Likely import names for one declaration: the shipped table when it knows the
    distribution, else names derived from the declared name (rank 5 candidates)."""
    req = parse_requirement(_EXTRAS_RE.sub("", dependency), "")
    if req is None:
        return frozenset()
    return shipped_table().get(req.dist) or candidate_names(req.written)


def _add_dep_names(dep_list: List[str], packages: set) -> None:
    """Parse PEP-508 dependency strings and add likely import names.

    Strips extras specifiers (e.g. psycopg[binary]) before canonicalisation
    so that `import psycopg` matches `psycopg[binary]>=3.1.0` in optional-deps.
    """
    for dep in dep_list:
        packages.update(_dependency_import_names(dep))


def _requirements(files: Sequence[Path], label_root: Path) -> Tuple[Requirement, ...]:
    """Declared distributions of the files, each labelled with its file (from `label_root`)."""
    found: List[Requirement] = []
    for path in files:
        label = path.relative_to(label_root).as_posix()
        for dependency in declared_requirements(path):
            req = parse_requirement(_EXTRAS_RE.sub("", dependency), label)
            if req is not None:
                found.append(req)
    return tuple(found)


def _root_requirements(
    project_root: Path, fingerprint: Optional[str] = None
) -> Tuple[Requirement, ...]:
    """The root's declared distributions (cached per project-context fingerprint)."""
    if fingerprint is None:
        fingerprint = fingerprint_for_roots(project_root / "_", (project_root,))
    root_key = (str(project_root), fingerprint)
    cached = _ROOT_REQUIREMENTS_CACHE.get(root_key)
    if cached is None:
        cached = _requirements(root_declaration_files(project_root), project_root)
        _ROOT_REQUIREMENTS_CACHE[root_key] = cached
    return cached


def _path_requirements(file: Path, nearest_root: Path) -> Tuple[Requirement, ...]:
    """Declarations in the directories between the file and its nearest root.

    Only files on the file's own path count: a declaration in another subtree
    says nothing about this file. The root itself is read by the root lookup.
    """
    directories = []
    current = file.parent
    while current != nearest_root and nearest_root in current.parents:
        directories.append(current)
        current = current.parent
    files = [path for directory in directories for path in declaration_files(directory)]
    return _requirements(files, nearest_root)


def file_requirements(file: Path, roots: Sequence[Path]) -> Tuple[Requirement, ...]:
    """Every declaration that is evidence for `file`: each resolution root's and the ones on its path."""
    found = [req for root in roots for req in _root_requirements(root)]
    if roots:
        found.extend(_path_requirements(file, roots[0]))
    return tuple(found)


def _resolves_in_project(
    indexes: Sequence[ProjectModuleIndex], dotted: str, names: Sequence[str] = ()
) -> bool:
    """Exact-path resolution under any of the project roots' module roots, no depth limit."""
    return any(index.resolves(dotted, names) for index in indexes)


def _get_resolvable_modules() -> FrozenSet[str]:
    """All top-level module names resolvable in this environment.

    Cached per environment state, so an install or uninstall in a long-lived
    process (MCP server, watch mode) is seen by the next lookup.
    """
    state = environment_state()
    if state in _RESOLVABLE_MODULES_STORE:
        return _RESOLVABLE_MODULES_STORE[state]

    known: set[str] = set()
    known.update(sys.builtin_module_names)

    if hasattr(sys, "stdlib_module_names"):
        known.update(sys.stdlib_module_names)  # type: ignore[attr-defined]

    try:
        from importlib.metadata import packages_distributions  # type: ignore[attr-defined]

        for top_level_names in packages_distributions().values():
            for name in top_level_names:
                known.add(name)
                known.add(name.replace("-", "_"))
    except (AttributeError, ImportError) as exc:
        logger.debug("packages_distributions unavailable, skipping layer 3: %s", exc)

    _RESOLVABLE_MODULES_STORE.clear()
    _RESOLVABLE_MODULES_STORE[state] = frozenset(known)
    return _RESOLVABLE_MODULES_STORE[state]


def _module_exists(name: str, excluded: Sequence[Path] = ()) -> bool:
    """Return True if name is a resolvable top-level module in the analyzer's environment.

    Never from the analyzer's cwd or the `excluded` project roots (see
    slop_detector.environment_resolution). A lookup that raises is not an
    answer: it propagates, and the pattern is recorded as unmeasured for the
    file instead of reporting the module as installed.
    """
    if name in _get_resolvable_modules():
        return True
    return find_installed_spec(name, excluded) is not None


def environment_exclusions(indexes: Sequence[ProjectModuleIndex]) -> Tuple[Path, ...]:
    """The analyzed project's own roots: never evidence that a module is installed."""
    return tuple(
        path
        for index in indexes
        for path in (index.project_root, *(root.path for root in index.roots))
    )


def project_skip_context(
    file: Path, allowlist: FrozenSet[str]
) -> Tuple[FrozenSet[str], Tuple[ProjectModuleIndex, ...]]:
    """Top-level names that belong to the project (never checked as installed packages).

    Internal packages of every resolution root, sibling .py files (flat-module
    projects without pyproject.toml), and the allowlist; plus each root's module
    index for exact-path resolution.
    """
    roots = resolution_roots(file)
    skip_names = set(allowlist)
    for position, root in enumerate(roots):
        # The scan root (second) is evidence for its hard roots and exact paths only.
        skip_names |= discover_project_packages(root, hard_only=position > 0)
    if has_location():
        skip_names |= _discover_sibling_modules(file, fingerprint_for_roots(file, roots))
    return frozenset(skip_names), tuple(get_module_index(root) for root in roots)


def _handler_is_import_guard(handler: ast.ExceptHandler) -> bool:
    """Return True if this except handler would catch an ImportError."""
    if handler.type is None:
        return True
    exc_names: set[str] = set()
    if isinstance(handler.type, ast.Name):
        exc_names.add(handler.type.id)
    elif isinstance(handler.type, ast.Tuple):
        for elt in handler.type.elts:
            if isinstance(elt, ast.Name):
                exc_names.add(elt.id)
    return bool(exc_names & _IMPORT_GUARD_EXC_NAMES)


def _collect_import_guard_lines(tree: ast.AST) -> FrozenSet[int]:
    """Return line numbers of import statements inside try/except ImportError blocks."""
    guarded: set[int] = set()
    for node in walk_nodes(tree):
        if not isinstance(node, ast.Try):
            continue
        if any(_handler_is_import_guard(h) for h in node.handlers):
            for stmt in node.body:
                if isinstance(stmt, (ast.Import, ast.ImportFrom)):
                    guarded.add(stmt.lineno)
    return frozenset(guarded)


def _no_context_row(line: int, module: str) -> Dict[str, object]:
    return unknown_row(line, module, None, "no_project_context", basis="environment_only")


class PhantomImportPattern(BasePattern):
    """Classify unresolved imports without confusing runtime and metadata evidence.

    `phantom_import` is reserved for imports with no local declaration and no
    runtime resolution. Declared-but-unavailable imports and requirements-only
    declarations use distinct pattern IDs so they can be reviewed separately.
    """

    id = "phantom_import"
    severity = Severity.CRITICAL
    axis = Axis.QUALITY
    message = "Import references a package that cannot be resolved in this environment"

    def __init__(self, allowlist: Optional[List[str]] = None) -> None:
        self._allowlist: FrozenSet[str] = frozenset(allowlist or [])
        self._unknowns: Dict[str, Tuple[Dict[str, object], ...]] = {}

    def take_unknowns(self, file: Path) -> List[Dict[str, object]]:
        """Imports the last check of `file` could not judge (removed once taken)."""
        return list(self._unknowns.pop(str(file), ()))

    def check(self, tree: ast.AST, file: Path, content: str) -> list[Issue]:
        issues: list[Issue] = []
        # A source with no location: an import the environment cannot resolve may
        # be local code nobody showed us, so it is unverified, not a finding.
        unknowns: list[Dict[str, object]] = []
        located = has_location()

        roots = resolution_roots(file)
        skip_names, indexes = project_skip_context(file, self._allowlist)
        target = find_target_environment(roots) if located else None
        env = marker_environment(target)
        inactive, undecided = platform_guard_lines(tree, env)
        ctx = _FileContext(
            excluded=environment_exclusions(indexes),
            guarded=_collect_import_guard_lines(tree),
            inactive=inactive,
            undecided=undecided,
            knowledge=ProviderKnowledge(target),
            requirements=file_requirements(file, roots),
            has_pyproject=bool(roots and (roots[0] / "pyproject.toml").exists()),
            marker_env=env,
        )

        for node in walk_nodes(tree):
            requests: List[Tuple[str, List[str]]] = []
            if isinstance(node, ast.Import):
                requests = [(alias.name, []) for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
                requests = [(node.module, [alias.name for alias in node.names])]
            for module, members in requests:
                top = module.split(".")[0]
                if top in skip_names or _resolves_in_project(indexes, module, members):
                    continue
                lineno = getattr(node, "lineno", 0)
                if lineno in ctx.inactive:
                    continue  # does not run on the target platform
                if self._resolved(top, ctx):
                    continue
                if not located:
                    unknowns.append(_no_context_row(lineno, module))
                    continue
                if lineno in ctx.undecided:
                    # under a platform test the target environment does not decide: whether
                    # this import runs where the code runs is not known, so it is no finding
                    unknowns.append(
                        unknown_row(
                            lineno,
                            module,
                            None,
                            "platform_guard_undecided",
                            basis="target_platform",
                        )
                    )
                    continue
                issues.append(self._verdict(file, node, module, members, ctx))

        self._unknowns[str(file)] = tuple(unknowns)
        return issues

    @staticmethod
    def _resolved(top: str, ctx: "_FileContext") -> bool:
        """Resolvable where the code runs: the target environment when there is one, else the
        analyzer's. With a target, only its site-packages and the standard library are
        searched (find_installed_spec with target_sites), on every Python version: the
        analyzer's installed packages are not evidence about the target."""
        target = ctx.knowledge.target
        if target is None:
            return _module_exists(top, ctx.excluded)
        if top in getattr(sys, "stdlib_module_names", ()) or target.has_module(top):
            return True
        sites = tuple(str(site) for site in target.sites)
        return find_installed_spec(top, ctx.excluded, target_sites=sites) is not None

    def _verdict(
        self, file: Path, node: ast.AST, module: str, members: List[str], ctx: "_FileContext"
    ) -> Issue:
        line, column = getattr(node, "lineno", 0), getattr(node, "col_offset", 0)
        knowledge = ctx.knowledge
        matching = []
        for req in ctx.requirements:
            view = knowledge.view(req)
            if provides(view.names, module, members):
                matching.append((req, view))
        if matching:
            states = [marker_active(m[0].marker, ctx.marker_env) for m in matching]
            active = [m for m, s in zip(matching, states) if s is not False]
            req, view = (active or matching)[0]
            sources = frozenset(r.label for r, _ in matching)
            ev = evidence(module, req.written, view.state, knowledge.environment)
            if req.marker:
                state_of_req = states[matching.index((req, view))]
                ev["marker_evaluation"] = {True: "ACTIVE", False: "INACTIVE", None: "UNKNOWN"}[
                    state_of_req
                ]
            if self._is_requirements_only_metadata_gap(sources, ctx.has_pyproject):
                issue = self._make_metadata_gap_issue(file, line, column, module, sources)
            else:
                inactive_marker = None if active else req.marker
                issue = self._declared_unavailable(
                    file, line, column, module, sources, req, knowledge, inactive_marker
                )
        else:
            known = knowledge.known_providers(module, members)
            # A provider is named only when exactly one distribution is known to supply the
            # name; several candidates and nothing that selects one: named nowhere.
            provider, state = known[0] if len(known) == 1 else (None, PROVIDER_UNKNOWN)
            ev = evidence(module, provider, state, knowledge.environment)
            if len(known) > 1:
                ev["candidates"] = [name for name, _ in known]
            if line in ctx.guarded:
                issue = self._undeclared_optional(file, line, column, module)
            elif known:
                issue = self._undeclared_known(file, line, column, module, provider, state, known)
            else:
                issue = self._unknown_provider(file, line, column, module)
        issue.subject = module  # one import line can name several modules
        ev["target_platform"] = knowledge.target.platform if knowledge.target is not None else None
        issue.evidence = ev
        return issue

    def _declared_unavailable(
        self,
        file: Path,
        line: int,
        column: int,
        module: str,
        sources: FrozenSet[str],
        req: Requirement,
        knowledge: ProviderKnowledge,
        inactive_marker: Optional[str],
    ) -> Issue:
        locations = ", ".join(sorted(sources))
        if knowledge.target is not None:
            where = f"the target environment ({knowledge.target.path.name})"
        else:
            where = "the analyzer runtime"
        same_name = req.written.replace("-", "_").lower() == module.split(".")[0].lower()
        provider = "" if same_name else f" (provided by '{req.written}')"
        note = ""
        if inactive_marker:
            note = f"; that declaration applies only where {inactive_marker}, and this import runs here"
        return Issue(
            pattern_id="runtime_unavailable_dependency",
            severity=Severity.MEDIUM,
            axis=self.axis,
            file=file,
            line=line,
            column=column,
            message=(
                f"Declared dependency '{module}'{provider} is unavailable in {where} "
                f"(declared in {locations}){note}."
            ),
            suggestion=(
                "Install the declared dependency in the analysis environment, then rerun. "
                "This is environment evidence, not proof of a phantom package."
            ),
        )

    def _undeclared_optional(self, file: Path, line: int, column: int, module: str) -> Issue:
        return Issue(
            pattern_id="undeclared_optional_dependency",
            severity=Severity.MEDIUM,
            axis=self.axis,
            file=file,
            line=line,
            column=column,
            message=(
                f"Undeclared optional dependency: '{module}' is guarded with "
                f"ImportError but not listed in [project.optional-dependencies]"
            ),
            suggestion=(
                f"Add '{module}' to the appropriate "
                f"[project.optional-dependencies.<group>] in pyproject.toml so "
                f"users know this feature requires an extra install."
            ),
        )

    def _undeclared_known(
        self,
        file: Path,
        line: int,
        column: int,
        module: str,
        provider: Optional[str],
        state: str,
        known: List[Tuple[str, str]],
    ) -> Issue:
        """HIGH only when one provider is identified from the target environment's own files
        or metadata; a provider known from mapping knowledge (the shipped table, the analyzer's
        installs) or several candidates are review candidates: MEDIUM."""
        identified = provider is not None and state in (ARTIFACT_VERIFIED, METADATA_DECLARED)
        if provider is not None:
            whom = f"the distribution '{provider}'"
            confirm = f"Confirm that '{provider}' is the package this code means, then declare it. "
        else:
            whom = "one of " + ", ".join(f"'{name}'" for name, _ in known)
            confirm = "Several distributions provide this name; confirm which one is meant. "
        return Issue(
            pattern_id="undeclared_dependency",
            severity=Severity.HIGH if identified else Severity.MEDIUM,
            axis=self.axis,
            file=file,
            line=line,
            column=column,
            message=(
                f"Undeclared dependency: '{module}' is provided by {whom}, "
                "which no dependency declaration on this file's path names"
            ),
            suggestion=(
                confirm
                + "Do not install or declare a package on the strength of this finding alone."
            ),
        )

    def _unknown_provider(self, file: Path, line: int, column: int, module: str) -> Issue:
        return self.create_issue(
            file=file,
            line=line,
            column=column,
            message=(
                f"Phantom import: no installed distribution, dependency declaration or known "
                f"provider supplies '{module}'"
            ),
            suggestion=(
                f"Confirm which package '{module}' was meant to come from before installing or "
                "declaring anything: a name that can be found on a package index is not proof "
                "that it is the intended package. AI models sometimes generate plausible-looking "
                "package names."
            ),
            severity_override=Severity.CRITICAL,
        )

    @staticmethod
    def _is_requirements_only_metadata_gap(
        declared_sources: FrozenSet[str], has_pyproject: bool
    ) -> bool:
        return has_pyproject and bool(declared_sources) and "pyproject.toml" not in declared_sources

    def _make_metadata_gap_issue(
        self,
        file: Path,
        line: int,
        column: int,
        module_name: str,
        declared_sources: FrozenSet[str],
    ) -> Issue:
        locations = ", ".join(sorted(declared_sources))
        issue = Issue(
            pattern_id="declared_outside_primary_metadata",
            severity=Severity.LOW,
            axis=self.axis,
            file=file,
            line=line,
            column=column,
            message=(
                f"Dependency '{module_name}' is declared in {locations} but not in "
                "pyproject.toml project metadata."
            ),
            suggestion=(
                "Keep dependency declarations aligned with pyproject.toml so package "
                "installation and analysis use the same contract."
            ),
            subject=module_name,
        )
        return issue


@dataclass(frozen=True)
class _FileContext:
    """What one file's import verdicts read."""

    excluded: Tuple[Path, ...]
    guarded: FrozenSet[int]
    inactive: FrozenSet[int]  # under a platform test that is false in the target environment
    undecided: FrozenSet[int]  # under a platform test the target environment does not decide
    knowledge: ProviderKnowledge
    requirements: Tuple[Requirement, ...]
    has_pyproject: bool
    marker_env: Dict[str, str]  # marker variables the target environment establishes
