"""Registered empty methods and the static semantic channel.

Registered decorator: `@register(...)` over a `pass` method was declared
because any non-accessor decorator counted as "supplies or registers the
body". A decorator that registers a method does not implement it: an empty
registered method is a placeholder unless its docstring declares the no-op.
A `...` body under a decorator (the decorator supplies the body) and a `pass`
module-level function under a registering decorator (a `click.group`) stay
declared.

Semantic channel: facts a single-function rule cannot see, read from the
module's closed call graph (functions and methods defined in the module).
Reported separately (`result.semantic_findings`); the deficit score does not
change. A call the module does not define is an open edge, and an open edge
makes the channel abstain, never report.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from slop_detector.core import SlopDetector


def _analyze(tmp_path: Path, source: str):
    path = tmp_path / "mod.py"
    path.write_text(textwrap.dedent(source), encoding="utf-8")
    return SlopDetector(read_only=True).analyze_file(str(path))


def _placeholders(result) -> list:
    return sorted(
        (i.line, i.pattern_id)
        for i in result.pattern_issues
        if i.pattern_id in {"pass_placeholder", "empty_except", "return_none_placeholder"}
    )


def _semantic(result) -> list:
    return sorted((f.function, f.kind, tuple(f.inputs)) for f in result.semantic_findings)


# --- registered decorator boundary -------------------------------------------


def test_an_empty_registered_method_is_a_placeholder(tmp_path):
    """A worker method registered for dispatch, body `pass`."""
    result = _analyze(
        tmp_path,
        """
        from dispatch import register, Dispatch

        class CriticWorker:
            @register(dispatch_mode=Dispatch.ONE_TO_ALL)
            def load_checkpoint(self, path):
                pass
        """,
    )
    assert [line for line, _ in _placeholders(result)] == [6]


def test_a_renamed_decorator_does_not_hide_an_empty_method(tmp_path):
    result = _analyze(
        tmp_path,
        """
        from tools import traced

        class Store:
            @traced
            def flush(self):
                pass
        """,
    )
    assert [line for line, _ in _placeholders(result)] == [6]


def test_a_declared_empty_registered_method_is_not_a_placeholder(tmp_path):
    result = _analyze(
        tmp_path,
        """
        from dispatch import register

        class Worker:
            @register()
            def warmup(self):
                \"\"\"No-op: this worker needs no warm-up.\"\"\"
                pass
        """,
    )
    assert _placeholders(result) == []


def test_a_comment_saying_the_empty_body_is_meant_declares_it(tmp_path):
    result = _analyze(
        tmp_path,
        """
        from flow import handler

        class EndExecutor:
            @handler
            async def handle(self, trigger, ctx):
                # Don't send a continuation - the workflow ends here
                pass
        """,
    )
    assert _placeholders(result) == []


def test_a_comment_naming_the_missing_work_does_not_declare_it(tmp_path):
    result = _analyze(
        tmp_path,
        """
        from dispatch import register

        class Worker:
            @register()
            def load_checkpoint(self, path):
                # load the checkpoint from path
                pass

            @register()
            def save_checkpoint(self, path):
                # TODO: nothing saved yet
                pass
        """,
    )
    assert [line for line, _ in _placeholders(result)] == [6, 11]


def test_a_comment_saying_the_body_is_unfinished_does_not_declare_it(tmp_path):
    result = _analyze(
        tmp_path,
        """
        from dispatch import register

        class Worker:
            @register()
            def load(self):
                # not ready yet
                pass

            @register()
            def save(self):
                # not implemented
                pass

            @register()
            def sync(self):
                # currently unavailable on this backend
                pass
        """,
    )
    assert [line for line, _ in _placeholders(result)] == [6, 11, 16]


def test_contract_and_signature_decorators_stay_declared(tmp_path):
    result = _analyze(
        tmp_path,
        """
        from abc import ABC, abstractmethod
        from typing import overload
        from rpc import remote

        class Base(ABC):
            @abstractmethod
            def run(self):
                pass

        class Client:
            @remote
            def call(self, x): ...

        @overload
        def parse(x: int) -> int: ...
        """,
    )
    assert _placeholders(result) == []


def test_an_empty_click_group_function_is_not_a_placeholder(tmp_path):
    result = _analyze(
        tmp_path,
        """
        import click

        @click.group()
        def cli():
            pass
        """,
    )
    assert _placeholders(result) == []


# --- semantic channel: input never reaches a result or an effect -------------


def test_an_input_dropped_by_a_module_helper_is_reported(tmp_path):
    """`save(data)` reads `data` (it passes it on), and the helper drops it:
    the single-function rule sees a use, the call graph sees none."""
    result = _analyze(
        tmp_path,
        """
        class Repo:
            def save(self, record):
                return self._write(record)

            def _write(self, payload):
                return True
        """,
    )
    assert ("Repo.save", "input_never_used", ("record",)) in _semantic(result)


def test_an_input_reaching_an_external_call_is_not_reported(tmp_path):
    result = _analyze(
        tmp_path,
        """
        import json

        class Repo:
            def save(self, record):
                return self._write(record)

            def _write(self, payload):
                return json.dumps(payload)
        """,
    )
    assert _semantic(result) == []


def test_an_input_passed_to_an_overridden_hook_abstains(tmp_path):
    """`self.decode(x)` dispatches on the instance: a subclass implements it."""
    result = _analyze(
        tmp_path,
        """
        class Previewer:
            def preview(self, image):
                return ("JPEG", self.decode(image))

            def decode(self, latent):
                pass

        class FastPreviewer(Previewer):
            def decode(self, latent):
                return latent[:1]
        """,
    )
    assert _semantic(result) == []


def test_an_input_passed_to_an_unresolved_call_abstains(tmp_path):
    result = _analyze(
        tmp_path,
        """
        def save(store, record):
            return store.put(record)
        """,
    )
    assert _semantic(result) == []


# --- semantic channel: success reported with no effect -----------------------


def test_success_after_only_empty_module_calls_is_reported(tmp_path):
    """`sync()` returns True and everything it calls is defined in the module
    and does nothing: the closed graph has no effect."""
    result = _analyze(
        tmp_path,
        """
        import logging
        log = logging.getLogger(__name__)

        class Syncer:
            def sync(self, items):
                self._prepare(items)
                log.info("synced")
                return True

            def _prepare(self, items):
                return None
        """,
    )
    kinds = {kind for function, kind, _ in _semantic(result) if function == "Syncer.sync"}
    assert "success_without_effect" in kinds


def test_success_returned_from_an_empty_helper_is_reported(tmp_path):
    result = _analyze(
        tmp_path,
        """
        class Repo:
            def save(self, record):
                return self._write(record)

            def _write(self, payload):
                return True
        """,
    )
    assert ("Repo.save", "success_without_effect", ()) in _semantic(result)


def test_a_helper_answer_that_is_computed_is_not_success(tmp_path):
    result = _analyze(
        tmp_path,
        """
        class Repo:
            def save(self, record):
                return self._valid(record)

            def _valid(self, payload):
                return payload is not None
        """,
    )
    assert _semantic(result) == []


def test_success_after_a_real_effect_is_not_reported(tmp_path):
    result = _analyze(
        tmp_path,
        """
        class Syncer:
            def sync(self, items, sink):
                for item in items:
                    sink.append(item)
                return True
        """,
    )
    assert _semantic(result) == []


def test_a_pure_computed_result_is_not_success_without_effect(tmp_path):
    result = _analyze(
        tmp_path,
        """
        def is_even(n):
            return n % 2 == 0
        """,
    )
    assert _semantic(result) == []


def test_a_never_read_input_is_left_to_ignored_parameter(tmp_path):
    """The request is never read: ignored_parameter reports it, and the channel
    does not repeat a finding one function shows."""
    result = _analyze(
        tmp_path,
        """
        def send_mail_to_user(mailer, request):
            mailer.send([], "simple plain text")
            return "mail sent"
        """,
    )
    assert [i.pattern_id for i in result.pattern_issues if "'request'" in i.message] == [
        "ignored_parameter"
    ]
    assert _semantic(result) == []


# --- the channel does not change the score -----------------------------------


def test_semantic_findings_do_not_change_the_deficit_score(tmp_path, monkeypatch):
    source = """
    class Repo:
        def save(self, record):
            return self._write(record)

        def _write(self, payload):
            return True
    """
    with_channel = _analyze(tmp_path, source)
    assert with_channel.semantic_findings
    import slop_detector.semantic as semantic

    monkeypatch.setattr(semantic, "semantic_analysis", lambda tree: ([], {}))
    without_channel = _analyze(tmp_path, source)
    assert without_channel.deficit_score == with_channel.deficit_score
    assert without_channel.status == with_channel.status
