"""What the semantic channel could not decide is reported, and its output
survives the cache unchanged.

`semantic_coverage` counts the module's functions by effect state and the
reasons an effect stayed unknown; an UNKNOWN is never a finding and never
no-effect. A channel failure leaves the file analysed (state UNMEASURED,
never cached), and neither the findings nor the coverage touch the score.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import slop_detector.semantic as semantic
from slop_detector.analysis_cache import (
    CACHE_ENGINE_VERSION,
    FileAnalysisCache,
    deserialize_file_analysis,
    serialize_file_analysis,
)
from slop_detector.core import SlopDetector

SOURCE = """
class Repo:
    def save(self, record):
        return self._write(record)

    def _write(self, payload):
        return True

def push(client, record):
    client.post("/records", json=record)
    return True

def remember(cache, record):
    cache[record.id] = record

async def settle(future):
    await future

def relay(client, record):
    return push(client, record)
"""


def _write(tmp_path: Path, source: str = SOURCE) -> Path:
    path = tmp_path / "mod.py"
    path.write_text(textwrap.dedent(source), encoding="utf-8")
    return path


def test_coverage_counts_effect_states_and_unknown_reasons(tmp_path):
    result = SlopDetector(read_only=True).analyze_file(str(_write(tmp_path)))
    assert result.semantic_coverage == {
        "state": "MEASURED",
        "functions": 6,
        "effect_states": {
            "EFFECT_OBSERVED": 1,
            "EFFECT_UNKNOWN": 3,
            "NO_EFFECT_IN_CLOSED_GRAPH": 2,
        },
        "unknown_reasons": {"external_awaitable": 1, "open_call": 1, "unknown_callee": 1},
        "open_call_details": {
            "ambiguous": 0,
            "dynamic": 1,
            "external": 0,
            "module_defined_unresolved": 0,
            "unclassified": 0,
        },
    }
    assert result.to_dict()["semantic_coverage"] == result.semantic_coverage


OPEN_CALLS = """
import json
from backend import push as remote_push

class Store:
    def save(self, record):
        return self._write(record)

    def _write(self, record):
        return True

    def flush(self):
        self.db.commit()

class Fast(Store):
    def _write(self, record):
        return False

def external_module(record):
    return json.dumps(record)

def external_name(record):
    remote_push(record)

def local_import(record):
    from backend import send
    send(record)

def builtin_call(path):
    open(path)

def callback(fn, record):
    fn(record)

def dispatch(obj, name, record):
    getattr(obj, name)(record)

def handler_table(handlers, key):
    handlers[key]()

def client_call(client, record):
    client.send(record)

def twice(record):
    return True

def twice(record):
    return False

def use_twice(record):
    twice(record)

@decorate
def wrapped(record):
    return True

def use_wrapped(record):
    wrapped(record)

def closed(record):
    return _helper(record)

def _helper(record):
    return record is not None

def unknown_name(record):
    mystery(record)

def made(record):
    return Store()

def _remember(cache, record):
    cache[record] = record

def mixed(cache, client, record):
    client.send(record)
    _remember(cache, record)
"""


def test_an_open_call_says_why_its_target_is_unknown():
    import ast

    graph = semantic._Graph(ast.parse(OPEN_CALLS))
    states, _, reasons, details = semantic._with_effect(graph)
    named = {graph.qualname(f): (states[f], reasons[f], details[f]) for f in states}
    expected = {
        "Store.save": "dynamic",  # a subclass in the module overrides _write
        "Store.flush": "dynamic",  # a method of an object held at runtime
        "external_module": "external",
        "external_name": "external",
        "local_import": "external",
        "builtin_call": "external",
        "callback": "dynamic",
        "dispatch": {"dynamic", "external"},  # getattr(...) itself is a builtin call
        "handler_table": "dynamic",
        "client_call": "dynamic",  # the caller decides what `client` is
        "use_twice": "ambiguous",
        "use_wrapped": "ambiguous",
        "unknown_name": "unclassified",
        "made": "module_defined_unresolved",  # Store's constructor is not followed
    }
    for name, why in expected.items():
        state, found, detail = named[name]
        assert state == "EFFECT_UNKNOWN" and "open_call" in found, name
        assert detail == (why if isinstance(why, set) else {why}), (name, detail)
    assert named["closed"] == ("NO_EFFECT_IN_CLOSED_GRAPH", set(), set())
    assert named["mixed"] == ("EFFECT_OBSERVED", set(), set())  # observed through a callee
    # A detail exists exactly when the function is unknown through an open call.
    for state, found, detail in named.values():
        assert bool(detail) == ("open_call" in found)


EVIDENCE = """
from typing import Generic, TypeVar
from unittest import TestCase
import unittest
from backend import Base

