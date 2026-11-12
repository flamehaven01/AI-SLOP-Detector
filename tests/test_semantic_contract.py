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
    assert {name: named[name] for name in expected} == {
        name: {why} for name, why in expected.items()
    }
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
    # A classmethod's `cls.m()` is not bound like `self.m()` (R-01b): open.
    assert named["Env.build"] == ("EFFECT_UNKNOWN", {"dynamic"})
    assert named["Env.save"] == ("EFFECT_UNKNOWN", {"dynamic"})  # `cls = type(env)`
    assert named["Env.swap"] == ("EFFECT_UNKNOWN", {"dynamic"})  # `self` is another object here
    assert named["Env.each"] == ("EFFECT_UNKNOWN", {"dynamic"})
    assert named["Env.renamed"] == (
        "EFFECT_UNKNOWN",
        {"unclassified"},
    )  # `self` is not its parameter
    assert named["Env.static"] == ("EFFECT_UNKNOWN", {"unclassified"})
    assert named["Env.bare"] == ("EFFECT_UNKNOWN", {"unclassified"})  # no parameter at all
    assert named["Env.other_name"] == (
        "EFFECT_UNKNOWN",
        {"dynamic"},
    )  # only `self` / `cls` name the instance
    found = [f.function for f in semantic.semantic_findings(ast.parse(R01))]
    assert "Env.save" not in found  # no success_without_effect through a guessed callee


R01B = """
import abc
import functools
try:
    from typing import override
except ImportError:
    from typing_extensions import override

def logged(fn):
    return fn

class Base:
    def render(self, value=None):
        return self

    @property
    def size(self):
        return self.render()

    @size.setter
    def size(self, value):
        self.render()

    @functools.cached_property
    def cached(self):
        return self.render()

    @abc.abstractmethod
    def shape(self):
        return self.render()

    @override
    def marked(self):
        return self.render()

    @logged
    def wrapped(self):
        return self.render()

    @logged
    @property
    def mixed(self):
        return self.render()

    @staticmethod
    def route(self):
        return self.render()

    @staticmethod
    def route_cls(cls):
        return cls.render()

    @classmethod
    def build(cls):
        return cls.default()

    @classmethod
    def default(cls):
        return cls

    @classmethod
    def unbound(cls, value):
        return cls.render(value)

class Other:
    def render(self, value=None):
        return "other"
"""

SHADOWED = """
from widgets import cached_property
from widgets import abstractmethod
from .functools import cached_property as relative_cached
import widgets as functools

class Box:
    property = staticmethod

    def render(self):
        return True

    @cached_property
    def a(self):
        return self.render()

    @functools.cached_property
    def b(self):
        return self.render()

    @abstractmethod
    def c(self):
        return self.render()

    @property
    def d(self):
        return self.render()

    @relative_cached
    def e(self):
        return self.render()

"""

SETTERS = """
class Tray:
    def render(self):
        return True

    def plain(self):
        return True

    @plain.setter
    def f(self, value):
        self.render()

    @logged
    def g(self):
        return True

    @g.setter
    def h(self, value):
        self.render()
"""

REBOUND_DECORATORS = """
import abc
import functools
abc = None
property = None

class Jar:
    functools = None

    def render(self):
        return True

    @property
    def a(self):
        return self.render()

    @abc.abstractmethod
    def b(self):
        return self.render()

    @functools.cached_property
    def c(self):
        return self.render()
"""


def _self_calls(source):
    import ast

    graph = semantic._Graph(ast.parse(source))
    out = {}
    for f in graph.owner:
        calls = [
            n
            for n in semantic._own_nodes(f)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        ]
        setter = any(isinstance(d, ast.Attribute) and d.attr == "setter" for d in f.decorator_list)
        tag = graph.qualname(f) + ("@setter" if setter else "")
        out[tag] = [graph.resolution(c, f)[0] is not None for c in calls]
    return out, graph


