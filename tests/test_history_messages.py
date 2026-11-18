"""3.16.2: what a user is told when the pre-v7 copy fails, and when the upgrade runs.

Contract:
- a scan whose history cannot be upgraded (the pre-upgrade copy failed)
  still runs: the same JSON on stdout, the same exit code, one warning line
  on stderr, no history row, the database unchanged; the detail goes to the
  debug log;
- a command that only reads history (--show-history, --history-trends,
  --export-history) says in one line that history could not be opened and
  exits 1, without a traceback; so does any other CLI step that needs history
  (one safety net at the entry point);
- the API records nothing and logs the warning; the analysis is answered;
- without a failure neither line appears;
- the upgrade notice appears once, on the run that upgrades, never on a
  later scan or a read-only report; it names no absolute path.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from slop_detector import history as history_module
from slop_detector.cli import main
from slop_detector.history import (
    HISTORY_NOT_OPENED,
    HISTORY_NOT_RECORDED,
    HistoryTracker,
)
from slop_detector.ml.self_calibrator import SelfCalibrator
from tests.test_history_languages import OLD_TABLE

SLOP = "def f(x, acc=[]):\n    try:\n        return int(x)\n    except:\n        pass\n"
NOTICE = "Notice: History database upgraded to v7."


@pytest.fixture
def setup(tmp_path, monkeypatch):
    """An old (3.16.1) history database and a project, both under tmp_path."""
    db = tmp_path / "home" / ".slop-detector" / "history.db"
    db.parent.mkdir(parents=True)
    with closing(sqlite3.connect(db)) as conn, conn:
        conn.executescript(OLD_TABLE)
        conn.execute(
            "INSERT INTO history (timestamp, file_path, file_hash, deficit_score)"
            " VALUES ('2026-11-01T00:00:00', '/p/a.py', 'h', 10.0)"
        )
    monkeypatch.setattr(HistoryTracker, "DEFAULT_DB", db)
    monkeypatch.setattr(SelfCalibrator, "DEFAULT_DB", db)
    project = tmp_path / "proj"
    project.mkdir()
    (project / "mod.py").write_text(SLOP, encoding="utf-8")
    return db, project


@pytest.fixture
def failing_copy(monkeypatch):
    def full_disk(source, target):
        raise sqlite3.OperationalError("database or disk is full")

    monkeypatch.setattr(history_module, "_backup_copy", full_disk)


def _rows(db: Path):
    with closing(sqlite3.connect(db)) as conn:
        return conn.execute("SELECT * FROM history ORDER BY id").fetchall()


def _lines(text: str, needle: str):
    return [line for line in text.splitlines() if needle in line]


def test_a_scan_whose_history_cannot_upgrade_still_runs_and_says_so(
    setup, failing_copy, capsys, caplog
):
    db, project = setup
    expected_code = main([str(project), "--json", "--no-history"])
    expected_out = capsys.readouterr().out
    before = _rows(db)

    with caplog.at_level(logging.DEBUG):
        code = main([str(project), "--json"])
    captured = capsys.readouterr()

    assert code == expected_code
    assert captured.out == expected_out
    json.loads(captured.out)
    assert _lines(captured.err, HISTORY_NOT_RECORDED) == [HISTORY_NOT_RECORDED]
    assert "Traceback" not in captured.err
    assert "disk is full" not in captured.err  # the detail is in the debug log
    assert "disk is full" in caplog.text
    assert _rows(db) == before


@pytest.mark.parametrize(
    "command",
    [["--show-history"], ["--history-trends"], ["--export-history", "out.jsonl"]],
)
def test_a_history_command_says_history_could_not_be_opened(
    setup, failing_copy, capsys, monkeypatch, command
):
    db, project = setup
    monkeypatch.chdir(project)
    before = _rows(db)

    code = main([str(project / "mod.py"), *command])
    err = capsys.readouterr().err

    assert code == 1
    assert _lines(err, HISTORY_NOT_OPENED) == [HISTORY_NOT_OPENED]
    assert "Traceback" not in err
    assert not (project / "out.jsonl").exists()
    assert _rows(db) == before


def test_any_other_step_that_needs_history_ends_with_one_line(setup, capsys, monkeypatch):
    """The entry point's safety net: a step not handled above (an optional
    output that reads history) still gives one line and exit 1."""
    from slop_detector import cli

    def needs_history(argv=None):
        raise history_module.HistoryBackupError("history upgrade stopped: disk is full")

    monkeypatch.setattr(cli, "_main", needs_history)
    code = main(["anything"])
    err = capsys.readouterr().err

    assert code == 1
    assert _lines(err, HISTORY_NOT_OPENED) == [HISTORY_NOT_OPENED]
    assert "Traceback" not in err and "disk is full" not in err


def test_the_api_answers_and_records_nothing(setup, failing_copy, caplog):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from slop_detector.api.server import create_app

    db, project = setup
    before = _rows(db)
    client = TestClient(create_app())
    body = {"file_path": str(project / "mod.py"), "save_history": True}

    with caplog.at_level(logging.WARNING):
        response = client.post("/analyze/file", json=body)

    assert response.status_code == 200
    assert HISTORY_NOT_RECORDED in caplog.text
    assert _rows(db) == before


def test_without_a_failure_neither_line_appears_and_the_notice_shows_once(
    setup, capsys, caplog, tmp_path
):
    db, project = setup
    notices = []
    for args in ([str(project), "--json"], [str(project), "--json"],
                 ["--self-calibrate", "--json", str(project)]):
        caplog.clear()
        with caplog.at_level(logging.WARNING):
            main(args)
        captured = capsys.readouterr()
        json.loads(captured.out)  # stdout stays one JSON document
        assert HISTORY_NOT_RECORDED not in captured.err + caplog.text
        assert HISTORY_NOT_OPENED not in captured.err + caplog.text
        notices.append([r.getMessage() for r in caplog.records if NOTICE in r.getMessage()])
        assert str(tmp_path) not in caplog.text

    assert [len(n) for n in notices] == [1, 0, 0]  # the upgrade run only