T = TypeVar("T")

CLIENT = object()
HANDLER = CLIENT

class Store:
    @classmethod
    def build(cls):
        return cls

    def keep(self, record):
        return True

class Fast(Store):
    def go(self, record):
        return self.keep(record)

    def gone(self, record):
        return self.missing(record)

class Case(TestCase):
    def test_one(self):
        self.assertTrue(1)

class Dotted(unittest.TestCase):
    def test_two(self):
        self.assertTrue(1)

class Mixed(Store, TestCase):
    def test_three(self):
        self.assertTrue(1)

class Failure(Exception):
    def text(self):
        return self.with_traceback(None)

class Injected(TestCase):
    def setUp(self):
        self.check = print

    def test_four(self):
        self.check()

@decorate
class Boxed(TestCase):
    def test_five(self):
        self.assertTrue(1)

class Faster(Fast):
    def go_far(self, record):
        return self.keep(record)

class Plain(Store, object):
    def go_plain(self, record):
        return self.keep(record)

class Hooked:
    def setUp(self):
        self.hook = print

class Child(Hooked):
    def run(self):
        self.hook()

class WithMeta(TestCase, metaclass=Registry):
    def test_six(self):
        self.assertTrue(1)

class Typed(Generic[T]):
    def items(self):
        return self.mro()

class Base(Base):
    def own(self):
        return True

class Shadowed(Base):
    def run(self):
        return self.other()

class Twice(TestCase):
    def test_seven(self):
        self.assertTrue(1)

class Twice(TestCase):
    def test_seven(self):
        self.assertTrue(1)

def via_twice(record):
    return Twice.test_seven(record)

def module_callable(record):
    return HANDLER(record)

def late(record):
    return later(record)
    later = record

class Tools:
    def helper(self):
        return True

class Mid(TestCase, Tools):
    pass

class Leaf(Mid):
    def test_eight(self):
        return self.helper()

@decorate
class Painted(Tools):
    pass

class Brush(Painted):
    def stroke(self):
        return self.helper()

class Cast(Tools, metaclass=Registry):
    pass

class Mold(Cast):
    def shape(self):
        return self.helper()

@decorate
class Dressed(Tools):
    def wear(self):
        return self.helper()

@decorate
class Hooked2(Hooked):
    def run(self):
        self.hook()

class Kid(Twice):
    def play(self):
        return self.test_seven()

def local_value(record):
    items = []
    items.append(record)

def local_callable(record):
    fn = lambda r: r
    return fn(record)

def caught(record):
    try:
        pass
    except Exception as error:
        error.with_traceback(None)

def expression_root(a, b):
    (a or b).close()

def module_value(record):
    CLIENT.send(record)

def constructor(record):
    return Store()

def boxed(record):
    return Boxed()

def via_class(record):
    return Store.build()

def class_attr(record):
    return Store.absent()

def nested(record):
    def inner(x):
        return x
    return inner(record)

def nested_rebound(record):
    def inner(x):
        return x
    inner = record
    return inner(record)

def nested_wrapped(record):
    @decorate
    def inner(x):
        return x
    return inner(record)

def nested_attr(record):
    def inner(x):
        return x
    return inner.cache_clear()

