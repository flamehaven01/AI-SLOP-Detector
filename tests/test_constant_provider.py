"""A constant that is the function's answer is not a stub.

A function that takes no input and returns text (a prompt, a message, a
template: several words or several lines) provides that text. A docstring
that says the answer is fixed ("Always returns 'hubspot'") declares it. A
function that takes input and answers with fixed text ignores the input, and
a short token (`"ok"`, `"SUCCESS"`) or a number stays a stub. Text that
reports success ("uploaded successfully", "saved", "sent") claims work was
done, so neither its length nor a docstring declares it.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from slop_detector.core import SlopDetector

PID = "return_constant_stub"


def _found(tmp_path: Path, source: str) -> list:
    path = tmp_path / "mod.py"
    path.write_text(textwrap.dedent(source), encoding="utf-8")
    result = SlopDetector(read_only=True).analyze_file(str(path))
    return sorted(i.line for i in result.pattern_issues if i.pattern_id == PID)


def test_text_without_input_is_content(tmp_path):
    source = '''
    class Prompts:
        def developer_prompt(self):
            return "You are a senior developer. Review the design below."

    def usage_message():
        return """Usage: render <file>
    Renders the file to video."""
    '''
    assert _found(tmp_path, source) == []


def test_fixed_text_for_an_input_is_a_stub(tmp_path):
    source = """
    def summarize(text):
        return "This is a summary of the text."
    """
    assert _found(tmp_path, source) == [2]


def test_a_short_token_or_a_number_without_input_is_a_stub(tmp_path):
    source = """
    def status():
        return "ok"

    def fraud_score():
        return 0.0
    """
    assert _found(tmp_path, source) == [2, 5]


def test_a_docstring_declaring_the_fixed_answer_declares_it(tmp_path):
    source = '''
    def parse_source(raw):
        """Always returns 'hubspot': it is the only supported source."""
        return "hubspot"
    '''
    assert _found(tmp_path, source) == []


def test_a_docstring_that_does_not_declare_it_keeps_the_finding(tmp_path):
    source = '''
    def parse_source(raw):
        """Returns the parsed source name."""
        return "hubspot"
    '''
    assert _found(tmp_path, source) == [2]


def test_success_text_without_input_is_a_stub(tmp_path):
    source = """
    def upload_backup():
        return "Your backup has been uploaded successfully."

    def sync_report():
        return \"\"\"Sync complete.
    All records were saved.\"\"\"
    """
    assert _found(tmp_path, source) == [2, 5]


def test_a_docstring_does_not_declare_a_success_claim(tmp_path):
    source = '''
    def upload_backup():
        """Always returns the confirmation text."""
        return "Backup uploaded successfully."
    '''
    assert _found(tmp_path, source) == [2]


def test_a_docstring_still_declares_a_fixed_boolean(tmp_path):
    source = '''
    class VectorAdapter:
        def has_collection(self, name):
            """Vectors live on nodes, so this always returns True."""
            return True
    '''
    assert _found(tmp_path, source) == []


def test_canned_text_for_a_state_the_docstring_looks_up_is_a_stub(tmp_path):
    """The docstring says the function reads current state; fixed text is not
    that state, whatever its length."""
    source = '''
    def get_portfolio_balance():
        """Get current portfolio balance and available funds."""
        return "Portfolio: $50,000 invested, $10,000 cash available."

    def check_staging_status():
        """Check the current status of the staging environment."""
        return "Staging environment: Healthy, Version 2.3.0 deployed"
    '''
    assert _found(tmp_path, source) == [2, 6]


def test_a_fixture_named_after_a_query_is_still_content(tmp_path):
    source = '''
    def query_context_uuid():
        """Query context containing a UUID (for retrieval tests)."""
        return "Find the record with UUID 550e8400-e29b-41d4-a716-446655440000"
    '''
    assert _found(tmp_path, source) == []
