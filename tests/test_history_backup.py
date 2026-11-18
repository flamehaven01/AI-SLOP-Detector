"""3.16.2: a verified copy of the history database before its one-time v7 rebuild.

A release older than 3.16.2 cannot read every v7 row (a NULL metric breaks
its --show-history and --history-trends). The rebuild therefore first keeps
the database as it was, so a user going back has a recovery path. This is a
recovery path, not compatibility: the old release still fails on a v7 database.

Contract:
- only the run that rebuilds a pre-v7 database makes a copy, next to it:
  `history.pre-v7.db`; a database already on v7 makes none;
- the copy is a consistent SQLite snapshot (the backup API inside a read
  transaction, not a file copy), checked before the rebuild: integrity_check
  ok and the same rows (every column, every id) and schema as the original;
- a copy that fails (an error, a full disk) or does not match stops the
  upgrade: the database is left as it was and no partial copy is left;
- an existing copy is never overwritten: a second one gets its own name;
- the copy gets the original's permission bits;
- restoring it (replacing history.db with it) gives back the old database.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import stat
from contextlib import closing
from pathlib import Path

import pytest

from slop_detector import history as history_module
from slop_detector.history import HistoryBackupError, HistoryTracker
from tests.test_history_languages import METRICS, OLD_TABLE

BACKUP = "history.pre-v7.db"


def _old_database(db: Path) -> None:
    db.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(db)) as conn, conn:  # closed, so the file can be replaced
        conn.executescript(OLD_TABLE)
        for i in range(3):
            conn.execute(
                "INSERT INTO history (timestamp, file_path, file_hash, deficit_score,"
                " ldr_score, inflation_score, ddc_usage_ratio, provenance_state)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (
                    f"2026-11-0{i + 1}T00:00:00",
                    f"/p/m{i}.py",
                    f"h{i}",
                    10.0 * i,
                    0.1 * i,
                    0.2 * i,
                    0.3 * i,
                    "v6",
                ),
            )
        conn.execute("DELETE FROM history WHERE id = 3")


def _state(db: Path):
    """Rows, schema and the metric columns' NOT NULL flags of a database."""
    with closing(sqlite3.connect(db)) as conn:  # closed: Windows cannot replace an open file
        rows = conn.execute("SELECT * FROM history ORDER BY id").fetchall()
        schema = conn.execute("SELECT sql FROM sqlite_master WHERE name = 'history'").fetchone()[0]
        notnull = [r[3] for r in conn.execute("PRAGMA table_info(history)") if r[1] in METRICS]
        sequence = conn.execute("SELECT seq FROM sqlite_sequence WHERE name = 'history'").fetchone()
    return {"rows": rows, "schema": schema, "notnull": notnull, "sequence": sequence}


def _copies(directory: Path):
    return sorted(p.name for p in directory.glob("history.pre-v7*.db"))


def test_the_rebuild_first_keeps_a_verified_copy_of_the_old_database(tmp_path, caplog):
    db = tmp_path / "history.db"
    _old_database(db)
    before = _state(db)

    with caplog.at_level(logging.DEBUG, logger="slop_detector.history"):
        HistoryTracker(db_path=db)

    copy = tmp_path / BACKUP
    assert _copies(tmp_path) == [BACKUP]
    assert _state(copy) == before  # the 3.16.1 table: NOT NULL metrics, rows, ids, sequence
    with sqlite3.connect(copy) as conn:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert _state(db)["notnull"] == [0, 0, 0]
    # The notice names the copy, not where it is: CI logs are often public.
    (notice,) = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    assert notice == (
        "Notice: History database upgraded to v7. Some history commands of releases"
        " before 3.16.2 fail on it; a pre-upgrade backup (history.pre-v7.db) was saved"
        " next to it."
    )
    assert str(tmp_path) not in notice
    assert any(str(copy) in r.getMessage() for r in caplog.records if r.levelno == logging.DEBUG)


def test_only_the_rebuild_makes_a_copy(tmp_path, monkeypatch):
    copies_made = []
    real = history_module._backup_copy

    def counting(source, target):
        copies_made.append(1)
        real(source, target)

    monkeypatch.setattr(history_module, "_backup_copy", counting)
    fresh = tmp_path / "fresh" / "history.db"
    HistoryTracker(db_path=fresh)
    HistoryTracker(db_path=fresh)
    assert _copies(fresh.parent) == [] and copies_made == []

    old = tmp_path / "old" / "history.db"
    _old_database(old)
    for _ in range(3):
        HistoryTracker(db_path=old)  # the later opens find v7 and copy nothing
    assert _copies(old.parent) == [BACKUP] and copies_made == [1]


def test_a_rebuild_that_fails_leaves_no_copy_behind(tmp_path, monkeypatch):
    """The database is unchanged, so the copy is not needed; leaving it would
    add one more file on every failed attempt."""
    db = tmp_path / "history.db"
    _old_database(db)
    before = _state(db)

    def fail(conn, columns):
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(history_module, "_copy_rows", fail)
    with pytest.raises(sqlite3.OperationalError):
        HistoryTracker(db_path=db)

    assert _state(db) == before
    assert _copies(tmp_path) == []


