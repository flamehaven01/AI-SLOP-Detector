"""Evidence passes for connection evidence: uses, decorators, exports, dynamic access.

Each pass adds evidence (by kind) or a dynamic reason to the symbols that
connection_resolution found. Nothing here decides a state; connection_evidence
does that.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Dict, Iterator, List, NamedTuple, Optional, Set, Tuple

from slop_detector.analysis.connection_resolution import (
    Collector,
    Def,
    Gaps,
    Module,
    Site,
    Symbol,
    Target,
    all_assignments,
    dunder_all,
    last_name,
    mark,
    module_level,
    name_chain,
    record_gap,
    top_level_defs,
)
from slop_detector.project_resolution import HARD_AUTHORITIES

# Last name of a decorator that registers the function with a framework
# (leading underscores ignored: a private `_register` is still a registry).
REGISTERING_DECORATORS = frozenset(
    {
        "route",
        "get",
        "post",
        "put",
        "delete",
        "patch",
        "head",
        "options",
        "websocket",
        "api_route",
        "command",
        "group",
        "task",
        "shared_task",
        "register",
        "fixture",
        "hookimpl",
        "hookspec",
        "receiver",
    }
)
# Decorators that wrap or describe without registering: evidence of nothing.
PLAIN_DECORATORS = frozenset(
    {
        "dataclass",
        "property",
        "cached_property",
        "lru_cache",
        "cache",
        "staticmethod",
        "classmethod",
        "total_ordering",
        "wraps",
        "contextmanager",
        "asynccontextmanager",
        "abstractmethod",
        "overload",
        "final",
        "override",
        "runtime_checkable",
        "singledispatch",
        "unique",
    }
)

_CONTAINERS = (ast.Dict, ast.List, ast.Tuple, ast.Set)
_ASSIGNMENTS = (ast.Assign, ast.AnnAssign, ast.AugAssign)
_DOTTED = re.compile(r"^[A-Za-z_][\w.]*[.:]([A-Za-z_]\w*)$")


class _Use(NamedTuple):
    kind: str
    full: bool  # the whole name chain resolved, no attribute left over
    owner: Optional[str]  # the top-level def/class the use sits in
    line: int


# ---------------------------------------------------------------------------
# Uses: calls, references, registry entries
# ---------------------------------------------------------------------------


def _context(
    tree: ast.Module,
) -> Tuple[List[Tuple[ast.AST, Optional[str]]], Dict[ast.AST, ast.AST]]:
    """One pass: every node with the top-level def/class it sits in, and parent links."""
    nodes: List[Tuple[ast.AST, Optional[str]]] = []
    parents: Dict[ast.AST, ast.AST] = {}
    stack: List[Tuple[ast.AST, Optional[str]]] = [(tree, None)]
    while stack:
        node, owner = stack.pop()
        nodes.append((node, owner))
        for child in ast.iter_child_nodes(node):
            parents[child] = node
            is_def = node is tree and isinstance(
                child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
            )
            stack.append((child, getattr(child, "name", None) if is_def else owner))
    return nodes, parents


def _chain_at(
    node: ast.AST, parents: Dict[ast.AST, ast.AST]
) -> Optional[Tuple[List[str], ast.expr]]:
    """The name chain a load starts, taken only at the top of its chain."""
    if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
        if isinstance(parents.get(node), ast.Attribute):
            return None  # the enclosing chain is handled at its top
        return [node.id], node
    if not (isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load)):
        return None
    parent = parents.get(node)
    if isinstance(parent, ast.Attribute) and parent.value is node:
        return None
    chain = name_chain(node)
    return None if chain is None else (chain, node)


def _use_kind(top: ast.expr, parents: Dict[ast.AST, ast.AST]) -> str:
    parent = parents.get(top)
    if isinstance(parent, ast.Call) and parent.func is top:
        return "direct_call"
    node: ast.AST = top
    while isinstance(parent, _CONTAINERS):
        node, parent = parent, parents.get(parent)
    if node is not top and isinstance(parent, _ASSIGNMENTS):
        return "registry_reference"
    return "direct_reference"


def _connect(collector: Collector, module: Module, symbol: Symbol, use: _Use) -> None:
    if symbol.file == module.path and use.owner == symbol.name:
        return  # a symbol's own body does not connect it
    if module.is_test:
        symbol.test_referenced = True
    else:
        symbol.evidence.setdefault(use.kind, []).append(collector.site(module.path, use.line))


def _record_use(
    collector: Collector, module: Module, target: Target, use: _Use, gaps: Gaps
) -> None:
    if target[0] == "gap":
        record_gap(target, gaps)
    elif target[0] == "module" and use.full and not module.is_test:
        # The module object itself is a value: its names may be reached through
        # whatever holds it.
        site = collector.site(module.path, use.line)
        collector.escaped.setdefault(target[1], "module_escape:%s:%d" % site)
    elif target[0] == "symbols":
        for symbol in target[1]:
            _connect(collector, module, symbol, use)


def references(collector: Collector, gaps: Gaps) -> None:
    for module in collector.modules.values():
        nodes, parents = _context(module.tree)
        for node, owner in nodes:
            found = _chain_at(node, parents)
            if found is None:
                continue
            parts, top = found
            for target, used in collector.resolve_chain(module, parts):
                full = used == len(parts)
                kind = _use_kind(top, parents) if full else "direct_reference"
                _record_use(collector, module, target, _Use(kind, full, owner, top.lineno), gaps)


# ---------------------------------------------------------------------------
# Decorators and exports
# ---------------------------------------------------------------------------


def _defined(module: Module) -> Iterator[Tuple[Def, Symbol]]:
    for node in top_level_defs(module.tree):
        for symbol in module.defs.get(node.name, ()):
            if symbol.line == node.lineno:
                yield node, symbol


def _judge_decorators(collector: Collector, module: Module, node: Def, symbol: Symbol) -> None:
    for deco in node.decorator_list:
        name = last_name(deco)
        if name and name.lstrip("_") in REGISTERING_DECORATORS:
            site = collector.site(module.path, deco.lineno)
            symbol.evidence.setdefault("decorator_registration", []).append(site)
        elif name not in PLAIN_DECORATORS:
            symbol.dynamic.append(f"unknown_decorator:{name or '?'}")


def decorators(collector: Collector) -> None:
    for module in collector.modules.values():
        for node, symbol in _defined(module):
            _judge_decorators(collector, module, node, symbol)


def _star_reexports(collector: Collector, module: Module, site: Site, gaps: Gaps) -> None:
    for star in module.stars:
        source = collector.modules.get(star[1]) if star[0] == "module" else None
        if source is None:
            continue
        for name in [n for n in source.defs if not n.startswith("_")]:
            mark(collector.resolve_name(source.path, name), "package_reexport", site, gaps)


def _reexports(collector: Collector, module: Module, gaps: Gaps) -> None:
    for stmt in module_level(module.tree):
        if not isinstance(stmt, ast.ImportFrom):
            continue
        site = collector.site(module.path, stmt.lineno)
        for alias in stmt.names:
            if alias.name == "*":
                _star_reexports(collector, module, site, gaps)
            else:
                local = alias.asname or alias.name
                mark(collector.resolve_name(module.path, local), "package_reexport", site, gaps)


def exports(collector: Collector, gaps: Gaps) -> None:
    for module in list(collector.modules.values()):
        if module.is_test:
            continue
        for name, line in dunder_all(module.tree):
            site = collector.site(module.path, line)
            mark(collector.resolve_name(module.path, name), "public_export", site, gaps)
        if module.path.name == "__init__.py":
            _reexports(collector, module, gaps)


# ---------------------------------------------------------------------------
# Dynamic access
# ---------------------------------------------------------------------------


def _module_names(collector: Collector) -> Dict[Path, str]:
    names: Dict[Path, str] = {}
    hard = [r for r in collector.index.roots if r.authority in HARD_AUTHORITIES]
    for path in collector.modules:
        root = next((r for r in hard if r.path in path.parents), None)
        if root is None:
            continue
        parts = list(path.relative_to(root.path).with_suffix("").parts)
        if parts and parts[-1] == "__init__":
            parts.pop()
        names[path] = ".".join(parts)
    return names


def _module_target(collector: Collector, module: Module, node: ast.expr) -> Optional[Path]:
    """The module file a name chain such as `pkg.sub` denotes, else None."""
    parts = name_chain(node)
    if not parts:
        return None
    for target, used in collector.resolve_chain(module, parts):
        if target[0] == "module" and used == len(parts):
            return target[1]
    return None


def _mentioned_name(node: ast.Constant) -> Optional[str]:
    text = str(node.value).strip()
    if text.isidentifier():
        return text
    match = _DOTTED.match(text)
    return match.group(1) if match else None


def _string_constants_to_skip(tree: ast.Module) -> Set[int]:
    """Ids of `__all__` entries: an export list names symbols, it does not reach them."""
    return {
        id(node)
        for stmt in all_assignments(tree)
        for node in ast.walk(getattr(stmt, "value", None) or ast.Constant(value=None))
    }


class _DynamicScan:
    """What makes names reachable in ways static reading cannot follow."""

    def __init__(self, collector: Collector) -> None:
        self.collector = collector
        self.names = _module_names(collector)
        self.dotteds = set(self.names.values())
        self.mentioned: Dict[str, str] = {}
        self.attributes: Set[str] = set()
        self.files: Dict[Path, str] = {}

    def mark(self, path: Path, reason: str) -> None:
        self.files.setdefault(path, reason)

    def scan(self, module: Module) -> None:
        rel = self.collector.rel(module.path)
        if any(n.name == "__getattr__" for n in top_level_defs(module.tree)):
            self.mark(module.path, f"module_getattr:{rel}")
        skip = _string_constants_to_skip(module.tree)
        for node in ast.walk(module.tree):
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
                skip.add(id(node.value))  # docstrings and bare strings
            else:
                self._visit(module, node, skip, f"{rel}:{getattr(node, 'lineno', 0)}")
            self._package_scan(module, node, rel)

    def _visit(self, module: Module, node: ast.AST, skip: Set[int], site: str) -> None:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) not in skip:
                self._string(node, site)
        elif isinstance(node, (ast.JoinedStr, ast.BinOp)):
            prefix, whole = self.text_prefix(module, node)
            if prefix and not whole:
                self._module_path(prefix, False, site)
        elif isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load):
            self.attributes.add(node.attr)
        elif isinstance(node, ast.Call):
            self._call(module, node, site)

    def _string(self, node: ast.Constant, site: str) -> None:
        name = _mentioned_name(node)
        if name:
            self.mentioned.setdefault(name, f"string_mention:{site}")
        self._module_path(str(node.value), True, site)

    def _module_path(self, text: str, whole: bool, site: str) -> None:
        """A dotted string naming a project module, or a prefix ending in '.'.

        A single name ("config") is not taken as a module path: it is a dict
        key or a word far more often than an import target.
        """
        text = text.strip()
        if whole and "." in text and text in self.dotteds:
            hits = [path for path, dotted in self.names.items() if dotted == text]
        elif not whole and text.endswith("."):
            hits = [path for path, dotted in self.names.items() if dotted.startswith(text)]
        else:
            return
        for path in hits:
            self.mark(path, f"module_path_string:{site}")

    def text_prefix(self, module: Module, node: ast.expr) -> Tuple[Optional[str], bool]:
        """(known leading text of a string expression, whether that is all of it).

        Constants and `{pkg.__name__}` / `{__name__}` parts are known; the first
        other part ends the prefix.
        """
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value, True
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            return self.text_prefix(module, node.left)[0], False
        if not isinstance(node, ast.JoinedStr):
            return None, False
        text = ""
        for part in node.values:
            piece = self._known_text(module, part)
            if piece is None:
                return text or None, False
            text += piece
        return text, True

    def _known_text(self, module: Module, part: ast.expr) -> Optional[str]:
        if isinstance(part, ast.Constant) and isinstance(part.value, str):
            return part.value
        if not isinstance(part, ast.FormattedValue):
            return None
        value = part.value
        if isinstance(value, ast.Name) and value.id == "__name__":
            return self.names.get(module.path)
        if isinstance(value, ast.Attribute) and value.attr == "__name__":
            path = _module_target(self.collector, module, value.value)
            return self.names.get(path) if path is not None else None
        return None

    def _call(self, module: Module, node: ast.Call, site: str) -> None:
        func = last_name(node.func)
        if func == "globals" or (func == "vars" and not node.args):
            self.mark(module.path, f"namespace_access:{site}")
        elif func in ("eval", "exec") and isinstance(node.func, ast.Name):
            self.mark(module.path, f"eval:{site}")
        elif func == "getattr" and len(node.args) >= 2:
            self._getattr(module, node, site)
        elif func in ("import_module", "__import__") and node.args:
            self._import(module, node, site)

    def _getattr(self, module: Module, node: ast.Call, site: str) -> None:
        if self.text_prefix(module, node.args[1])[1]:
            return  # a constant attribute name is a string mention, not a scan
        path = _module_target(self.collector, module, node.args[0])
        if path is not None:
            self.mark(path, f"dynamic_getattr:{site}")

    def _import(self, module: Module, node: ast.Call, site: str) -> None:
        prefix, whole = self.text_prefix(module, node.args[0])
        if not prefix or prefix.startswith("."):
            file = site.rsplit(":", 1)[0]
            self.collector.unresolved.append(
                {"kind": "unscoped_dynamic_import", "file": file, "line": node.lineno}
            )
            return
        for path, dotted in self.names.items():
            if (dotted == prefix) if whole else dotted.startswith(prefix):
                self.mark(path, f"dynamic_import:{site}")

    def _package_scan(self, module: Module, node: ast.AST, rel: str) -> None:
        """`<pkg>.__path__` (or `__path__` in a package) enumerates its modules."""
        package: Optional[Path] = None
        if isinstance(node, ast.Name) and node.id == "__path__":
            package = module.path.parent if module.path.name == "__init__.py" else None
        elif isinstance(node, ast.Attribute) and node.attr == "__path__":
            init = _module_target(self.collector, module, node.value)
            package = init.parent if init is not None and init.name == "__init__.py" else None
        if package is None:
            return
        reason = f"package_scan:{rel}:{getattr(node, 'lineno', 0)}"
        for path in self.collector.modules:
            if package in path.parents:
                self.mark(path, reason)

    def apply(self) -> None:
        escaped = self.collector.escaped
        for module in self.collector.modules.values():
            for name, symbols in module.defs.items():
                reasons = [self.files.get(module.path), self.mentioned.get(name)]
                if name in self.attributes:
                    reasons.append(escaped.get(module.path))
                for symbol in symbols:
                    symbol.dynamic.extend(r for r in reasons if r)


def dynamic(collector: Collector) -> None:
    scan = _DynamicScan(collector)
    for module in collector.modules.values():
        if not module.is_test:
            scan.scan(module)
    scan.apply()
