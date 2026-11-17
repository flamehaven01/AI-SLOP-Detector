"""3.16.2 P1: history of all four languages, each row saying what was measured.

LDR, inflation and DDC are Python measurements. Before 3.16.2 only Python
files reached history, and a row always held three numbers: a file whose
metric was skipped (its role, --patterns-only, no executable code) or that
did not parse kept placeholder values there (a parse error stored LDR 0.0,
inflation 999 and DDC 0.0) that read as measurements.

Contract (history schema v7):
- every analyzed file is recorded, Python, JS/TS, Go and Rust, with its
  `language` and `parser_mode` (python_ast; tree_sitter_ast or the adapter's
  fallback mode);
- a metric column holds a value only when the metric was measured and
  counted; otherwise it is NULL and `unmeasured_metrics` says why
  (not_supported, skipped, parse_error);
- rules nobody looked at are unmeasured evidence: all of them when patterns
  did not run, the fallback's unmeasured rules for an adapter without its AST;
- an older database is rebuilt once so the three metric columns accept NULL:
  every row and id is kept, and a failed rebuild leaves the table as it was;
- readers of history accept NULL metrics.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from slop_detector import history as history_module
from slop_detector.cli_history import _record_history
from slop_detector.core import SlopDetector
from slop_detector.history import HistoryTracker
from slop_detector.language_registry import spec
from slop_detector.ml.calibration_evidence import withheld_evidence

SOURCES = {
    "a.py": "def f(x, acc=[]):\n    try:\n        return int(x)\n    except:\n        pass\n",
    "b.js": "function f(a) {\n  var x = a;\n  console.log(x);\n  return x == 1;\n}\n",
    # three panics: the Go rule's severity is the string "critical"
    "c.go": (
        "package main\n\nfunc f() {\n\t// TODO: implement\n"
        "\tpanic(\"a\")\n\tpanic(\"b\")\n\tpanic(\"c\")\n}\n"
    ),
    "d.rs": "fn f() -> i32 {\n    todo!()\n}\n",
}
METRICS = ("ldr_score", "inflation_score", "ddc_usage_ratio")

# The 3.16.1 table: the metric columns are NOT NULL with defaults.
OLD_TABLE = """
CREATE TABLE history (
    id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT NOT NULL,
    file_path TEXT NOT NULL, file_hash TEXT NOT NULL, deficit_score REAL NOT NULL,
    ldr_score REAL NOT NULL DEFAULT 0.0, inflation_score REAL NOT NULL DEFAULT 0.0,
    ddc_usage_ratio REAL NOT NULL DEFAULT 1.0, pattern_count INTEGER NOT NULL DEFAULT 0,
    n_critical_patterns INTEGER NOT NULL DEFAULT 0, grade TEXT NOT NULL DEFAULT '',
    git_commit TEXT, git_branch TEXT, fired_rules TEXT DEFAULT NULL,
    project_id TEXT DEFAULT NULL, detector_version TEXT DEFAULT NULL,
    measurement_fingerprint TEXT DEFAULT NULL, weights_vector TEXT DEFAULT NULL,
    project_root TEXT DEFAULT NULL, file_rel_path TEXT DEFAULT NULL,
    base_deficit REAL DEFAULT NULL, pattern_penalty REAL DEFAULT NULL,
    provenance_state TEXT DEFAULT NULL, withheld_evidence TEXT DEFAULT NULL
);
"""


@pytest.fixture
def history_db(tmp_path, monkeypatch):
    db = tmp_path / "home" / ".slop-detector" / "history.db"
    monkeypatch.setattr(HistoryTracker, "DEFAULT_DB", db)
    return db


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    for name, text in SOURCES.items():
        (root / name).write_text(text, encoding="utf-8")
    return root


def _rows(db: Path):
    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(r) for r in conn.execute("SELECT * FROM history ORDER BY id")]


def _by_suffix(rows):
    return {Path(r["file_path"]).suffix: r for r in rows}


def _scan_and_record(project: Path, config_path: str = None):
    detector = SlopDetector(config_path=config_path, read_only=True)
    result = detector.analyze_project(str(project), pattern="**/*")
    _record_history(result, detector.config, str(project), True)
    return result


def test_every_language_is_recorded_with_its_language_and_parser_mode(project, history_db):
    result = _scan_and_record(project)

    rows = _by_suffix(_rows(history_db))
    assert {s: r["language"] for s, r in rows.items()} == {
        ".py": "python",
        ".js": "javascript",
        ".go": "go",
        ".rs": "rust",
    }
    assert rows[".py"]["parser_mode"] == "python_ast"
    for suffix, name in ((".js", "javascript"), (".go", "go"), (".rs", "rust")):
        (adapter_result,) = getattr(result, spec(name).result_key)
        expected = "tree_sitter_ast" if adapter_result.ast_mode else spec(name).fallback_mode
        assert rows[suffix]["parser_mode"] == expected
    assert {r["provenance_state"] for r in rows.values()} == {"v7"}


def test_a_language_without_python_metrics_stores_none_of_them(project, history_db):
    result = _scan_and_record(project)

    rows = _by_suffix(_rows(history_db))
    for suffix, name in ((".js", "javascript"), (".go", "go"), (".rs", "rust")):
        row = rows[suffix]
        (adapter_result,) = getattr(result, spec(name).result_key)
        assert [row[m] for m in METRICS] == [None, None, None], suffix
        assert json.loads(row["unmeasured_metrics"]) == {
            "ddc": "not_supported",
            "inflation": "not_supported",
            "ldr": "not_supported",
        }
        assert row["deficit_score"] == pytest.approx(adapter_result.slop_score)
        assert adapter_result.issues, suffix  # each sample fires, so the counts are tested
        fired = {}
        for issue in adapter_result.issues:
            fired[issue.pattern_id] = fired.get(issue.pattern_id, 0) + 1
        assert json.loads(row["fired_rules"]) == fired
        assert row["pattern_count"] == len(adapter_result.issues)
        critical = sum(1 for i in adapter_result.issues if str(i.severity).lower() == "critical")
        assert row["n_critical_patterns"] == critical
        assert critical >= 1 or suffix != ".go"
        assert row["base_deficit"] is None and row["pattern_penalty"] is None


def test_a_measured_python_row_keeps_its_values(project, history_db):
    result = _scan_and_record(project)

    row = _by_suffix(_rows(history_db))[".py"]
    (py,) = result.file_results
    assert row["ldr_score"] == pytest.approx(py.ldr.ldr_score)
    assert row["inflation_score"] == pytest.approx(py.inflation.inflation_score)
    assert row["ddc_usage_ratio"] == pytest.approx(py.ddc.usage_ratio)
    assert json.loads(row["unmeasured_metrics"]) == {}


def test_a_skipped_python_metric_is_null_not_a_value(tmp_path, history_db):
    root = tmp_path / "proj"
    root.mkdir()
    (root / "mod.py").write_text(SOURCES["a.py"], encoding="utf-8")
    (root / ".slopconfig.yaml").write_text("advanced:\n  patterns_only: true\n", encoding="utf-8")
    _scan_and_record(root, str(root / ".slopconfig.yaml"))

    (row,) = _rows(history_db)
    assert [row[m] for m in METRICS] == [None, None, None]
    assert json.loads(row["unmeasured_metrics"]) == {
        "ddc": "skipped",
        "inflation": "skipped",
        "ldr": "skipped",
    }
    assert row["fired_rules"] is not None  # patterns still ran and were recorded


def test_a_python_file_that_did_not_parse_stores_no_placeholder(tmp_path, history_db):
    root = tmp_path / "proj"
    root.mkdir()
    (root / "broken.py").write_text("def f(:\n    pass\n", encoding="utf-8")
    _scan_and_record(root)

    (row,) = _rows(history_db)
    assert [row[m] for m in METRICS] == [None, None, None]
    assert set(json.loads(row["unmeasured_metrics"]).values()) == {"parse_error"}
    assert json.loads(row["withheld_evidence"])["unmeasured"] == ["all"]


def test_rules_nobody_looked_at_are_unmeasured_evidence(tmp_path, monkeypatch):
    protocol = "from typing import Protocol\n\n\nclass P(Protocol):\n    def f(self) -> int: ...\n"
    stub = SlopDetector(read_only=True).analyze_code_string(protocol, "iface.py")
    assert "patterns" in stub.skipped_metrics
    assert withheld_evidence(stub)["unmeasured"] == ["all"]

    from slop_detector.languages import js_analyzer

    monkeypatch.setattr(js_analyzer, "_TS_AVAILABLE", False)
    source = tmp_path / "b.js"
    source.write_text(SOURCES["b.js"], encoding="utf-8")
    fallback = js_analyzer.JSAnalyzer().analyze(str(source))
    assert not fallback.ast_mode
    assert set(spec("javascript").fallback_not_measured()) <= set(
        withheld_evidence(fallback)["unmeasured"]
    )


def _old_database(db: Path):
    db.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db) as conn:
        conn.executescript(OLD_TABLE)
        for i in range(3):
            conn.execute(
                "INSERT INTO history (timestamp, file_path, file_hash, deficit_score,"
                " ldr_score, inflation_score, ddc_usage_ratio, pattern_count, grade,"
                " provenance_state, withheld_evidence) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (f"2026-11-0{i + 1}T00:00:00", f"/p/m{i}.py", f"h{i}", 10.0 * i,
                 0.1 * i, 0.2 * i, 0.3 * i, i, "clean", "v6" if i else None, None),
            )
        conn.execute("DELETE FROM history WHERE id = 3")  # its id is never handed out again


def _notnull(db: Path):
    with sqlite3.connect(db) as conn:
        return {r[1]: r[3] for r in conn.execute("PRAGMA table_info(history)")}


def test_an_older_database_is_rebuilt_once_and_keeps_every_row(tmp_path):
    db = tmp_path / "history.db"
    _old_database(db)
    before = _rows(db)

    tracker = HistoryTracker(db_path=db)
    HistoryTracker(db_path=db)  # a second open finds nothing to do

    after = _rows(db)
    assert [{k: r[k] for k in before[0]} for r in after] == before
    assert [r["id"] for r in after] == [1, 2]
    assert [_notnull(db)[m] for m in METRICS] == [0, 0, 0]
    entry = history_module.HistoryEntry(
        timestamp="2026-11-17T00:00:00", file_path="/p/x.rs", file_hash="h",
        deficit_score=1.0, ldr_score=None, inflation_score=None, ddc_usage_ratio=None,
        pattern_count=0,
    )
    tracker._insert(entry)
    assert _rows(db)[-1]["id"] == 4  # the sequence continues past the old ids


def test_a_failed_rebuild_leaves_the_table_as_it_was(tmp_path, monkeypatch):
    db = tmp_path / "history.db"
    _old_database(db)
    before = _rows(db)

    def fail(conn, columns):
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(history_module, "_copy_rows", fail)
    with pytest.raises(sqlite3.OperationalError):
        HistoryTracker(db_path=db)

    assert _rows(db) == before
    assert [_notnull(db)[m] for m in METRICS] == [1, 1, 1]


def test_history_readers_accept_rows_without_python_metrics(project, history_db, capsys):
    _scan_and_record(project)
    tracker = HistoryTracker()

    trends = tracker.get_project_trends(days=1)
    assert trends["data_points"] == 1  # the four rows of today, three without LDR
    rust_file = str((project / "d.rs").resolve())
    assert tracker.get_file_history(rust_file)[0]["ldr_score"] is None

    from slop_detector.cli_history import _show_file_history

    _show_file_history(rust_file)
    assert "History:" in capsys.readouterr().out


def test_the_api_project_route_records_every_language(project, history_db):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from slop_detector.api.server import create_app

    body = {"project_path": str(project), "save_history": True}
    assert TestClient(create_app()).post("/analyze/project", json=body).status_code == 200

    assert sorted(r["language"] for r in _rows(history_db)) == [
        "go",
        "javascript",
        "python",
        "rust",
    ]


def test_a_scan_of_a_relative_path_records_absolute_file_paths(project, history_db, monkeypatch):
    """Adapter results carry the path as the scan was given it: history keys a
    file by its absolute path, whatever directory the scan ran from."""
    monkeypatch.chdir(project.parent)
    _scan_and_record(Path(project.name))

    recorded = {Path(r["file_path"]).name: r["file_path"] for r in _rows(history_db)}
    assert recorded == {name: str((project / name).resolve()) for name in SOURCES}
    rust_file = str((project / "d.rs").resolve())
    assert HistoryTracker().get_file_history(rust_file)
