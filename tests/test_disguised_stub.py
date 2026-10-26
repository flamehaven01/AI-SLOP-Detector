"""A stub stays a stub when it logs before returning.

`return_constant_stub` read a body of exactly one `return <constant>`, so one
logging line in front of the constant hid the stub (recall corpus:
`FraudScreen.score`, `PaymentGateway.submit`). A body that only logs, prints
or passes before its final `return` is judged by that return.
`return_input_stub` reports the same shape when the return hands back an
argument unchanged (`normalize`, `calibrate`).

Not stubs: any other statement (an assignment, a call that is not logging,
an `if` or a loop), a log call whose arguments call something other than a
pure builtin, a bare `return x` with nothing in front of it, and every
declared intent `return_constant_stub` already honours (abstract, contract,
override, accessor, dunder).
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from slop_detector.core import SlopDetector

STUB_IDS = {"return_constant_stub", "return_input_stub"}


def _stubs(tmp_path: Path, source: str) -> list:
    path = tmp_path / "mod.py"
    path.write_text(textwrap.dedent(source), encoding="utf-8")
    result = SlopDetector(read_only=True).analyze_file(str(path))
    return sorted(
        (issue.pattern_id, issue.line, issue.message)
        for issue in result.pattern_issues
        if issue.pattern_id in STUB_IDS
    )


LOGGING_HEADER = """
import logging

logger = logging.getLogger(__name__)
"""


@pytest.mark.parametrize(
    "body, value",
    [
        ('logger.debug("screening %s", charge.customer_id)\n    return 0.0', "0.0"),
        ('logger.info("submitting %s", charge)\n    return True', "True"),
        ('print("charging")\n    return "ok"', "'ok'"),
        ('logging.warning("no rates")\n    logger.info("fallback")\n    return {}', "{}"),
        ('logger.info("n=%d", len(charge))\n    return False', "False"),
    ],
)
def test_logging_before_a_constant_is_still_a_stub(tmp_path, body, value):
    source = LOGGING_HEADER + f'\n\ndef score(charge):\n    """Score the charge."""\n    {body}\n'
    found = _stubs(tmp_path, source)
    assert [(pid, line) for pid, line, _ in found] == [("return_constant_stub", 7)]
    message = found[0][2]
    assert "only logs" in message and value in message


def test_a_method_logging_through_self_logger_is_a_stub(tmp_path):
    source = """
    class FraudScreen:
        def score(self, charge):
            self.logger.debug("screening")
            return 0.0
    """
    assert [pid for pid, _, _ in _stubs(tmp_path, source)] == ["return_constant_stub"]


def test_logging_before_returning_an_argument_is_a_passthrough_stub(tmp_path):
    source = (
        LOGGING_HEADER
        + """

def normalize(records):
    \"\"\"Lower-case emails and convert timestamps to UTC.\"\"\"
    logger.info("normalizing %d records", len(records))
    return records
"""
    )
    found = _stubs(tmp_path, source)
    assert [(pid, line) for pid, line, _ in found] == [("return_input_stub", 7)]
    assert "'records'" in found[0][2] and "unchanged" in found[0][2]


def test_unchanged_constant_stub_message_is_kept(tmp_path):
    found = _stubs(tmp_path, "def score(charge):\n    return 0.0\n")
    assert found == [
        ("return_constant_stub", 1, "Function 'score' returns constant 0.0 - likely stub")
    ]


@pytest.mark.parametrize(
    "body",
    [
        'logger.info("x")\n    return charge * 2',  # computed result
        "self_count = 1\n    return True",  # an assignment is work
        "client.send(charge)\n    return True",  # a call that is not logging
        'if not charge:\n        logger.info("empty")\n    return True',  # control flow
        "for item in charge:\n        logger.info(item)\n    return True",  # a loop
        'logger.info("%s", compute(charge))\n    return True',  # log argument calls code
        'logger.info("x")\n    return None',  # return None has its own pattern
    ],
)
def test_real_work_or_unclear_shapes_are_not_stubs(tmp_path, body):
    source = LOGGING_HEADER + f"\n\ndef score(charge):\n    {body}\n"
    assert _stubs(tmp_path, source) == []


def test_a_bare_passthrough_is_not_a_stub(tmp_path):
    assert _stubs(tmp_path, "def identity(value):\n    return value\n") == []


def test_returning_self_state_is_not_a_passthrough(tmp_path):
    source = (
        LOGGING_HEADER
        + """

class Box:
    def get(self, key):
        logger.debug("get %s", key)
        return self