def via_boxed(record):
    return Boxed.test_five()

def undefined(record):
    return mystery(record)
"""


def test_an_open_call_is_classified_only_by_evidence_the_module_shows():
    import ast

    graph = semantic._Graph(ast.parse(EVIDENCE))
    states, _, reasons, details = semantic._with_effect(graph)
    named = {graph.qualname(f): details[f] for f in states}
    expected = {
        "local_value": "dynamic",  # a value the caller assigned
        "local_callable": "dynamic",
        "caught": "dynamic",  # the exception object raised at run time
        "expression_root": "dynamic",
        "module_value": "dynamic",  # a value the module assigned
        "Case.test_one": "external",  # inherited from an imported base only
        "Dotted.test_two": "external",
        "Mixed.test_three": "unclassified",  # a module base beside an imported one
        "Failure.text": "unclassified",  # a builtin base is not an import
        "Injected.test_four": "ambiguous",  # set on the instance
        "Boxed.test_five": "unclassified",  # a class decorator may add the method
        "Fast.go": "module_defined_unresolved",  # defined by the module base Store
        "Fast.gone": "unclassified",  # no base in the module defines it
        "constructor": "module_defined_unresolved",
        "boxed": "ambiguous",  # a decorated class
        "via_class": "module_defined_unresolved",
        "class_attr": "unclassified",
        "nested": "module_defined_unresolved",
        "nested_rebound": "ambiguous",
        "Faster.go_far": "module_defined_unresolved",  # through Fast to Store
        "Plain.go_plain": "module_defined_unresolved",  # `object` adds nothing
        "Child.run": "ambiguous",  # the module base sets it on the instance
        "WithMeta.test_six": "unclassified",  # a metaclass may add the method
        "Typed.items": "external",
        "Shadowed.run": "unclassified",  # `Base` is imported and defined again
        "nested_wrapped": "ambiguous",
        "nested_attr": "unclassified",  # an attribute of a nested def
        "via_boxed": "ambiguous",
        "Twice.test_seven": "unclassified",  # the module binds the class twice
        "via_twice": "ambiguous",
        "module_callable": "dynamic",
        "late": "unclassified",  # bound only after the return
        "Leaf.test_eight": "unclassified",  # TestCase precedes Tools in Mid's bases
        "Brush.stroke": "unclassified",  # a decorator on the path may add the method
        "Mold.shape": "unclassified",  # so may a metaclass
        "Dressed.wear": "unclassified",  # its own decorator may add the method
        "Kid.play": "unclassified",  # its base is bound twice
        "Hooked2.run": "ambiguous",  # the module base sets it, decorator or not
        "undefined": "unclassified",
    }
    assert {name: named[name] for name in expected} == {name: {why} for name, why in expected.items()}
    # A label explains an open call: no call joins or leaves the closed graph.
    for f in states:
        assert bool(details[f]) == ("open_call" in reasons[f]), graph.qualname(f)


REBOUND = """
import backend
import json
try:
    import ujson as fast
except ImportError:
    import json as fast

import os
import yaml
from Bio import Entrez
try:
    from kit import Layout
except ImportError:
    class Layout:
        pass

backend = backend.connect()
Entrez.email = "x"  # a store into the module object, not a new binding
os.environ["MODE"] = "test"

def save(record):
    backend.send(record)

def save_chain(record):
    backend.session.send(record)

def dump(record):
    return json.dumps(record)

def fast_dump(record):
    return fast.dumps(record)

def local_rebound(record):
    import pickle
    pickle = record
    return pickle.dumps(record)

def local_import(record):
    import pickle
    return pickle.dumps(record)

class Remote(backend.Base):
    def run(self):
        return self.go()

class Fancy(Layout):
    def run(self):
        return self.go()

def swap():
    global yaml
    yaml = None

def use_yaml(record):
    return yaml.dump(record)

def search(term):
    return Entrez.esearch(term)

