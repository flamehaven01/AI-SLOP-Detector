"""v3.10 placeholder intent: a declared contract is not unfinished code.

Found by the cross-domain precision study (stage-1 sample: 0 true positives in
42 `return_constant_stub` / `not_implemented` / `interface_only_class` /
`ellipsis_placeholder` findings) and measured on the 18-repository corpus:
of 514 placeholder-family findings, 336 sit where the code declares its
intent: a constant property or class-level accessor (141), an ABC or
Protocol class (74), a base method its subclasses override (57), an override
of a base method (52), a decorator-implemented body (12).

Contract (evidence from the same module only, so a file's result depends on
the file):
- a method of a class declared abstract (ABC / ABCMeta / Protocol base) or a
  base method that a subclass in the module overrides is a contract: no
  placeholder finding;
- an override of a method its module-level base defines, returning a constant
  or None, is a hook implementation (capability flag), not a stub; an
  override that is `pass` or raises NotImplementedError is still reported;
- a property / classmethod / staticmethod returning a constant is a declared
  accessor; a `...` body under another decorator is implemented by the
  decorator;
- `interface_only_class` skips declared interfaces and classes their module
  subclasses, and does not count constant accessors as placeholders;
- a concrete subclass of an ABC is not itself a declared interface.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from slop_detector.core import SlopDetector

PLACEHOLDER_IDS = {
    "pass_placeholder",
    "ellipsis_placeholder",
    "not_implemented",
    "return_none_placeholder",
    "return_constant_stub",
    "interface_only_class",
}


def _findings(tmp_path: Path, source: str) -> list:
    path = tmp_path / "mod.py"
    path.write_text(textwrap.dedent(source), encoding="utf-8")
    result = SlopDetector(read_only=True).analyze_file(str(path))
    return sorted(
        (issue.pattern_id, issue.line)
        for issue in result.pattern_issues
        if issue.pattern_id in PLACEHOLDER_IDS
    )


def test_methods_of_declared_interfaces_are_contracts(tmp_path):
    source = """
        import abc
        from abc import ABC, ABCMeta
        from typing import Generic, Protocol, TypeVar

        T = TypeVar("T")

        class Reader(ABC):
            def read(self):
                raise NotImplementedError

        class Sink(Protocol):
            def write(self, data):
                pass

        class Typed(Protocol[T]):
            def get(self) -> T:
                ...

        class Meta(metaclass=ABCMeta):
            def close(self):
                return None

        class Qualified(abc.ABC):
            def supports_seek(self):
                return False
        """
    assert _findings(tmp_path, source) == []


def test_base_method_overridden_in_the_module_is_a_contract(tmp_path):
    source = """
        class Generator:
            def generate(self):
                raise NotImplementedError

            def name(self):
                return "base"

        class CdaGenerator(Generator):
            def generate(self):
                return build()

            def name(self):
                return compute_name()

        class Unfinished:
            def generate(self):
                raise NotImplementedError

            def total(self):
                return compute_total()
        """
    # Unfinished (not subclassed): reported as before.
    assert _findings(tmp_path, source) == [("interface_only_class", 16), ("not_implemented", 17)]


def test_constant_hook_override_is_not_a_stub_but_an_empty_override_is(tmp_path):
    source = """
        class Channel:
            def can_handle(self, url):
                return url.startswith(self.prefix)

            def setup(self):
                self.ready = True

        class Web(Channel):
            def can_handle(self, url):
                return True

            def setup(self):
                pass

        class Plain:
            def enabled(self):
                return False

            def other(self):
                return compute()
        """
    # Web: the constant hook is an implementation, the empty override is not.
    assert _findings(tmp_path, source) == [
        ("interface_only_class", 9),
        ("interface_only_class", 16),
        ("pass_placeholder", 13),
        ("return_constant_stub", 17),
    ]


def test_constant_accessors_are_declared(tmp_path):
    source = """
        class Loss:
            @property
            def citation(self):
                return "@misc{li2024}"

            @classmethod
            def default_scale(cls):
                return 20.0

            @staticmethod
            def name():
                return "loss"

            def forward(self, x):
                return x * 2
        """
    assert _findings(tmp_path, source) == []


def test_decorator_implemented_ellipsis_is_not_a_placeholder(tmp_path):
    source = """
        def peft_wrapper(fn):
            return fn

        class Model:
            @peft_wrapper
            def add_adapter(self, config):
                ...

            def todo(self):
                ...
        """
    assert _findings(tmp_path, source) == [
        ("ellipsis_placeholder", 10),
        ("interface_only_class", 5),
    ]


def test_interface_only_class_respects_declared_and_subclassed_interfaces(tmp_path):
    source = """
        from abc import ABC

        class Port(ABC):
            def send(self):
                pass

            def recv(self):
                pass

        class Base:
            def a(self):
                pass

            def b(self):
                pass

        class Impl(Base):
            # Overrides only `a`: Base is still a base class (its `b` is a
            # default hook), so Base is not reported as interface-only.
            def a(self):
                return 1

        class Settings:
            @property
            def mode(self):
                return "fast"

            def apply(self, value):
                return value + 1

        class Empty:
            def a(self):
                pass

            def b(self):
                pass
        """
    found = _findings(tmp_path, source)
    assert [f for f in found if f[0] == "interface_only_class"] == [("interface_only_class", 32)]


def test_concrete_subclass_of_an_abc_is_still_checked(tmp_path):
    source = """
        from abc import ABC, abstractmethod

        class Base(ABC):
            @abstractmethod
            def run(self):
                pass

        class Impl(Base):
            def run(self):
                raise NotImplementedError
        """
    assert _findings(tmp_path, source) == [("interface_only_class", 9), ("not_implemented", 10)]
