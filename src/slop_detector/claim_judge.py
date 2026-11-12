"""Claim against mechanism (H3-2): does the body keep its docstring's promise?

A claim extracted by `claims.py` gets one state:

- SUPPORTED: the body has the structure the kind needs. Evidence of shape,
  never proof that the promise is kept.
- DELEGATED_IN_MODULE: a callee the closed call graph reaches has it.
- UNDECIDED: something unresolved could provide the mechanism or overturn
  the judgment; the reason is kept (`basis`).
- CONTRADICTED: the bounded scope holds a body incompatible with the claim
  and nothing unresolved could overturn it. Absence of evidence alone is
  never a contradiction.
- UNMEASURED: the judgment itself failed. NOT_EVALUATED: retry and cache,
  whose provider must be proven first. PROVIDED_ELSEWHERE is kept for them.

Only reachable own nodes are read (`_own_nodes`), calls resolve through the
module's closed call graph, and a name is trusted only by its import origin.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from typing import Dict, FrozenSet, List, Optional, Set, Tuple

from slop_detector.claims import (
    Claim,
    ClaimExtraction,
    _docstring_line,
    _is_stub,
    _qualname,
    extract_claims,
)
from slop_detector.patterns.declared_intent import _first_sentence
from slop_detector.patterns.placeholder import _is_log_call
from slop_detector.semantic import FunctionNode, _Graph, _own_nodes, _real_bases, _statement_targets

SUPPORTED = "SUPPORTED"
DELEGATED = "DELEGATED_IN_MODULE"
PROVIDED = "PROVIDED_ELSEWHERE"
UNDECIDED = "UNDECIDED"
CONTRADICTED = "CONTRADICTED"
UNMEASURED = "UNMEASURED"
NOT_EVALUATED = "NOT_EVALUATED"
_STATE_KEYS = {
    SUPPORTED: "supported",
    DELEGATED: "delegated_in_module",
    PROVIDED: "provided_elsewhere",
    UNDECIDED: "undecided",
    CONTRADICTED: "contradicted",
    UNMEASURED: "unmeasured",
    NOT_EVALUATED: "not_evaluated",
}
PHASE2 = frozenset({"retry", "cache"})
MAX_DEPTH = 3  # closed callees followed; past it a call is an unresolved path

_FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef)
_LOOPS = (ast.For, ast.AsyncFor, ast.While)
_COMPREHENSIONS = (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)
_OPERATIONS = (ast.BinOp, ast.BoolOp, ast.Compare, ast.Subscript, ast.JoinedStr) + _COMPREHENSIONS
# Builtins that only compute from their arguments (when the name is not rebound).
_PURE_BUILTINS = frozenset(
    {"len", "range", "enumerate", "zip", "sum", "min", "max", "abs", "round", "bool", "isinstance"}
)
_REDUCTIONS = frozenset({"sum", "min", "max"})
_WRAPPER_BUILTINS = frozenset({"staticmethod", "classmethod"})
# str methods with no failure path; on a parameter declared `str` they are
# still an open call (the annotation is not the runtime receiver).
_TOTAL_STR_METHODS = frozenset(
    {"strip", "lstrip", "rstrip", "lower", "upper", "casefold", "title", "capitalize", "swapcase"}
)
# One request, one response, by import origin.
_SINGLE_REQUEST = frozenset(
    {"requests.get", "requests.post", "requests.request", "urllib.request.urlopen", "httpx.get"}
)
_IO_ROOTS = frozenset({"requests", "urllib", "httpx", "aiohttp", "socket", "sqlite3", "http"})
# Concurrency that takes work: a call given the work as an argument, or a
# runner (executor, pool, task group) whose bound name then receives a call.
_CONCURRENT_CALLS = frozenset(
    {
        "asyncio.gather",
        "asyncio.wait",
        "asyncio.as_completed",
        "asyncio.create_task",
        "asyncio.ensure_future",
        "asyncio.to_thread",
        "threading.Thread",
        "multiprocessing.Process",
        "ray.get",
        "dask.compute",
    }
)
# Of those, a Thread or Process runs its work only once started (H3-F06).
_STARTED_BY_CALL = frozenset({"threading.Thread", "multiprocessing.Process"})
_CONCURRENT_RUNNERS = frozenset(
    {
        "concurrent.futures.ThreadPoolExecutor",
        "concurrent.futures.ProcessPoolExecutor",
        "multiprocessing.Pool",
        "multiprocessing.pool.Pool",
        "multiprocessing.pool.ThreadPool",
        "asyncio.TaskGroup",
        "joblib.Parallel",
        "trio.open_nursery",
        "anyio.create_task_group",
    }
)
# Bases that add no method body.
_NEUTRAL_BASES = frozenset({"abc.ABC", "typing.Generic", "typing.Protocol"})


@dataclass(frozen=True)
class Verdict:
    state: str
    basis: str
    detail: str = ""

    def to_dict(self) -> Dict[str, str]:
        return {"state": self.state, "basis": self.basis, "detail": self.detail}


@dataclass
class ClaimJudgment:
    extraction: ClaimExtraction
    verdicts: List[Tuple[Claim, Verdict]] = field(default_factory=list)

    def coverage(self) -> Dict[str, object]:
        """Extraction coverage plus claims by state, by kind and UNDECIDED by reason."""
        out = self.extraction.coverage()
        totals = {key: 0 for key in _STATE_KEYS.values()}
        undecided: Dict[str, int] = {}
        phase2: Dict[str, int] = {}
        by_kind: Dict[str, Dict[str, int]] = {}
        for claim, verdict in self.verdicts:
            key = _STATE_KEYS[verdict.state]
            totals[key] += 1
            kind = by_kind.setdefault(claim.kind, {k: 0 for k in _STATE_KEYS.values()})
            kind[key] += 1
            if verdict.state == UNDECIDED:
                undecided[verdict.basis] = undecided.get(verdict.basis, 0) + 1
            elif verdict.state == NOT_EVALUATED:
                phase2[verdict.basis] = phase2.get(verdict.basis, 0) + 1
        out.update(totals)
        out["undecided_by_reason"] = dict(sorted(undecided.items()))
        out["not_evaluated"] = phase2
        out["by_kind"] = dict(sorted(by_kind.items()))
        return out


class _Module:
    def __init__(self, tree: ast.AST) -> None:
        self.graph = _Graph(tree)

    def shadowed(self, fn: FunctionNode, name: str) -> bool:
        return name in self.graph._module_names or name in self.graph.bound_in(fn)

    def pure_builtin(self, fn: FunctionNode, call: ast.Call, names=_PURE_BUILTINS) -> bool:
        func = call.func
        return isinstance(func, ast.Name) and func.id in names and not self.shadowed(fn, func.id)

    def origin(self, fn: FunctionNode, func: ast.expr) -> Optional[str]:
        """`requests.get` -> requests.get when `requests` has one import origin
        and is bound no other way."""
        parts = []
        while isinstance(func, ast.Attribute):
            parts.append(func.attr)
            func = func.value
        if not isinstance(func, ast.Name) or func.id in self.graph.bound_in(fn):
            return None
        sources = self.graph.import_sources.get(func.id)
        if not sources or len(sources) != 1 or func.id in self.graph.rebound_imports:
            return None
        return ".".join([next(iter(sources))] + list(reversed(parts)))


def _calls(fn: FunctionNode) -> List[ast.Call]:
    return [n for n in _own_nodes(fn) if isinstance(n, ast.Call)]


def _returns(fn: FunctionNode) -> List[ast.Return]:
    return [n for n in _own_nodes(fn) if isinstance(n, ast.Return)]


def _yields(fn: FunctionNode) -> bool:
    return any(isinstance(n, (ast.Yield, ast.YieldFrom)) for n in _own_nodes(fn))


def _in_log(fn: FunctionNode) -> Set[int]:
    """Nodes inside log calls: their arguments never shape the result."""
    return {id(n) for c in _calls(fn) if _is_log_call(c) for n in ast.walk(c)}


def _literal(node: ast.AST) -> bool:
    """A constant, a container of constants, or a comprehension whose element
    is constant (its shape may follow the input: `{k: 0.0 for k in keys}`)."""
    if isinstance(node, ast.Constant):
        return True
    if isinstance(node, ast.UnaryOp):
        return isinstance(node.operand, ast.Constant)
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return all(_literal(e) for e in node.elts)
    if isinstance(node, ast.Dict):
        return all(k is not None and _literal(k) for k in node.keys) and all(
            _literal(v) for v in node.values
        )
    if isinstance(node, ast.DictComp):
        return _literal(node.value)
    if isinstance(node, (ast.ListComp, ast.SetComp)):
        return _literal(node.elt)
    return False


def _reads(mod: _Module, fn: FunctionNode, node: ast.AST) -> bool:
    """The value reads a name or an attribute itself; reads inside a call
    other than a pure builtin belong to that call."""
    opaque: Set[int] = set()
    for c in ast.walk(node):
        if isinstance(c, ast.Call) and not mod.pure_builtin(fn, c):
            opaque |= {id(n) for n in ast.walk(c)}
        elif isinstance(c, ast.Call):
            opaque |= {id(n) for n in ast.walk(c.func)}
    return any(
        isinstance(n, (ast.Name, ast.Attribute))
        and isinstance(n.ctx, ast.Load)
        and id(n) not in opaque
        for n in ast.walk(node)
    )


def _stores_state(mod: _Module, fn: FunctionNode) -> bool:
    """An attribute or item store, or a `global` / `nonlocal` name: the result
    may leave by another way than the return."""
    stores = any(
        isinstance(n, (ast.Attribute, ast.Subscript)) and isinstance(n.ctx, ast.Store)
        for n in _own_nodes(fn)
    )
    return stores or bool(mod.graph.outer_names(fn))


def _falls_through(fn: FunctionNode) -> bool:
    last = fn.body[-1] if fn.body else None
    return not isinstance(last, (ast.Return, ast.Raise))


def _params(fn: FunctionNode) -> Set[str]:
    a = fn.args
    named = a.posonlyargs + a.args + a.kwonlyargs + [x for x in (a.vararg, a.kwarg) if x]
    rebound = {
        n.id for n in _own_nodes(fn) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)
    }
    return {p.arg for p in named} - rebound


class _Calls:
    """The body's calls other than log calls and pure builtins: open ones,
    and the verdicts of the closed callees under the same kind."""

    def __init__(
        self, mod: _Module, fn: FunctionNode, kind: str, depth: int, seen: FrozenSet[FunctionNode]
    ):
        self.open: List[ast.Call] = []
        self.closed: List[Verdict] = []
        for call in _calls(fn):
            if _is_log_call(call) or mod.pure_builtin(fn, call):
                continue
            found = mod.graph.resolve(call, fn) if fn in mod.graph.owner else None
            if found is None:
                self.open.append(call)
            elif found[0] in seen or depth >= MAX_DEPTH:
                self.closed.append(Verdict(UNDECIDED, "depth_bound"))
            else:
                self.closed.append(_judge(mod, found[0], kind, depth + 1, seen | {found[0]}))

    def delegated(self) -> bool:
        return any(v.state in (SUPPORTED, DELEGATED) for v in self.closed)

    def closed_undecided(self) -> bool:
        return any(v.state in (UNDECIDED, UNMEASURED) for v in self.closed)

    def pending(self, reason=None) -> Optional[Verdict]:
        """DELEGATED when a closed callee has the mechanism; UNDECIDED for an
        open call (`reason(call)` names it) or a callee left undecided."""
        if self.delegated():
            return Verdict(DELEGATED, "closed_callee")
        if self.open:
            call = self.open[0]
            return Verdict(UNDECIDED, reason(call) if reason else "open_call", _detail(call.func))
        if self.closed_undecided():
            return Verdict(UNDECIDED, "closed_callee_undecided")
        return None

    def without(self, calls: List[ast.Call]) -> "_Calls":
        """The same calls with `calls` set aside as resolved."""
        view = object.__new__(_Calls)
        view.open = [c for c in self.open if all(c is not x for x in calls)]
        view.closed = self.closed
        return view


def _detail(node: Optional[ast.AST]) -> str:
    """Source-like text for the record (ast.unparse is 3.9+; 3.8 shows dotted
    names and the node type otherwise)."""
    if node is None:
        return "None"
    if hasattr(ast, "unparse"):
        return ast.unparse(node)[:80]
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return _detail(node.value) + "." + node.attr
    return type(node).__name__


# --- computed_result / live_data -------------------------------------------------
def _io_evidence(mod: _Module, fn: FunctionNode, calls: _Calls) -> Optional[Verdict]:
    """An open call whose import origin is an I/O library."""
    for call in calls.open:
        origin = mod.origin(fn, call.func) or ""
        if origin.split(".")[0] in _IO_ROOTS:
            return Verdict(SUPPORTED, "io_call_by_origin", origin)
    return None


def _value_paths(mod: _Module, fn: FunctionNode) -> Optional[Verdict]:
    """A result that may leave by a way other than a value return."""
    returns = _returns(fn)
    if _yields(fn) or not returns or any(r.value is None for r in returns) or _falls_through(fn):
        return Verdict(UNDECIDED, "no_value_return")
    if _stores_state(mod, fn):
        return Verdict(UNDECIDED, "stores_state")
    return None


def _computed(fn: FunctionNode) -> Verdict:
    in_log = _in_log(fn)
    if any(isinstance(n, _OPERATIONS) and id(n) not in in_log for n in _own_nodes(fn)):
        return Verdict(SUPPORTED, "computed_from_inputs")
    return Verdict(UNDECIDED, "no_proof")


def _rule_value(mod: _Module, fn: FunctionNode, depth: int, seen, live: bool = False) -> Verdict:
    calls = _Calls(mod, fn, "live_data" if live else "computed_result", depth, seen)
    valued = [r for r in _returns(fn) if r.value is not None and not _literal(r.value)]
    found = _io_evidence(mod, fn, calls) if live and valued else None
    if found:
        return found
    pending = calls.pending() or _value_paths(mod, fn)
    if pending:
        return pending
    if not valued:
        return Verdict(CONTRADICTED, "literal_result", _detail(_returns(fn)[0].value))
    return Verdict(UNDECIDED, "no_io_proof") if live else _computed(fn)


# --- validation / rejection --------------------------------------------------------
def _declared_str(fn: FunctionNode) -> Set[str]:
    """Parameters annotated `str` that the body does not rebind."""
    named = fn.args.posonlyargs + fn.args.args + fn.args.kwonlyargs
    return {
        p.arg
        for p in named
        if (isinstance(p.annotation, ast.Name) and p.annotation.id == "str")
        or (isinstance(p.annotation, ast.Constant) and p.annotation.value == "str")
    } & _params(fn)


def _open_reason(fn: FunctionNode, call: ast.Call) -> str:
    """`declared_str_only` for a total str method on a parameter declared
    `str`: the annotation does not make the receiver a builtin str."""
    func = call.func
    receiver = getattr(func, "value", None)
    total = (
        isinstance(func, ast.Attribute)
        and func.attr in _TOTAL_STR_METHODS
        and isinstance(receiver, ast.Name)
    )
    constant_args = not call.keywords and all(
        isinstance(a, ast.Constant) and isinstance(a.value, str) for a in call.args
    )
    if (
        total
        and constant_args
        and isinstance(receiver, ast.Name)
        and receiver.id in _declared_str(fn)
    ):
        return "declared_str_only"
    return "open_call"


def _logged_branch(fn: FunctionNode) -> bool:
    """A branch on a run-time test whose body logs: the outcome is reported."""
    for n in _own_nodes(fn):
        if isinstance(n, (ast.If, ast.While, ast.IfExp)) and not isinstance(n.test, ast.Constant):
            test = {id(x) for x in ast.walk(n.test)}
            if any(
                isinstance(x, ast.Call) and _is_log_call(x) and id(x) not in test
                for x in ast.walk(n)
            ):
                return True
    return False


def _outcomes(mod: _Module, fn: FunctionNode, calls: _Calls) -> Tuple[Optional[Verdict], Set[str]]:
    """The outcomes the returns can report, or a verdict a return settles:
    a value from an open call, or one read from the input."""
    params = _params(fn)
    open_ids = {id(c): c for c in calls.open}
    outcomes: Set[str] = {"None"} if _falls_through(fn) else set()
    for r in _returns(fn):
        value = r.value
        if value is None or _literal(value):
            outcomes.add(ast.dump(value) if value is not None else "None")
        elif isinstance(value, ast.Name) and value.id in params:
            outcomes.add("input")
        else:
            inner = [open_ids[id(x)] for x in ast.walk(value) if id(x) in open_ids]
            if inner:
                return (
                    Verdict(UNDECIDED, _open_reason(fn, inner[0]), _detail(inner[0].func)),
                    outcomes,
                )
            if _reads(mod, fn, value):
                return Verdict(SUPPORTED, "outcome_from_input"), outcomes
    return None, outcomes


def _check_paths(mod: _Module, fn: FunctionNode) -> Optional[Verdict]:
    """A result reported by state or by a log line rather than the return."""
    if _stores_state(mod, fn):
        return Verdict(UNDECIDED, "stores_state")
    if _logged_branch(fn):
        return Verdict(UNDECIDED, "outcome_logged")
    return None


def _rule_check(mod: _Module, fn: FunctionNode, depth: int, seen) -> Verdict:
    if any(isinstance(n, (ast.Raise, ast.Assert)) for n in _own_nodes(fn)):
        return Verdict(SUPPORTED, "raise_or_assert")
    if _yields(fn):
        return Verdict(UNDECIDED, "generator")
    calls = _Calls(mod, fn, "validation", depth, seen)
    settled, outcomes = _outcomes(mod, fn, calls)
    if settled:
        return settled
    if len(outcomes) >= 2:
        return Verdict(SUPPORTED, "distinct_outcomes")
    pending = calls.pending(lambda call: _open_reason(fn, call)) or _check_paths(mod, fn)
    if pending:
        return pending
    shown = [_detail(r.value) for r in _returns(fn) if r.value is not None]
    return Verdict(CONTRADICTED, "single_outcome", "; ".join(shown) or "None")


# --- aggregation -------------------------------------------------------------------
def _index(subscript: Optional[ast.AST]) -> Optional[int]:
    """The constant int index of `x[0]` (3.8 wraps it in ast.Index), else None."""
    if not isinstance(subscript, ast.Subscript):
        return None
    index = subscript.slice
    if type(index).__name__ == "Index":
        index = getattr(index, "value", index)  # ast.Index exists only on 3.8
    if (
        isinstance(index, ast.Constant)
        and isinstance(index.value, int)
        and not isinstance(index.value, bool)
    ):
        return index.value
    return None


def _collection(node: ast.AST) -> Optional[str]:
    """A parameter or `self.attr` (the collection a constant index may read)."""
    if isinstance(node, ast.Name) and node.id != "self":
        return node.id
    if (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "self"
    ):
        return "self." + node.attr
    return None


def _single_member(fn: FunctionNode) -> Optional[str]:
    """The one collection every return reads at one constant index, and that
    the body reads no other way outside log calls."""
    returns = _returns(fn)
    keys: Set[Tuple[Optional[str], Optional[int]]] = set()
    for r in returns:
        v = r.value
        if not isinstance(v, ast.Subscript) or _index(v) is None:
            return None
        keys.add((_collection(v.value), _index(v)))
    if len(keys) != 1:
        return None
    return _members_only_indexed(fn, next(iter(keys)))


def _members_only_indexed(
    fn: FunctionNode, key: Tuple[Optional[str], Optional[int]]
) -> Optional[str]:
    name, index = key
    if name is None:
        return None
    in_log = _in_log(fn)
    nodes = _own_nodes(fn)
    parents = {id(child): node for node in nodes for child in ast.iter_child_nodes(node)}
    for n in nodes:
        if id(n) in in_log or _collection(n) != name:
            continue
        parent = parents.get(id(n))
        if not (
            isinstance(parent, ast.Subscript) and parent.value is n and _index(parent) == index
        ):
            return None
    return f"{name}[{index}]"


def _element_call(call: ast.Call, member: str) -> bool:
    func = call.func
    return (
        isinstance(func, ast.Attribute)
        and isinstance(func.value, ast.Subscript)
        and _index(func.value) is not None
        and f"{_collection(func.value.value)}[{_index(func.value)}]" == member
    )


def _single_member_call(fn: FunctionNode) -> Optional[str]:
    """Every return is one call on one element (`self.models[0].predict(x)`)."""
    returns = _returns(fn)
    members = set()
    for r in returns:
        v = r.value
        if not (
            isinstance(v, ast.Call)
            and isinstance(v.func, ast.Attribute)
            and isinstance(v.func.value, ast.Subscript)
            and _index(v.func.value) is not None
        ):
            return None
        members.add((_collection(v.func.value.value), _index(v.func.value)))
    if len(members) != 1:
        return None
    return _members_only_indexed(fn, next(iter(members)))


def _aggregate_evidence(mod: _Module, fn: FunctionNode) -> Optional[Verdict]:
    nodes = _own_nodes(fn)
    if any(isinstance(n, _LOOPS + _COMPREHENSIONS + (ast.Starred,)) for n in nodes):
        return Verdict(SUPPORTED, "iteration")
    if any(
        isinstance(n, ast.Call) and mod.pure_builtin(fn, n, _REDUCTIONS) and n.args for n in nodes
    ):
        return Verdict(SUPPORTED, "reduction")
    return None


def _rule_aggregate(mod: _Module, fn: FunctionNode, depth: int, seen) -> Verdict:
    evidence = _aggregate_evidence(mod, fn)
    if evidence:
        return evidence
    calls = _Calls(mod, fn, "aggregation", depth, seen)
    member = _single_member_call(fn) if calls.open and not calls.delegated() else None
    if member and all(_element_call(c, member) for c in calls.open):
        return Verdict(UNDECIDED, "single_member_open_call", member)
    pending = calls.pending()
    if pending:
        return pending
    member = _single_member(fn)
    if member:
        return Verdict(CONTRADICTED, "single_member_read", f"{member} only")
    return Verdict(UNDECIDED, "no_proof")


# --- pagination ----------------------------------------------------------------------
def _paging_evidence(mod: _Module, fn: FunctionNode) -> Optional[Verdict]:
    nodes = _own_nodes(fn)
    if any(
        isinstance(n, _LOOPS + _COMPREHENSIONS)
        and any(isinstance(x, ast.Call) for x in ast.walk(n))
        for n in nodes
    ):
        return Verdict(SUPPORTED, "loop_with_call")
    if any(isinstance(n, ast.YieldFrom) and isinstance(n.value, ast.Call) for n in nodes):
        return Verdict(SUPPORTED, "yield_from_call")
    if fn in mod.graph.owner and any(
        (mod.graph.resolve(c, fn) or (None,))[0] is fn for c in _calls(fn)
    ):
        return Verdict(SUPPORTED, "recursion")
    return None


def _rule_paginate(mod: _Module, fn: FunctionNode, depth: int, seen) -> Verdict:
    evidence = _paging_evidence(mod, fn)
    if evidence:
        return evidence
    calls = _Calls(mod, fn, "pagination", depth, seen)
    requests = [c for c in calls.open if mod.origin(fn, c.func) in _SINGLE_REQUEST]
    pending = calls.without(requests).pending()
    if pending:
        return pending
    if requests:
        return Verdict(CONTRADICTED, "single_request", mod.origin(fn, requests[0].func) or "")
    returns = _returns(fn)
    if (
        returns
        and not _yields(fn)
        and all(r.value is not None and _literal(r.value) for r in returns)
    ):
        return Verdict(CONTRADICTED, "no_request", _detail(returns[0].value))
    return Verdict(UNDECIDED, "no_proof")


# --- parallel -------------------------------------------------------------------------
def _runners(mod: _Module, fn: FunctionNode) -> Dict[str, str]:
    """Names bound to a concurrency runner (`with Pool() as pool`, `ex = ...`)."""
    bound: Dict[str, str] = {}
    for n in _own_nodes(fn):
        pairs = []
        if isinstance(n, (ast.With, ast.AsyncWith)):
            pairs = [(i.context_expr, i.optional_vars) for i in n.items]
        elif isinstance(n, ast.Assign) and len(n.targets) == 1:
            pairs = [(n.value, n.targets[0])]
        for value, target in pairs:
            origin = mod.origin(fn, value.func) if isinstance(value, ast.Call) else None
            if origin in _CONCURRENT_RUNNERS and isinstance(target, ast.Name):
                bound[target.id] = origin
    return bound


def _elements(value: ast.AST) -> List[ast.AST]:
    """What an assignment binds: the element of a list comprehension, the items
    of a list or tuple display, else the value itself."""
    if isinstance(value, ast.ListComp):
        return [value.elt]
    if isinstance(value, (ast.List, ast.Tuple)):
        return list(value.elts)
    return [value]


def _loop_sources(nodes: List[ast.AST], names: Set[str]) -> Set[str]:
    """`names` plus each collection a `for` loop takes one of them from."""
    return names | {
        n.iter.id
        for n in nodes
        if isinstance(n, (ast.For, ast.AsyncFor))
        and isinstance(n.target, ast.Name)
        and n.target.id in names
        and isinstance(n.iter, ast.Name)
    }


def _started(fn: FunctionNode) -> Set[int]:
    """Calls whose result the function starts: `Thread(...).start()`, a name
    bound to one and then started, or a list of them started in a `for` loop."""
    starts = [
        c.func.value
        for c in _calls(fn)
        if isinstance(c.func, ast.Attribute) and c.func.attr == "start"
    ]
    nodes = _own_nodes(fn)
    names = _loop_sources(nodes, {s.id for s in starts if isinstance(s, ast.Name)})
    started = {id(s) for s in starts if isinstance(s, ast.Call)}
    for n in nodes:
        if (
            isinstance(n, ast.Assign)
            and len(n.targets) == 1
            and isinstance(n.targets[0], ast.Name)
            and n.targets[0].id in names
        ):
            started |= {id(e) for e in _elements(n.value)}
    return started


def _concurrent_call(
    mod: _Module, fn: FunctionNode, call: ast.Call, bound: Dict[str, str], started: Set[int]
) -> Optional[str]:
    origin = mod.origin(fn, call.func)
    if origin in _CONCURRENT_CALLS and (call.args or any(k.arg == "target" for k in call.keywords)):
        return origin if origin not in _STARTED_BY_CALL or id(call) in started else None
    if isinstance(call.func, ast.Call) and mod.origin(fn, call.func.func) in _CONCURRENT_RUNNERS:
        return mod.origin(fn, call.func.func)  # `Parallel(n_jobs=4)(work)`
    func = call.func
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
        return bound.get(func.value.id)
    return None


def _concurrency(mod: _Module, fn: FunctionNode) -> Optional[str]:
    """A concurrent call given work, or a runner whose bound name receives a call."""
    bound = _runners(mod, fn)
    started = _started(fn)
    for call in _calls(fn):
        found = _concurrent_call(mod, fn, call, bound, started)
        if found:
            return found
    return None


def _rule_parallel(mod: _Module, fn: FunctionNode, depth: int, seen) -> Verdict:
    found = _concurrency(mod, fn)
    if found:
        return Verdict(SUPPORTED, "concurrency_structure", found)
    nodes = _own_nodes(fn)
    if isinstance(fn, ast.AsyncFunctionDef) or any(isinstance(n, ast.Await) for n in nodes):
        return Verdict(UNDECIDED, "async")
    pending = _Calls(mod, fn, "parallel", depth, seen).pending()
    if pending:
        return pending
    in_log = _in_log(fn)
    if any(
        isinstance(n, ast.Attribute) and isinstance(n.ctx, ast.Load) and id(n) not in in_log
        for n in nodes
    ):
        return Verdict(UNDECIDED, "no_proof")  # an attribute read may run anything
    return Verdict(CONTRADICTED, "no_concurrent_call")


RULES = {
    "computed_result": _rule_value,
    "live_data": lambda mod, fn, depth, seen: _rule_value(mod, fn, depth, seen, live=True),
    "validation": _rule_check,
    "rejection": _rule_check,
    "aggregation": _rule_aggregate,
    "pagination": _rule_paginate,
    "parallel": _rule_parallel,
}


# --- what may replace or explain the body ------------------------------------------------
def _plain_decorators(mod: _Module, fn: FunctionNode) -> bool:
    """No decorator, or only ones proven by origin to keep the body as
    written: builtin `staticmethod` / `classmethod`, and those the graph
    proves keep the instance (builtin `property`, `functools.cached_property`)."""
    if not fn.decorator_list:
        return True
    klass = mod.graph._class_of.get(fn)
    if klass is None:
        return False
    local = {name for member in klass.body for name in _statement_targets(member)}
    for d in fn.decorator_list:
        if (
            isinstance(d, ast.Name)
            and d.id in _WRAPPER_BUILTINS
            and d.id not in mod.graph._module_names
            and d.id not in local
        ):
            continue
        if not mod.graph._keeps_instance(d, klass, local):
            return False
    return True


def _empty(mod: _Module, fn: FunctionNode) -> bool:
    return mod.graph.intent.is_contract(fn) or _is_stub(fn)


def _extension_point(mod: _Module, fn: FunctionNode, klass: ast.ClassDef) -> bool:
    """The class leaves another (non-special) method for subclasses to fill."""
    return any(
        m is not fn
        and isinstance(m, _FUNCTIONS)
        and not (m.name.startswith("__") and m.name.endswith("__"))
        and _empty(mod, m)
        for m in klass.body
    )


def _module_bases(mod: _Module, klass: ast.ClassDef) -> List[ast.ClassDef]:
    return [
        mod.graph.classes[b.id]
        for b in _real_bases(klass)
        if isinstance(b, ast.Name) and b.id in mod.graph.classes
    ]


def _copies_contract(mod: _Module, fn: FunctionNode, klass: ast.ClassDef) -> bool:
    """A module base's empty method of the same name whose first docstring
    sentence the implementation repeats: the claim is the interface's."""
    mine = ast.get_docstring(fn)
    for base in _module_bases(mod, klass):
        for m in base.body:
            if isinstance(m, _FUNCTIONS) and m.name == fn.name and _empty(mod, m):
                theirs = ast.get_docstring(m)
                if mine and theirs and _first_sentence(mine) == _first_sentence(theirs):
                    return True
    return False