def joined(name):
    return os.path.join(name)
"""


def test_an_import_bound_again_is_not_explained_as_external():
    import ast

    graph = semantic._Graph(ast.parse(REBOUND))
    states, _, _, details = semantic._with_effect(graph)
    named = {graph.qualname(f): details[f] for f in states}
    assert named == {
        "save": {"ambiguous"},  # imported, then assigned: which one runs is not shown
        "save_chain": {"ambiguous"},
        "dump": {"external"},  # imported only
        "fast_dump": {"external"},  # two imports, no other binding
        "local_rebound": {"ambiguous"},
        "local_import": {"external"},
        "Remote.run": {"unclassified"},  # the base's root is bound again
        "Fancy.run": {"unclassified"},  # imported, or the fallback class
        "swap": set(),  # `global`: an observed effect
        "use_yaml": {"ambiguous"},  # a function rebinds it
        "search": {"external"},
        "joined": {"external"},
    }


T27B = """
import ctypes
try:
    import cv2
except ImportError:
    from scipy import ndimage
try:
    import ujson as json
except ImportError:
    import json
try:
    from fast import blur
except ImportError:
    def blur(image):
        return image

class Logger:
    CURRENT = None

    def logkv(self, key):
        return key

class Env:
    def render(self):
        return True

    def draw(self):
        return self.render()

    def kind(self, env):
        cls = type(env)
        return cls.__dict__.get("render")

def literal_dict(key):
    return {"a": 1}.get(key)

def literal_list(item):
    return ["mon", "tue"].index(item)

def literal_set(items):
    return {"a", "b"}.issubset(items)

def literal_tuple(item):
    return (1, 2).count(item)

def literal_text(name):
    return f"{name}:x".encode()

def literal_comprehension(rows):
    return [r for r in rows].count(None)

def literal_dict_comprehension(rows):
    return {r: r for r in rows}.values()

def literal_set_comprehension(rows):
    return {r for r in rows}.pop()

def patched_forward(self, x):
    return self.q_proj(x)

def patched_factory(cls, x):
    return cls.build(x)

def rebound_self(value):
    self = value
    return self.curve_basis()

def orphan(record):
    return self.go(record)

def chosen_or(runner, record):
    return (runner or json.dumps)(record)

def chosen_if(flag, record):
    return (json.dumps if flag else json.loads)(record)

def chosen_walrus(record):
    return (fn := json.dumps)(record)

def walrus_root(path):
    return (p := path.parent).exists()

def array_type(values):
    return (ctypes.c_int32 * len(values))(*values)

def immediate_lambda(record):
    return (lambda r: r)(record)

def except_import(mask):
    return ndimage.label(mask)

def two_imports(record):
    return json.dumps(record)

def fallback_def(image):
    return blur(image)

def class_attribute(key):
    Logger.CURRENT.logkv(key)

def method_attribute():
    return Env.render.cache_clear()