def test_a_decorated_caller_keeps_its_instance_only_by_a_known_descriptor():
    closed, _ = _self_calls(R01B)
    assert closed["Base.size"] == [True]  # builtin property
    assert closed["Base.size@setter"] == [True]  # the setter of that property
    assert closed["Base.cached"] == [True]  # functools.cached_property
    assert closed["Base.shape"] == [True]  # abc.abstractmethod
    assert closed["Base.marked"] == [True]  # typing / typing_extensions override
    assert closed["Base.wrapped"] == [False]  # an unknown decorator
    assert closed["Base.mixed"] == [False]  # known + unknown: still unknown
    assert closed["Base.route"] == [False]  # staticmethod: `self` is any argument
    assert closed["Base.route_cls"] == [False]
    assert closed["Base.build"] == [False]  # classmethod: `cls.m()` is not bound like `self.m()`
    assert closed["Base.unbound"] == [False]
    shadowed, _ = _self_calls(SHADOWED)
    assert shadowed == {
        "Box.render": [],
        "Box.a": [False],
        "Box.b": [False],
        "Box.c": [False],
        "Box.d": [False],  # the class binds `property`
        "Box.e": [False],  # a relative `functools` is not the standard one
    }
    setters, _ = _self_calls(SETTERS)
    assert setters == {
        "Tray.render": [],
        "Tray.plain": [],
        "Tray.g": [],
        "Tray.f@setter": [False],  # `plain` is not a property
        "Tray.h@setter": [False],  # `g` is under another decorator, not property
    }
    rebound, _ = _self_calls(REBOUND_DECORATORS)
    # `property` and `abc` bound again by the module, `functools` by the class
    assert rebound == {"Jar.render": [], "Jar.a": [False], "Jar.b": [False], "Jar.c": [False]}


def test_the_descriptor_controls_run_as_python_says():
    namespace = {}
    exec(compile(R01B, "r01b", "exec"), namespace)
    base, other = namespace["Base"], namespace["Other"]
    assert base.route(other()) == "other"  # staticmethod: the argument decides
    assert base.build() is base  # classmethod calling a classmethod
    stranger = other()
    assert base.unbound(stranger) is stranger  # `cls.render(x)`: `x` becomes `self`
    item = base()
    assert (
        item.size is item and item.cached is item and item.marked() is item and item.shape() is item
    )


def test_a_classmethod_argument_is_not_mapped_past_self():
    import ast

    graph = semantic._Graph(ast.parse(R01B))
    dropped, _ = semantic._dropped(graph)
    unbound = next(f for f in graph.owner if f.name == "unbound")
    # `cls.render(value)` passes `value` as `self`; it is not the dropped `value`.
    assert (unbound, "value") not in dropped


R01C = """
import dataclasses
from dataclasses import dataclass

def swap(klass):
    klass.render = lambda self: "swapped"
    return klass

class Meta(type):
    def __new__(mcs, name, bases, namespace):
        namespace["render"] = lambda self: "meta"
        return super().__new__(mcs, name, bases, namespace)

class Plain:
    def render(self):
        return "own"

    def draw(self):
        return self.render()

    def __post_init__(self):
        return None

    def again(self):
        return self.__post_init__()

@dataclass
class Point:
    def render(self):
        return "own"

    def draw(self):
        return self.render()

    def __post_init__(self):
        return None

    def again(self):
        return self.__post_init__()

@dataclasses.dataclass(frozen=True, order=True)
class Frozen:
    def render(self):
        return "own"

    def draw(self):
        return self.render()

@swap
class Swapped:
    def render(self):
        return "own"

    def draw(self):
        return self.render()

@swap
@dataclass
class Stacked:
    def render(self):
        return "own"

    def draw(self):
        return self.render()

class Made(metaclass=Meta):
    def render(self):
        return "own"

    def draw(self):
        return self.render()
"""

DATACLASS_OPTIONS = """
import attr as dataclasses
from dataclasses import dataclass
from pydantic.dataclasses import dataclass as pydantic_dataclass
from .dataclasses import dataclass as relative_dataclass
from dataclasses import dataclass as rebound
rebound = staticmethod(rebound)
FLAG = True
OPTIONS = {}

class Base:
    pass

@dataclass(slots=True)
class Slotted:
    def render(self):
        return True

    def draw(self):
        return self.render()

@dataclass(eq=FLAG)
class Flagged:
    def render(self):
        return True

    def draw(self):
        return self.render()

@dataclass(**OPTIONS)
class Spread:
    def render(self):
        return True

    def draw(self):
        return self.render()

@dataclass(Base)
class Positional:
    def render(self):
        return True

    def draw(self):
        return self.render()

@dataclasses.dataclass
class Attr:
    def render(self):
        return True

    def draw(self):
        return self.render()

@pydantic_dataclass
class Pydantic:
    def render(self):
        return True

    def draw(self):
        return self.render()

@relative_dataclass
class Relative:
    def render(self):
        return True

    def draw(self):
        return self.render()

@rebound
class Rebound:
    def render(self):
        return True

    def draw(self):
        return self.render()

class Keyword(Base, flag=True):
    def render(self):
        return True

    def draw(self):
        return self.render()
"""


