"""The audit (review) screen says what its verdict judged.

The verdict comes from the CI gate, which judges each file; overall_status is
the score band of the whole project. A project can be "clean" on average with
two files over a warning threshold, so WARN next to "clean" is correct, but
the screen must say the verdict is per file and how many files it counted.
JSON keeps its keys and values.
"""

from __future__ import annotations

import copy

from slop_detector.operations import render_payload_markdown, render_payload_text


def _audit_payload(verdict: str, failed: int, warned: int, total: int = 129) -> dict:
    return {
        "command": "audit",
        "verdict": verdict,
        "summary": {"total_files": total, "overall_status": "clean"},
        "gate": {
            "verdict": verdict,
            "failed_files": [f"f{i}.py" for i in range(failed)],
            "warned_files": [f"w{i}.py" for i in range(warned)],
            "quarantined_files": [],
        },
    }


def test_the_text_verdict_names_its_per_file_basis():
    text = render_payload_text(_audit_payload("warn", failed=0, warned=2))
    assert "Verdict: WARN - per file: 0 failed, 2 warned of 129 files" in text.splitlines()
    assert "overall_status: clean" in text.splitlines()


def test_the_markdown_verdict_names_its_per_file_basis():
    md = render_payload_markdown(_audit_payload("fail", failed=1, warned=3, total=10))
    assert "**Verdict**: `FAIL` - per file: 1 failed, 3 warned of 10 files" in md.splitlines()


def test_a_payload_without_a_gate_keeps_the_plain_verdict():
    payload = {"command": "dead-code", "verdict": "pass", "summary": {"issue_count": 0}}
    assert "Verdict: PASS" in render_payload_text(payload).splitlines()
    assert "**Verdict**: `PASS`" in render_payload_markdown(payload).splitlines()


def test_rendering_does_not_change_the_payload():
    payload = _audit_payload("warn", failed=0, warned=2)
    before = copy.deepcopy(payload)
    render_payload_text(payload)
    render_payload_markdown(payload)
    assert payload == before