def test_an_existing_copy_is_never_overwritten(tmp_path):
    db = tmp_path / "history.db"
    _old_database(db)
    kept = tmp_path / BACKUP
    kept.write_bytes(b"an earlier copy")

    HistoryTracker(db_path=db)

    assert kept.read_bytes() == b"an earlier copy"
    (other,) = [name for name in _copies(tmp_path) if name != BACKUP]
    assert _state(tmp_path / other)["notnull"] == [1, 1, 1]


def test_a_failed_copy_stops_the_upgrade(tmp_path, monkeypatch):
    db = tmp_path / "history.db"
    _old_database(db)
    before = _state(db)

    def full_disk(source, target):
        target.execute("CREATE TABLE partial (x)")
        target.commit()
        raise sqlite3.OperationalError("database or disk is full")

    monkeypatch.setattr(history_module, "_backup_copy", full_disk)
    with pytest.raises(HistoryBackupError, match="disk is full"):
        HistoryTracker(db_path=db)

    assert _state(db) == before
    assert _copies(tmp_path) == []


def test_a_copy_that_does_not_match_stops_the_upgrade(tmp_path, monkeypatch):
    db = tmp_path / "history.db"
    _old_database(db)
    before = _state(db)
    real = history_module._backup_copy

    def drifting(source, target):
        real(source, target)
        target.execute("DELETE FROM history WHERE id = 1")
        target.commit()

    monkeypatch.setattr(history_module, "_backup_copy", drifting)
    with pytest.raises(HistoryBackupError, match="does not match"):
        HistoryTracker(db_path=db)

    assert _state(db) == before
    assert _copies(tmp_path) == []


def test_restoring_the_copy_gives_back_the_old_database(tmp_path):
    db = tmp_path / "history.db"
    _old_database(db)
    before = _state(db)
    tracker = HistoryTracker(db_path=db)
    entry = history_module.HistoryEntry(
        timestamp="2026-11-18T00:00:00",
        file_path="/p/x.rs",
        file_hash="h",
        deficit_score=1.0,
        ldr_score=None,
        inflation_score=None,
        ddc_usage_ratio=None,
        pattern_count=0,
    )
    tracker._insert(entry)  # a v7 row the old release could not read

    os.replace(tmp_path / BACKUP, db)  # the documented restore

    assert _state(db) == before


def test_the_copy_gets_the_permission_bits_of_the_original(tmp_path):
    original, copy = tmp_path / "a.db", tmp_path / "b.db"
    original.write_bytes(b"x")
    copy.write_bytes(b"y")
    os.chmod(original, stat.S_IREAD)
    try:
        history_module._restrict_like(original, copy)
        assert stat.S_IMODE(os.stat(copy).st_mode) == stat.S_IMODE(os.stat(original).st_mode)
        assert not os.access(copy, os.W_OK)
    finally:
        os.chmod(original, stat.S_IREAD | stat.S_IWRITE)
        os.chmod(copy, stat.S_IREAD | stat.S_IWRITE)


def test_a_database_older_than_the_metric_columns_is_kept_too(tmp_path):
    """A table without the metric columns gains them NOT NULL, then is rebuilt:
    it is copied first like any other pre-v7 table."""
    db = tmp_path / "history.db"
    with sqlite3.connect(db) as conn:
        conn.execute(
            "CREATE TABLE history (id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT NOT NULL,"
            " file_path TEXT NOT NULL, file_hash TEXT NOT NULL, deficit_score REAL NOT NULL)"
        )
        conn.execute(
            "INSERT INTO history (timestamp, file_path, file_hash, deficit_score)"
            " VALUES ('2026-01-01T00:00:00', 'a.py', 'h', 40.0)"
        )
    with sqlite3.connect(db) as conn:
        before = conn.execute("SELECT * FROM history").fetchall()

    HistoryTracker(db_path=db)

    with sqlite3.connect(tmp_path / BACKUP) as conn:
        assert conn.execute("SELECT * FROM history").fetchall() == before


def test_removing_a_copy_ignores_only_a_missing_file(tmp_path):
    """A copy that is already gone is fine; any other I/O error is raised, not
    hidden (here a directory: PermissionError on Windows, IsADirectoryError or
    PermissionError elsewhere)."""
    history_module._discard(tmp_path / "absent.db")

    busy = tmp_path / "busy.db"
    busy.mkdir()
    with pytest.raises(OSError) as raised:
        history_module._discard(busy)
    assert not isinstance(raised.value, FileNotFoundError)
    assert busy.exists()


# --- INS-CAL-BKP-05: a write between the copy and the upgrade's write lock ---


def _write_between(monkeypatch, write):
    """Run `write` (once) after the copy is made and before the upgrade takes
    its write lock: another process writing in that window."""
    real = history_module._keep_pre_v7_copy
    done = []

    def copy_then_write(db_path):
        made = real(db_path)
        if not done:
            done.append(1)
            write(db_path)
        return made

    monkeypatch.setattr(history_module, "_keep_pre_v7_copy", copy_then_write)