"""


def test_t27b_labels_follow_the_evidence_the_source_shows():
    import ast

    graph = semantic._Graph(ast.parse(T27B))
    states, _, _, details = semantic._with_effect(graph)
    named = {graph.qualname(f): details[f] for f in states}
    expected = {
        "literal_dict": {"external"},  # a method of a builtin literal
        "literal_list": {"external"},
        "literal_set": {"external"},
        "literal_tuple": {"external"},
        "literal_text": {"external"},
        "literal_comprehension": {"external"},
        "literal_dict_comprehension": {"external"},
        "literal_set_comprehension": {"external"},
        "patched_forward": {"dynamic"},  # `self` is a parameter of a top-level function
        "patched_factory": {"dynamic"},
        "rebound_self": {"dynamic"},  # `self` assigned a value
        "orphan": {"unclassified"},  # `self` bound nowhere
        "chosen_or": {"dynamic"},  # which callable runs is chosen at run time
        "chosen_if": {"dynamic"},
        "chosen_walrus": {"dynamic"},
        "walrus_root": {"dynamic"},
        "array_type": {"dynamic"},  # `len` only builds a value
        "immediate_lambda": {"unclassified"},  # deferred: the callee is written in place
        "except_import": {"external"},  # imported in an except body
        "two_imports": {"external"},  # imported in try and except, nothing else
        "fallback_def": {"ambiguous"},  # imported, or the fallback def
        "class_attribute": {"dynamic"},  # a class attribute holds a run-time value
        "method_attribute": {"unclassified"},  # an attribute of a method, not a value
        "Env.kind": {"dynamic"},  # `cls` is a local value here
        "Env.draw": set(),  # the class's own method: still a closed edge
    }
    assert {name: named[name] for name in expected} == expected
    draw = next(f for f in states if graph.qualname(f) == "Env.draw")
    assert states[draw] == "NO_EFFECT_IN_CLOSED_GRAPH"


R01 = """
class Env:
    def render(self):
        return True

    def draw(self):
        return self.render()

    @classmethod
    def build(cls):
        return cls.make()

    def make(cls):
        return True

    def save(self, env):
        cls = type(env)
        cls.render()
        return True

    def swap(self, other):
        self = other
        self.render()
        return True

    def each(self, items):
        for self in items:
            self.render()
        return True

    def renamed(this):
        self.render()
        return True

    @staticmethod
    def static(value):
        self.render()
        return True

    def bare():
        self.render()
        return True

    def other_name(this):
        this.render()
        return True
