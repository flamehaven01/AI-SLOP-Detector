"""P0 placeholder semantics: declared defaults are not stubs, logged stubs are.

From the hold-out v2 development data (12 false alarms, 2 missed stubs):

- a null object or a base of defaults says so in its class name
  (`NullRenderer`, `BaseFeature`); its one-line bodies are the defaults, and a
  `return` in a subclass of such a named base is a hook answer;
- an empty `pass` / `return None` body under a registering decorator
  (`@click.group()`) claims nothing;
- `raise NotImplementedError` in a method of a class with a base the module
  does not define, or of a class with two or more such methods, declares the
  operation unsupported or the interface;
- print or log lines in front of `raise NotImplementedError` do not make it an
  implementation (`print("authorize", args); raise NotImplementedError()`).

Kept: a constant success answer under a decorator, a lone NotImplementedError
in a concrete class, an override of a module base that is `pass`.
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


def test_named_null_objects_and_bases_hold_defaults(tmp_path):
    source = """
        from models import AirBaseModel

        class NullRenderer:
            def draw(self, frame) -> None:
                return

            def cleanup(self) -> None:
                return None

        class NoOpSink:
            def write(self, data):
                pass

        class BaseFeature:
            def default_config(self) -> dict:
                \"\"\"Default configuration (optional).\"\"\"
                return {}

        class Qwen(AirBaseModel):
            def use_better_transformer(self):
                return False
    """
    assert _findings(tmp_path, source) == []


def test_empty_body_under_registering_decorator(tmp_path):
    source = """
        import click

        @click.group()
        def cli() -> None:
            \"\"\"Tool.\"\"\"
            return

        @click.group()
        def tools():
            pass
    """
    assert _findings(tmp_path, source) == []


def test_not_implemented_declared_by_interface(tmp_path):
    source = """
        from handlers import BaseFileHandler

        class ImageHandler(BaseFileHandler):
            def dump_to_str(self, obj, **kwargs):
                raise NotImplementedError

        class Agent:
            def decide(self, state):
                raise NotImplementedError

            def fallback(self, reason):
                \"\"\"Subclasses return the worst case.\"\"\"
                raise NotImplementedError
    """
    assert _findings(tmp_path, source) == []


def test_logged_not_implemented_is_reported(tmp_path):
    source = """
        def authorize(args):
            \"\"\"Run the equivalent of tool authorize.\"\"\"
            print("authorize", args)
            raise NotImplementedError()

        def password(args):
            print("password", args)
            raise NotImplementedError
    """
    assert _findings(tmp_path, source) == [("not_implemented", 2), ("not_implemented", 7)]


def test_named_bases_do_not_excuse_logged_or_declared_stubs(tmp_path):
    """Replay drops that were real: a logged success report, a logged empty
    answer the docstring calls a placeholder, a NotImplementedError the
    docstring calls a placeholder."""
    source = """
        import logging
        from platforms import BasePlatformAdapter, BaseGenerator, BaseRequestConstructor

        log = logging.getLogger(__name__)

        class WebhookAdapter(BasePlatformAdapter):
            async def send(self, chat_id, content):
                log.info("response for %s", chat_id)
                return SendResult(success=True)

        class FHIRGenerator(BaseGenerator):
            def from_hl7v2(self, entries):
                \"\"\"Convert entries. This is a placeholder implementation.\"\"\"
                log.warning("placeholder implementation")
                return []

        class CdaConstructor(BaseRequestConstructor):
            def construct_cda(self):
                \"\"\"Placeholder for CDA construction logic.\"\"\"
                raise NotImplementedError

        class Sink(BasePlatformAdapter):
            def flush(self):
                log.info("flushed")
                return True

            def deliver(self, item):
                return SendResult(success=True)
    """
    assert _findings(tmp_path, source) == [
        ("not_implemented", 19),
        ("return_constant_stub", 8),
        ("return_constant_stub", 13),
        ("return_constant_stub", 24),
        ("return_constant_stub", 28),
    ]


def test_kept_stubs_still_reported(tmp_path):
    source = """
        from web import app

        @app.get("/health")
        def health():
            return True

        class Exporter:
            def export_pdf(self, report):
                raise NotImplementedError

        class Store:
            def save(self, item):
                return 1

        class CachedStore(Store):
            def save(self, item):
                pass

        class PaymentService:
            def charge(self, amount):
                return True
    """
    # Store.save is a base contract (CachedStore overrides it): not reported.
    assert _findings(tmp_path, source) == [
        ("not_implemented", 9),
        ("pass_placeholder", 17),
        ("return_constant_stub", 5),
        ("return_constant_stub", 21),
    ]
