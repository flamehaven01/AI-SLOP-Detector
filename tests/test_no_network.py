"""The README says a scan makes no network calls. A full project scan and the
report files it writes must finish with every network connection refused, and
none may be attempted.
"""

from __future__ import annotations

import contextlib
import io
import socket
from pathlib import Path

DEMO = Path(__file__).resolve().parents[1] / "examples" / "demo_project"


def _refuse_network(monkeypatch) -> list:
    attempts = []

    def refused(*args, **kwargs):
        attempts.append(args[:2])
        raise OSError("network refused by test_no_network")

    for owner, name in (
        (socket.socket, "connect"),
        (socket.socket, "connect_ex"),
        (socket, "create_connection"),
        (socket, "getaddrinfo"),
    ):
        monkeypatch.setattr(owner, name, refused)
    return attempts


def test_a_project_scan_and_its_reports_make_no_network_call(monkeypatch, tmp_path):
    attempts = _refuse_network(monkeypatch)
    from slop_detector.cli import main

    with contextlib.redirect_stdout(io.StringIO()) as out:
        code = main(["--project", str(DEMO), "--json", "--no-history"])
    assert code == 0 and '"weighted_deficit_score"' in out.getvalue()
    for name in ("report.md", "report.html", "ai-report.md"):
        with contextlib.redirect_stdout(io.StringIO()):
            assert main(["--project", str(DEMO), "-o", str(tmp_path / name), "--no-history"]) == 0
        assert (tmp_path / name).stat().st_size > 0, name
    assert attempts == []


def test_the_refusal_is_real(monkeypatch):
    """The guard itself: a connection attempt under it fails and is counted."""
    attempts = _refuse_network(monkeypatch)
    try:
        socket.create_connection(("example.invalid", 80), timeout=1)
    except OSError:
        pass
    assert len(attempts) == 1