def _insert_from_another_connection(db_path):
    with closing(sqlite3.connect(db_path)) as other, other:
        other.execute(
            "INSERT INTO history (timestamp, file_path, file_hash, deficit_score, provenance_state)"
            " VALUES ('2026-11-18T00:00:00', '/p/late.py', 'late', 5.0, 'v6')"
        )


def test_a_write_after_the_copy_stops_the_upgrade(tmp_path, monkeypatch):
    db = tmp_path / "history.db"
    _old_database(db)
    earlier = tmp_path / BACKUP
    earlier.write_bytes(b"an earlier copy")  # a copy from before: kept
    _write_between(monkeypatch, _insert_from_another_connection)

    with pytest.raises(HistoryBackupError) as raised:
        HistoryTracker(db_path=db)

    assert raised.value.cause == history_module.CONCURRENT_WRITE_DETECTED
    state = _state(db)
    assert state["notnull"] == [1, 1, 1]  # not upgraded
    assert state["rows"][-1][2] == "/p/late.py"  # the concurrent row is kept
    assert _copies(tmp_path) == [BACKUP] and earlier.read_bytes() == b"an earlier copy"


def test_the_next_run_upgrades_with_a_copy_that_has_the_late_row(tmp_path, monkeypatch):
    db = tmp_path / "history.db"
    _old_database(db)
    _write_between(monkeypatch, _insert_from_another_connection)
    with pytest.raises(HistoryBackupError):
        HistoryTracker(db_path=db)
    before_retry = _state(db)

    HistoryTracker(db_path=db)  # nothing writes in between this time

    assert _copies(tmp_path) == [BACKUP]
    assert _state(tmp_path / BACKUP) == before_retry  # the copy has the late row
    assert _state(db)["notnull"] == [0, 0, 0]


def test_a_copy_that_fails_says_backup_failed(tmp_path, monkeypatch):
    db = tmp_path / "history.db"
    _old_database(db)

    def full_disk(source, target):
        raise sqlite3.OperationalError("database or disk is full")

    monkeypatch.setattr(history_module, "_backup_copy", full_disk)
    with pytest.raises(HistoryBackupError) as raised:
        HistoryTracker(db_path=db)
    assert raised.value.cause == history_module.BACKUP_FAILED


def test_another_process_that_upgraded_first_is_not_an_error(tmp_path, monkeypatch):
    """Two 3.16.2 processes: the other one upgrades between this run's copy
    and its lock. This run finds v7, keeps no copy of its own and goes on."""
    db = tmp_path / "history.db"
    _old_database(db)
    before = _state(db)
    _write_between(monkeypatch, lambda path: HistoryTracker(db_path=path))

    HistoryTracker(db_path=db)

    (copy,) = _copies(tmp_path)  # the other process's copy only (this run's name was taken)
    assert _state(tmp_path / copy) == before
    assert _state(db)["notnull"] == [0, 0, 0]


# --- INS-CAL-BKP-06: an older table created after the check found nothing to copy ---


def _created_by_an_older_release(db_path):
    """Another process (an older release) creates its table and writes a row."""
    with closing(sqlite3.connect(db_path)) as other, other:
        other.executescript(OLD_TABLE)
        other.execute(
            "INSERT INTO history (timestamp, file_path, file_hash, deficit_score)"
            " VALUES ('2026-11-18T00:00:00', '/p/b.py', 'h', 10.0)"
        )


@pytest.mark.parametrize("start", ["no file", "empty file"])
def test_an_older_table_created_after_the_check_is_not_upgraded_without_a_copy(
    tmp_path, monkeypatch, start
):
    db = tmp_path / "history.db"
    if start == "empty file":
        db.write_bytes(b"")
    _write_between(monkeypatch, _created_by_an_older_release)

    with pytest.raises(HistoryBackupError) as raised:
        HistoryTracker(db_path=db)

    assert raised.value.cause == history_module.CONCURRENT_WRITE_DETECTED
    state = _state(db)
    assert state["notnull"] == [1, 1, 1]  # the older table, untouched
    assert len(state["rows"]) == 1
    assert _copies(tmp_path) == []

    before_retry = _state(db)
    monkeypatch.undo()
    HistoryTracker(db_path=db)  # the next run copies it first, then upgrades

    assert _copies(tmp_path) == [BACKUP]
    assert _state(tmp_path / BACKUP) == before_retry
    assert _state(db)["notnull"] == [0, 0, 0]


@pytest.mark.parametrize("start", ["no file", "empty file", "v7 database"])
def test_without_another_process_a_database_opens_as_before(tmp_path, start):
    db = tmp_path / "history.db"
    if start == "empty file":
        db.write_bytes(b"")
    if start == "v7 database":
        HistoryTracker(db_path=db)

    HistoryTracker(db_path=db)

    assert _state(db)["notnull"] == [0, 0, 0]
    assert _copies(tmp_path) == []