def _unknown_base(mod: _Module, klass: ast.ClassDef, fn: FunctionNode, seen: Set[str]) -> bool:
    """A base on the path that is neither a module class nor one adding no method."""
    for base in _real_bases(klass):
        node = base.value if isinstance(base, ast.Subscript) else base
        if isinstance(node, ast.Name) and node.id in mod.graph.classes:
            if node.id not in seen and _unknown_base(
                mod, mod.graph.classes[node.id], fn, seen | {node.id}
            ):
                return True
        elif mod.origin(fn, node) not in _NEUTRAL_BASES:
            return True
    return False


def _alternative(mod: _Module, fn: FunctionNode, klass: ast.ClassDef) -> Optional[str]:
    if _extension_point(mod, fn, klass):
        return "extension_point_default"
    if _copies_contract(mod, fn, klass):
        return "implements_module_contract"
    if _unknown_base(mod, klass, fn, {klass.name}):
        return "imported_base"
    return None


def _judge(
    mod: _Module,
    fn: FunctionNode,
    kind: str,
    depth: int = 0,
    seen: FrozenSet[FunctionNode] = frozenset(),
) -> Verdict:
    if not _plain_decorators(mod, fn):
        return Verdict(UNDECIDED, "decorated")
    klass = mod.graph._class_of.get(fn)
    if klass is not None and not mod.graph._class_keeps(fn, fn.name):
        return Verdict(UNDECIDED, "class_wrapped")
    verdict = RULES[kind](mod, fn, depth, seen | {fn})
    if verdict.state == CONTRADICTED and klass is not None:
        reason = _alternative(mod, fn, klass)
        if reason:
            return Verdict(UNDECIDED, reason, verdict.detail)
    return verdict


def judge_claims(tree: ast.AST, is_test: Optional[bool]) -> ClaimJudgment:
    """Every extracted claim of the module with its verdict (see module doc)."""
    extraction = extract_claims(tree, is_test)
    result = ClaimJudgment(extraction)
    if not extraction.claims:
        return result
    mod = _Module(tree)
    parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
    functions = {
        (_qualname(parents, n), _docstring_line(n)): n
        for n in ast.walk(tree)
        if isinstance(n, _FUNCTIONS)
    }
    for claim in extraction.claims:
        if claim.kind in PHASE2:
            result.verdicts.append((claim, Verdict(NOT_EVALUATED, "phase2")))
            continue
        try:
            verdict = _judge(mod, functions[(claim.function, claim.line)], claim.kind)
        except Exception as error:  # the channel failed: never read as UNDECIDED
            verdict = Verdict(UNMEASURED, type(error).__name__)
        result.verdicts.append((claim, verdict))
    return result