"""
    )
    assert _stubs(tmp_path, source) == []


@pytest.mark.parametrize(
    "source",
    [
        # abstract method
        """
        import abc
        class Model(abc.ABC):
            @abc.abstractmethod
            def predict(self, x):
                logger.debug("predict")
                return 0.0
        """,
        # override of a module base: a hook answering a question
        """
        class Base:
            def enabled(self):
                return compute()
        class Child(Base):
            def enabled(self):
                logger.debug("child")
                return False
        """,
        # declared accessor
        """
        class Config:
            @property
            def retries(self):
                logger.debug("retries")
                return 3
        """,
        # dunder that legitimately answers with a constant
        """
        class Empty:
            def __len__(self):
                logger.debug("len")
                return 0
        """,
        # passthrough in a contract method a subclass overrides
        """
        class Step:
            def apply(self, records):
                logger.debug("noop")
                return records
        class Upper(Step):
            def apply(self, records):
                return [r.upper() for r in records]
        """,
    ],
)
def test_declared_intent_still_exempts_logged_bodies(tmp_path, source):
    header = "import logging\nlogger = logging.getLogger(__name__)\n"
    assert _stubs(tmp_path, header + textwrap.dedent(source)) == []


@pytest.mark.parametrize(
    "registration",
    [
        "set_callback(auto_deny)",  # passed as an argument
        "HANDLERS = {'deny': auto_deny}",  # mapped in a table
        "def pick(flag):\n    return auto_deny",  # returned as a value
    ],
)
def test_a_logged_callback_registered_by_value_is_not_a_stub(tmp_path, registration):
    """External replay: approval callbacks and dispatch handlers answer with a fixed
    token and their log line is the action (hermes-agent, 5 of 6 new findings)."""
    source = (
        LOGGING_HEADER
        + f"""

def auto_deny(command, description):
    \"\"\"Refuse dangerous commands in subagent threads.\"\"\"
    logger.warning("auto-denied %s", command)
    return "deny"


{registration}
"""
    )
    assert _stubs(tmp_path, source) == []


def test_a_logged_method_registered_through_self_is_not_a_stub(tmp_path):
    source = (
        LOGGING_HEADER
        + """

class Gateway:
    def routes(self):
        return {"start": self._ignore_start}

    def _ignore_start(self, event):
        logger.info("ignoring /start ping")
        return ""
"""
    )
    assert _stubs(tmp_path, source) == []


def test_a_logged_stub_that_is_called_is_still_a_stub(tmp_path):
    source = (
        LOGGING_HEADER
        + """

class Generator:
    def generate(self, entries):
        return self.from_hl7(entries)

    def from_hl7(self, entries):
        logger.warning("HL7v2 conversion is a placeholder")
        return []
"""
    )
    assert [pid for pid, _, _ in _stubs(tmp_path, source)] == ["return_constant_stub"]


def test_a_bare_constant_callback_keeps_its_existing_finding(tmp_path):
    source = "def auto_deny(command):\n    return 'deny'\n\n\nset_callback(auto_deny)\n"
    assert [pid for pid, _, _ in _stubs(tmp_path, source)] == ["return_constant_stub"]


@pytest.mark.parametrize(
    "other",
    [
        "def inspect_reference(verify_token):\n    return verify_token",  # same-name parameter
        "def build():\n    verify_token = make()\n    return verify_token",  # same-name local
        "def loop(items):\n    for verify_token in items:\n        use(verify_token)",  # loop target
    ],
)
def test_a_same_name_in_another_scope_is_not_a_registration(tmp_path, other):
    """Audit S312-01: a name read in another scope is not the module function."""
    source = (
        LOGGING_HEADER
        + f"""

def verify_token(token):
    logger.info("verify %s", token)
    return True


{other}
"""
    )
    assert [pid for pid, _, _ in _stubs(tmp_path, source)] == ["return_constant_stub"]


def test_a_self_data_attribute_with_the_method_name_is_not_a_registration(tmp_path):
    source = (
        LOGGING_HEADER
        + """

class Screen:
    def __init__(self):
        self.score = None

    def report(self):
        return self.score

    def score(self, charge):
        logger.debug("screening")
        return 0.0
"""
    )
    assert [pid for pid, _, _ in _stubs(tmp_path, source)] == ["return_constant_stub"]


def test_a_shadowed_builtin_in_a_log_argument_is_not_pure(tmp_path):
    source = (
        LOGGING_HEADER
        + """
from metrics import record as len


def score(charge):
    logger.info("n=%d", len(charge))
    return 0.0
"""
    )
    assert _stubs(tmp_path, source) == []


@pytest.mark.parametrize("name", ["trace", "log_event", "audit_access", "report_status", "notify"])
def test_a_function_whose_job_is_to_log_is_not_a_stub(tmp_path, name):
    source = (
        LOGGING_HEADER
        + f"""

def {name}(value):
    logger.info("value %s", value)
    return value


def {name}_ok(event):
    logger.info("event %s", event)
    return True
"""
    )
    assert _stubs(tmp_path, source) == []


def test_a_nested_callback_registered_in_its_own_scope_is_not_a_stub(tmp_path):
    """External replay regression: `def deny(...)` then `set_callback(deny)` in one function."""
    source = (
        LOGGING_HEADER
        + """

def install(parser):
    def unavailable(args):
        print("module unavailable")
        return 1

    parser.set_defaults(func=unavailable)
"""
    )
    assert _stubs(tmp_path, source) == []


@pytest.mark.parametrize("returned", ["charge * 2", "charge[0]", "charge.total", "compute(charge)"])
def test_non_name_returns_after_logging_raise_no_pattern_error(tmp_path, returned):
    """Only a bare argument name is a passthrough; anything else is left alone cleanly."""
    path = tmp_path / "mod.py"
    path.write_text(
        LOGGING_HEADER + f"\n\ndef score(charge):\n    logger.info('x')\n    return {returned}\n",
        encoding="utf-8",
    )
    result = SlopDetector(read_only=True).analyze_file(str(path))
    assert result.pattern_errors == []
    assert not [i for i in result.pattern_issues if i.pattern_id in STUB_IDS]
