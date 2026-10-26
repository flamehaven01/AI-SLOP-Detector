"""A catch-all handler that returns what the success path returns hides the failure.

When `except Exception:` answers with the same result as the `try` body's
final return (`return len(records)` on both paths in `export_csv`, the same
"up" status in `PartnerClient.health`), the caller cannot tell a failure from
a success. `failure_as_success` reports a handler that catches everything
(bare, `Exception`, `BaseException`) and, after nothing but logging, returns a
value equal to the success path's: the same constant, the same expression over
names the `try` body does not reassign, or a dict with the same success status.

Not reported (external replay, 2026-10-23: 151 findings of a first version,
mostly documented fail-open / fail-closed decisions): `except Exception:
return True` after a `try` that returns something else, since a static reader
cannot tell "report success" from a deliberate safe default; failure values
(`False`, `None`, empty, `{"success": False, ...}`); values the `try` body
returns on a failure branch; narrow exceptions with a fallback; re-raise.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from slop_detector.core import SlopDetector

PID = "failure_as_success"


def _found(tmp_path: Path, source: str) -> list:
    path = tmp_path / "mod.py"
    path.write_text(textwrap.dedent(source), encoding="utf-8")
    result = SlopDetector(read_only=True).analyze_file(str(path))
    return [(i.line, i.message) for i in result.pattern_issues if i.pattern_id == PID]


def test_same_constant_on_both_paths(tmp_path):
    source = """
    import logging
    logger = logging.getLogger(__name__)

    def save(store, item):
        try:
            store.put(item)
            return True
        except Exception:
            logger.exception("save failed")
            return True
    """
    found = _found(tmp_path, source)
    assert [line for line, _ in found] == [9]
    assert "same result as the success path" in found[0][1]


def test_same_expression_on_both_paths(tmp_path):
    source = """
    def export(records, writer):
        try:
            writer.writerows(records)
            return len(records)
        except Exception:
            return len(records)
    """
    assert [line for line, _ in _found(tmp_path, source)] == [6]


def test_same_success_status_on_both_paths(tmp_path):
    source = """
    def health(client):
        try:
            client.get("/health")
            return {"status": "up", "latency_ms": measure()}
        except Exception:
            return {"status": "up", "latency_ms": 0.0}
    """
    assert [line for line, _ in _found(tmp_path, source)] == [6]


@pytest.mark.parametrize(
    "handler", ["except:", "except BaseException:", "except (OSError, Exception):"]
)
def test_every_catch_all_form(tmp_path, handler):
    source = f"""
    def save(store, item):
        try:
            store.put(item)
            return True
        {handler}
            return True
    """
    assert len(_found(tmp_path, source)) == 1


def test_true_after_a_different_success_result_is_not_reported(tmp_path):
    """Fail-open decisions (`keep the session alive`, `verify TLS`) look like this."""
    source = """
    def charge(gateway, request):
        try:
            return gateway.submit(request)
        except Exception:
            return True
    """
    assert _found(tmp_path, source) == []


def test_a_value_from_a_failure_branch_of_the_try_is_not_reported(tmp_path):
    source = """
    def search(client, query):
        try:
            if not query:
                return {"success": False, "error": "empty"}
            return {"success": True, "results": client.search(query)}
        except Exception as exc:
            return {"success": False, "error": str(exc)}
    """
    assert _found(tmp_path, source) == []


def test_a_name_reassigned_in_the_try_is_not_the_same_result(tmp_path):
    source = """
    def translate(client, text):
        try:
            text = client.translate(text)
            return text
        except Exception:
            return text
    """
    assert _found(tmp_path, source) == []


@pytest.mark.parametrize(
    "handler_body",
    ["return False", "return None", "return {}", 'return {"status": "down"}', "raise", "return 0"],
)
def test_failure_values_and_reraise_are_not_reported(tmp_path, handler_body):
    source = f"""
    def health(client):
        try:
            client.get("/health")
            return {{"status": "up"}}
        except Exception:
            {handler_body}
    """
    assert _found(tmp_path, source) == []


def test_a_narrow_exception_with_a_fallback_is_not_reported(tmp_path):
    source = """
    def created(path):
        try:
            path.mkdir()
            return True
        except FileExistsError:
            return True
    """
    assert _found(tmp_path, source) == []


def test_a_handler_doing_work_before_returning_is_not_reported(tmp_path):
    source = """
    def save(store, queue, item):
        try:
            store.put(item)
            return True
        except Exception:
            queue.put(item)
            return True
    """
    assert _found(tmp_path, source) == []


def test_a_default_answer_after_several_returns_is_not_reported(tmp_path):
    """External replay: config reads and lookups end the try with a default and
    answer errors with the same default (hermes-agent approval modes, max_skew)."""
    source = """
    def approval_mode(config):
        try:
            mode = config.read("mode")
            if mode in {"approve", "allow"}:
                return "approve"
            return "deny"
        except Exception:
            return "deny"
    """
    assert _found(tmp_path, source) == []


def test_a_container_filled_in_the_try_is_not_the_same_result(tmp_path):
    source = """
    def runs(client, ids):
        found = []
        found_by_id = {}
        try:
            for i in ids:
                found.append(client.get(i))
                found_by_id[i] = found[-1]
            return found
        except Exception:
            return found
    """
    assert _found(tmp_path, source) == []


def test_a_catch_all_beside_a_handler_that_reports_failure_is_a_decision(tmp_path):
    """External replay: `except AuthError: return False` then `except Exception:
    return True` classifies transient errors as still valid (documented)."""
    source = """
    def token_valid(token):
        try:
            validate(token)
            return True
        except AuthError:
            return False
        except Exception:
            return True
    """
    assert _found(tmp_path, source) == []


def test_the_saved_path_returned_when_saving_failed_is_reported(tmp_path):
    """External replay true positive: a plotting script returns the save path
    even when drawing or saving raised."""
    source = """
    def visualize(graph, save_path=None):
        try:
            draw(graph)
            save(save_path)
            return save_path or "pathway.png"
        except Exception as e:
            print(f"Error visualizing pathway: {e}")
            return save_path or "pathway.png"
    """
    assert [line for line, _ in _found(tmp_path, source)] == [7]


def test_a_single_early_return_inside_the_try_is_not_the_success_path(tmp_path):
    """External replay: the try's one return is an early failure exit; success
    is returned after the try."""
    source = """
    def usage(client):
        try:
            data = client.get()
            if not data:
                return Usage(available=False)
        except Exception:
            return Usage(available=False)
        return Usage(available=True, data=data)
    """
    assert _found(tmp_path, source) == []


@pytest.mark.parametrize(
    "value",
    ["(False, 'client_closed')", "({}, False)", "Usage(available=False)", "Result(ok=False)"],
)
def test_failure_shaped_results_are_not_reported(tmp_path, value):
    source = f"""
    def probe(client):
        try:
            client.ping()
            return {value}
        except Exception:
            return {value}
    """
    assert _found(tmp_path, source) == []


def test_an_early_success_return_inside_the_try_is_not_the_success_path(tmp_path):
    """The try's one return is an early exit; the function's result comes after it."""
    source = """
    def status(job):
        try:
            if job.ready():
                return "ok"
            job.refresh()
        except Exception:
            return "ok"
        return "pending"
    """
    assert _found(tmp_path, source) == []