def test_a_class_keeps_its_methods_only_without_a_transform_or_by_the_standard_dataclass():
    closed, graph = _self_calls(R01C)
    assert closed["Plain.draw"] == [True] and closed["Plain.again"] == [True]  # controls
    assert closed["Point.draw"] == [True]  # the standard dataclass keeps a plain method
    assert closed["Point.again"] == [False]  # a special method it may generate or call
    assert closed["Frozen.draw"] == [True]  # constant options
    assert closed["Swapped.draw"] == [False]  # a class decorator that replaces the method
    assert closed["Stacked.draw"] == [False]  # dataclass under another decorator
    assert closed["Made.draw"] == [False]  # a metaclass that replaces the method
    states, _, _, details = semantic._with_effect(graph)
    named = {graph.qualname(f): details[f] for f in states}
    assert named["Swapped.draw"] == named["Made.draw"] == named["Point.again"] == {"ambiguous"}
    options, _ = _self_calls(DATACLASS_OPTIONS)
    drawn = {name: calls for name, calls in options.items() if name.endswith(".draw")}
    # slots (a new class), options not constant, or not the standard dataclass by origin
    assert drawn == {
        name + ".draw": [False]
        for name in (
            "Slotted",
            "Flagged",
            "Spread",
            "Positional",
            "Attr",
            "Pydantic",
            "Relative",
            "Rebound",
            "Keyword",
        )
    }


def test_the_class_transform_controls_run_as_python_says():
    namespace = {}
    exec(compile(R01C, "r01c", "exec"), namespace)
    assert namespace["Plain"]().draw() == "own"
    assert namespace["Point"]().draw() == "own"
    assert namespace["Frozen"]().draw() == "own"
    assert namespace["Swapped"]().draw() == "swapped"  # a closed edge to `render` would be wrong
    assert namespace["Stacked"]().draw() == "swapped"
    assert namespace["Made"]().draw() == "meta"


SUCCESS_SHAPES = """
class SendResult:
    def __init__(self, ok=False, verbose=False):
        self.ok = ok

class Status:
    SUCCESS = "success"

def persist(record):
    return None

def save_status(record):
    persist(record)
    return {"status": "ok", "id": record}

def save_flag(record):
    persist(record)
    return {"success": True}

def save_result(record):
    persist(record)
    return SendResult(ok=True)

def save_member(record):
    persist(record)
    return Status.SUCCESS

def send(client, payload):
    try:
        client.post(payload)
    except Exception:
        pass
    return {"ok": True}

def save_computed(record):
    persist(record)
    return {"success": record}

def read_flag(conn):
    persist(conn)
    return conn.connected

def save_verbose(record):
    persist(record)
    return SendResult(verbose=True)

def save_failed(record):
    persist(record)
    return {"status": "error"}

def save_real(record):
    persist(record)
    record.saved = True
    return {"status": "ok"}

def save_mixed(record):
    persist(record)
    return {"status": "ok", "success": record}
"""


def test_a_constant_success_report_is_success_however_it_is_shaped():
    import ast

    found = {(f.function, f.kind) for f in semantic.semantic_findings(ast.parse(SUCCESS_SHAPES))}
    for name in ("save_status", "save_flag", "save_result", "save_member"):
        assert (name, "success_without_effect") in found, name
    assert (
        "send",
        "failure_reported_as_success",
    ) in found  # {"ok": True} after a swallowed failure
    # a computed success entry, a run-time member, a flag that is not success,
    # a failure status, a real effect, one literal claim beside a computed one
    for name in (
        "save_computed",
        "read_flag",
        "save_verbose",
        "save_failed",
        "save_real",
        "save_mixed",
    ):
        assert (name, "success_without_effect") not in found, name