"""


def test_self_or_cls_bound_again_is_not_the_class_s_own_method():
    import ast

    graph = semantic._Graph(ast.parse(R01))
    states, _, _, details = semantic._with_effect(graph)
    named = {graph.qualname(f): (states[f], details[f]) for f in states}
    closed = ("NO_EFFECT_IN_CLOSED_GRAPH", set())
    assert named["Env.draw"] == closed  # its own instance: still a closed edge
    assert named["Env.build"] == closed  # a classmethod's own class
    assert named["Env.save"] == ("EFFECT_UNKNOWN", {"dynamic"})  # `cls = type(env)`
    assert named["Env.swap"] == ("EFFECT_UNKNOWN", {"dynamic"})  # `self` is another object here
    assert named["Env.each"] == ("EFFECT_UNKNOWN", {"dynamic"})
    assert named["Env.renamed"] == ("EFFECT_UNKNOWN", {"unclassified"})  # `self` is not its parameter
    assert named["Env.static"] == ("EFFECT_UNKNOWN", {"unclassified"})
    assert named["Env.bare"] == ("EFFECT_UNKNOWN", {"unclassified"})  # no parameter at all
    assert named["Env.other_name"] == ("EFFECT_UNKNOWN", {"dynamic"})  # only `self` / `cls` name the instance
    found = [f.function for f in semantic.semantic_findings(ast.parse(R01))]
    assert "Env.save" not in found  # no success_without_effect through a guessed callee


def test_coverage_of_a_module_without_functions_is_measured_and_empty(tmp_path):
    result = SlopDetector(read_only=True).analyze_file(str(_write(tmp_path, "VALUE = 1\n")))
    assert result.semantic_coverage["state"] == "MEASURED"
    assert result.semantic_coverage["functions"] == 0
    assert set(result.semantic_coverage["effect_states"].values()) == {0}


def test_a_channel_failure_is_unmeasured_and_leaves_the_score(tmp_path, monkeypatch):
    path = _write(tmp_path)
    measured = SlopDetector(read_only=True).analyze_file(str(path))

    def explode(tree):
        raise RecursionError("too deep")

    monkeypatch.setattr(semantic, "semantic_analysis", explode)
    detector = SlopDetector()
    detector._analysis_cache = FileAnalysisCache(tmp_path / "cache.db")
    failed = detector.analyze_file(str(path))
    assert failed.semantic_findings == []
    assert failed.semantic_coverage == {"state": "UNMEASURED", "error_type": "RecursionError"}
    assert failed.deficit_score == measured.deficit_score
    assert failed.status == measured.status
    # Not cached: the next run measures again.
    monkeypatch.undo()
    again = detector.analyze_file(str(path))
    assert again.semantic_coverage["state"] == "MEASURED"


def test_the_cache_returns_findings_and_coverage_exactly(tmp_path):
    path = _write(tmp_path)
    fresh = SlopDetector(read_only=True).analyze_file(str(path))
    assert fresh.semantic_findings
    restored = deserialize_file_analysis(serialize_file_analysis(fresh))
    assert restored.to_dict()["semantic_findings"] == fresh.to_dict()["semantic_findings"]
    assert restored.semantic_coverage == fresh.semantic_coverage

    detector = SlopDetector()
    detector._analysis_cache = FileAnalysisCache(tmp_path / "cache.db")
    first = detector.analyze_file(str(path))
    hit = detector.analyze_file(str(path))
    for key in ("semantic_findings", "semantic_coverage", "deficit_score", "status"):
        assert hit.to_dict()[key] == first.to_dict()[key] == fresh.to_dict()[key]


def test_a_legacy_payload_restores_as_not_recorded(tmp_path):
    fresh = SlopDetector(read_only=True).analyze_file(str(_write(tmp_path)))
    data = json.loads(serialize_file_analysis(fresh))
    del data["semantic_findings"], data["semantic_coverage"]
    restored = deserialize_file_analysis(json.dumps(data))
    assert restored.semantic_findings == []
    assert restored.semantic_coverage == {}
    assert restored.deficit_score == fresh.deficit_score


def test_an_entry_from_an_older_engine_is_not_served(tmp_path):
    path = _write(tmp_path)
    fresh = SlopDetector(read_only=True).analyze_file(str(path))
    cache = FileAnalysisCache(tmp_path / "cache.db")
    stat = path.stat()
    key = dict(file_path=str(path), file_size=stat.st_size, mtime_ns=stat.st_mtime_ns,
               content_hash="h", config_fingerprint="c")
    # v42: four open-call kinds, v43: first five-kind labels, v44: before T27b, v45: before R-01
    for older in ("analysis-cache-v37", "analysis-cache-v42", "analysis-cache-v43", "analysis-cache-v44", "analysis-cache-v45"):
        cache.put(result=fresh, engine_version=older, **key)
        assert cache.get(engine_version=CACHE_ENGINE_VERSION, **key) is None
        assert cache.get(engine_version=older, **key) is not None


def test_the_output_does_not_depend_on_hash_order(tmp_path):
    path = _write(
        tmp_path,
        SOURCE
        + """
def _audit(entry):
    return entry is not None

def _trace(entry):
    return entry is not None

def report(entry):
    _trace(entry)
    _audit(entry)
    return True
""",
    )
    script = (
        "import ast, json, sys\n"
        "from slop_detector.semantic import semantic_analysis\n"
        "found, cov = semantic_analysis(ast.parse(open(sys.argv[1]).read()))\n"
        "print(json.dumps([[f.to_dict() for f in found], cov]))\n"
    )
    src = str(Path(semantic.__file__).resolve().parents[1])
    runs = {
        subprocess.run(
            [sys.executable, "-c", script, str(path)],
            env={**os.environ, "PYTHONHASHSEED": seed, "PYTHONPATH": src},
            capture_output=True, text=True, check=True,
        ).stdout
        for seed in ("0", "1", "2", "3")
    }
    assert len(runs) == 1
    assert "success_without_effect" in runs.pop()


def test_an_interface_stub_file_skips_the_channel_and_says_so(tmp_path):
    path = _write(
        tmp_path,
        """
        from typing import Protocol

        class Store(Protocol):
            def save(self, record: object) -> bool: ...
        """,
    )
    result = SlopDetector(read_only=True).analyze_file(str(path))
    assert result.semantic_findings == []
    assert result.semantic_coverage == {"state": "SKIPPED"}
