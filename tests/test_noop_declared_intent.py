"""An empty body whose own summary sentence declares it a no-op is not a stub.

Contract (fixed before implementation):

- body: after the leading docstring, exactly one `pass`, `return` or
  `return None` statement;
- declaration: the docstring's first sentence says no-op / does nothing / do
  nothing / nothing to do / intentionally empty, and that sentence has no
  not / never / n't / cannot / must / should / shall ("has no typing indicator"
  and "required by the SDK" explain a no-op and are allowed);
- nothing in the docstring says placeholder / stub / todo or limits it in time
  (for now, currently, yet, until, temporary, future, later);
- structural evidence besides the words: a method of a class with a base the
  module does not define, an override of a module base, a subclass of a named
  base, or a function registered by value.

Anything else keeps its placeholder finding.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from slop_detector.core import SlopDetector

PLACEHOLDER_IDS = {"pass_placeholder", "return_none_placeholder", "return_constant_stub"}


def _findings(tmp_path: Path, source: str) -> list:
    path = tmp_path / "mod.py"
    path.write_text(textwrap.dedent(source), encoding="utf-8")
    result = SlopDetector(read_only=True).analyze_file(str(path))
    return sorted(
        (issue.pattern_id, issue.line)
        for issue in result.pattern_issues
        if issue.pattern_id in PLACEHOLDER_IDS
    )


def test_declared_noops_with_structural_evidence_are_protected(tmp_path):
    source = """
        import sdk
        from platforms import PlatformAdapter, BaseSink

        class ChatAdapter(PlatformAdapter):
            async def send_typing(self, chat_id, metadata=None) -> None:
                \"\"\"This chat has no typing indicator API - no-op.\"\"\"
                pass

        class Handler(sdk.ChatbotHandler if sdk else object):
            def pre_start(self) -> None:
                \"\"\"No-op pre-start hook required by the SDK.

                The SDK calls pre_start() on every handler before connecting.
                \"\"\"
                return None

        class Sink(BaseSink):
            def flush(self):
                \"\"\"Does nothing: writes are unbuffered.\"\"\"
                return

        def on_idle(event):
            \"\"\"Nothing to do when idle.\"\"\"
            pass

        CALLBACKS = [on_idle]
    """
    assert _findings(tmp_path, source) == []


def test_undeclared_contradicted_or_unanchored_noops_are_reported(tmp_path):
    source = """
        from platforms import PlatformAdapter, Bus, SDKPlugin

        def send_notification(recipient):
            \"\"\"Send a notification to the recipient.\"\"\"
            return None

        def process_payment(order):
            \"\"\"No-op.\"\"\"
            pass

        class Gateway(Bus):
            def register_builtin_hooks(self):
                \"\"\"Register built-in hooks. Currently empty - nothing to do.\"\"\"
                return None

            def stop(self):
                \"\"\"No-op for now.\"\"\"
                pass

            def notify(self, recipient):
                \"\"\"This is not a no-op; it must notify the recipient.\"\"\"
                return None

            def hook(self):
                \"\"\"No-op is not allowed; this hook must register listeners.\"\"\"
                pass

            def alert(self):
                \"\"\"Send an alert. Intentionally does nothing.\"\"\"
                return None

            def draft(self):
                \"\"\"No-op placeholder.\"\"\"
                pass

            def charge(self, amount):
                \"\"\"No-op.\"\"\"
                return True

            def pause(self):
                \"\"\"No-op.\"\"\"
                "kept for the scheduler"
                pass

        class Plugin(SDKPlugin):
            def after_shutdown(self) -> None:
                \"\"\"Optional lifecycle hook. Intentionally does nothing by default.\"\"\"
                return None
    """
    assert _findings(tmp_path, source) == [
        ("pass_placeholder", 8),
        ("pass_placeholder", 17),
        ("pass_placeholder", 25),
        ("pass_placeholder", 33),
        ("pass_placeholder", 41),
        ("return_constant_stub", 37),
        ("return_none_placeholder", 4),
        ("return_none_placeholder", 13),
        ("return_none_placeholder", 21),
        ("return_none_placeholder", 29),
        ("return_none_placeholder", 47),
    ]