HANDLERS_AND_CHECKS = """
import logging
from framework import Base

logger = logging.getLogger(__name__)
REQUIRED = ("id", "email")

def charge(gateway, item):
    if not item:
        return False
    try:
        ok = gateway.submit(item)
    except Exception:
        logger.exception("charge failed")
        return True
    return ok

def charge_report(gateway, item):
    if not item:
        return {"status": "rejected"}
    try:
        receipt = gateway.submit(item)
    except Exception:
        logger.exception("charge failed")
        return {"status": "ok"}
    return {"status": receipt}

def charge_error_dict(gateway, item):
    try:
        receipt = gateway.submit(item)
    except Exception as exc:
        return {"available": True, "error": str(exc)}
    return {"receipt": receipt}

def charge_honest(gateway, item):
    try:
        ok = gateway.submit(item)
    except Exception:
        return False
    return ok

def charge_reraise(gateway, item):
    try:
        ok = gateway.submit(item)
    except Exception:
        logger.exception("charge failed")
        raise
    return ok

def charge_narrow(gateway, item):
    try:
        ok = gateway.submit(item)
    except KeyError:
        return {"status": "ok"}
    return ok

def no_work(item):
    try:
        value = item
    except Exception:
        return {"status": "ok"}
    return value

def validate_record(record):
    for name in REQUIRED:
        if name not in record:
            logger.debug("missing %s", name)
    return True

def enabled():
    return True

def serialize(preview):
    return {"ok": True, "effect": preview.effect}

def verify_sizes(expected, actual):
    assert expected.size == actual.size
    return True

def healthz(timeout_s=None):
    del timeout_s
    return {"status": "ok"}

def reset(record):
    record = {}
    return True

class ScanResult:
    pass

def start_scan(root):
    return ScanResult("scan", True, f"Scanned {root}")

def ping(conn):
    try:
        conn.send()
    except Exception:
        return {"success": conn.ok}
    return {"success": True}

def summarize(result):
    return {"passed": result.passed}

def validate_strict(record):
    if "id" not in record:
        return False
    return True

class Plugin(Base):
    def supports(self, feature):
        if feature:
            logger.debug("asked for %s", feature)
        return True
"""


def test_a_handler_or_a_check_that_answers_success_whatever_happened_is_reported():
    import ast

    found = {
        (f.function, f.kind) for f in semantic.semantic_findings(ast.parse(HANDLERS_AND_CHECKS))
    }
    # the handler's own answer is a success report, whatever the function's other returns
    assert ("charge_report", "failure_reported_as_success") in found
    # a bare True (a fail-open default far more often than a disguise), a report
    # carrying the error, an honest False, a re-raise, a narrow handler, no work
    # ... and a report built from what the input says (`{"success": conn.ok}`)
    for name in (
        "charge",
        "charge_error_dict",
        "charge_honest",
        "charge_reraise",
        "charge_narrow",
        "no_work",
        "ping",
    ):
        assert (name, "failure_reported_as_success") not in found, name
    # a check that reads its input and passes whatever it finds
    assert ("validate_record", "success_without_effect") in found
    # the input only shown in the report's text: the answer does not depend on it
    assert ("start_scan", "success_without_effect") in found
    # no input read; a failing path; a signature an outside base fixes; an answer
    # built from the input (a serializer); a member read from the input
    # ... and a check that asserts (it fails loudly on a bad input)
    # ... and an input only deleted or overwritten, never read (`del timeout_s`)
    for name in (
        "enabled",
        "validate_strict",
        "Plugin.supports",
        "serialize",
        "summarize",
        "verify_sizes",
        "healthz",
        "reset",
    ):
        assert (name, "success_without_effect") not in found, name


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
    key = dict(
        file_path=str(path),
        file_size=stat.st_size,
        mtime_ns=stat.st_mtime_ns,
        content_hash="h",
        config_fingerprint="c",
    )
    # v42: four open-call kinds, v43: first five-kind labels, v44: before T27b, v45: before R-01,
    # v46: before R-01b, v47: before R-01c, v48: before structured success reports,
    # v49: before the read check counted only loads
    older_engines = ("v37", "v42", "v43", "v44", "v45", "v46", "v47", "v48", "v49")
    for older in ("analysis-cache-" + v for v in older_engines):
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
            capture_output=True,
            text=True,
            check=True,
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
