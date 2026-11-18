"""
Historical trend tracking for slop detection.

Stores analysis results in SQLite and provides per-file trend analysis.
Auto-recorded on every CLI run; opt-out with --no-history.

Schema v2 (v2.9.0):
  - inflation_score replaces bcr_score (v2.8.0 rename)
  - pattern_count added

Schema v3 (v3.2.0):
  - n_critical_patterns added (CRITICAL-severity pattern count per file)
    Required for 4D self-calibration (purity dimension).

Schema v4 (v3.4.0):
  - fired_rules added (JSON: {"pattern_id": count, ...})
    Required for per-rule FP rate tracking in LEDA self-calibration.

Schema v5 (v3.5.0):
  - project_id added (sha256[:12] of resolved cwd at scan time)
    Prevents cross-project calibration signal pollution in global history.db.

Schema v6 (v3.10):
  - measurement provenance: detector_version, measurement_fingerprint
    (detector version + cache engine + full configuration), weights_vector,
    project_root (canonical scan root), file_rel_path, base_deficit,
    pattern_penalty, provenance_state ("v6").
    Only v6 rows are calibration evidence; older rows are kept as they are
    (provenance_state NULL = legacy, unknown measurement) and never rewritten.

Schema v7 (3.16.2):
  - every analyzed language is recorded: language, parser_mode, and
    unmeasured_metrics (JSON {metric: not_supported | skipped | parse_error |
    not_reported});
  - ldr_score, inflation_score and ddc_usage_ratio hold a value only when the
    metric was measured and counted, else NULL. A database made before v7 is
    rebuilt once (in one transaction) so these columns accept NULL; its rows,
    ids and values are kept.
  - new rows are provenance_state "v7"; v6 and v7 rows are calibration
    evidence. A release that reads only v6 rows never meets a NULL metric.
  - before that rebuild the database is kept as it was in history.pre-v7.db
    (a checked SQLite snapshot; an existing copy is never overwritten). A
    copy that fails or does not match stops the upgrade. Restoring it is a
    user action (docs/HISTORY_TRACKING.md); it is a recovery path, not
    compatibility of older releases with a v7 database.
"""

import hashlib
import json
import logging
import shutil
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, NamedTuple, Optional

logger = logging.getLogger(__name__)

PROVENANCE_V6 = "v6"
PROVENANCE_V7 = "v7"
EVIDENCE_PROVENANCE = (PROVENANCE_V6, PROVENANCE_V7)
PRE_V7_BACKUP = "history.pre-v7.db"  # next to the database it was taken from

# What a user is told; no absolute path (CI logs are often public). The
# detail (paths, the error) goes to the debug log.
UPGRADE_NOTICE = (
    "Notice: History database upgraded to v7. Some history commands of releases"
    " before 3.16.2 fail on it; a pre-upgrade backup ({name}) was saved next to it."
)
HISTORY_NOT_RECORDED = (
    "Warning: History was not recorded because the pre-upgrade backup failed."
    " The original database is unchanged. See debug logs for details."
)
HISTORY_NOT_OPENED = (
    "Error: History could not be opened because the pre-upgrade backup failed."
    " The original database is unchanged. See debug logs for details."
)


BACKUP_FAILED = "BACKUP_FAILED"  # the copy could not be made or does not match
# Another process wrote between the copy and the upgrade's write lock: the
# copy is not the database as it was right before the upgrade.
CONCURRENT_WRITE_DETECTED = "CONCURRENT_WRITE_DETECTED"


class HistoryBackupError(RuntimeError):
    """The copy kept before the v7 rebuild could not be made, checked or
    trusted (`cause`); the database was not changed."""

    def __init__(self, message: str, cause: str = BACKUP_FAILED) -> None:
        super().__init__(f"{cause}: {message}")
        self.cause = cause


class _PreV7Copy(NamedTuple):
    path: Path
    digest: str  # _snapshot_digest of the database the copy was taken from

# The Python metrics: (name, FileAnalysis attribute, its field, history column).
PYTHON_METRICS = (
    ("ldr", "ldr", "ldr_score", "ldr_score"),
    ("inflation", "inflation", "inflation_score", "inflation_score"),
    ("ddc", "ddc", "usage_ratio", "ddc_usage_ratio"),
)
_METRIC_COLUMNS = tuple(column for _, _, _, column in PYTHON_METRICS)

_TABLE = """
CREATE TABLE IF NOT EXISTS history (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp            TEXT    NOT NULL,
    file_path            TEXT    NOT NULL,
    file_hash            TEXT    NOT NULL,
    deficit_score        REAL    NOT NULL,
    ldr_score            REAL    DEFAULT NULL,
    inflation_score      REAL    DEFAULT NULL,
    ddc_usage_ratio      REAL    DEFAULT NULL,
    pattern_count        INTEGER NOT NULL DEFAULT 0,
    n_critical_patterns  INTEGER NOT NULL DEFAULT 0,
    grade                TEXT    NOT NULL DEFAULT '',
    git_commit           TEXT,
    git_branch           TEXT
)
"""
_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_file_path ON history(file_path)",
    "CREATE INDEX IF NOT EXISTS idx_timestamp ON history(timestamp DESC)",
    "CREATE INDEX IF NOT EXISTS idx_v6_evidence"
    " ON history(project_root, file_rel_path, measurement_fingerprint, timestamp)",
)

# v6 provenance columns (all nullable: NULL on legacy rows).
_V6_COLUMNS = {
    "detector_version": "TEXT",
    "measurement_fingerprint": "TEXT",
    "weights_vector": "TEXT",
    "project_root": "TEXT",
    "file_rel_path": "TEXT",
    "base_deficit": "REAL",
    "pattern_penalty": "REAL",
    "provenance_state": "TEXT",
}
# v7 measurement columns (NULL on older rows).
_V7_COLUMNS = {"language": "TEXT", "parser_mode": "TEXT", "unmeasured_metrics": "TEXT"}


@dataclass
class HistoryEntry:
    """Single historical analysis record."""

    timestamp: str
    file_path: str
    file_hash: str
    deficit_score: float
    ldr_score: Optional[float]  # None: not measured (unmeasured_metrics says why)
    inflation_score: Optional[float]
    ddc_usage_ratio: Optional[float]
    pattern_count: int
    grade: str = ""
    n_critical_patterns: int = 0  # v3.2.0: CRITICAL-severity patterns (purity calibration signal)
    fired_rules: Optional[str] = None  # v3.4.0: JSON {pattern_id: count} for per-rule FP tracking
    git_commit: Optional[str] = None
    git_branch: Optional[str] = None
    project_id: Optional[str] = None  # v3.5.0: sha256[:12] of cwd (legacy, not evidence)
    # v6 measurement provenance (None on legacy rows)
    detector_version: Optional[str] = None
    measurement_fingerprint: Optional[str] = None
    weights_vector: Optional[str] = None  # JSON {dimension: weight}
    project_root: Optional[str] = None
    file_rel_path: Optional[str] = None
    base_deficit: Optional[float] = None
    pattern_penalty: Optional[float] = None
    provenance_state: Optional[str] = None
    # 3.16.2: what the scan held back per rule (suppressed with the user's kind of
    # judgment, unmeasured, masked, ignored); JSON, None on older rows.
    withheld_evidence: Optional[str] = None
    # v7: what measured the row (None on older rows)
    language: Optional[str] = None
    parser_mode: Optional[str] = None
    unmeasured_metrics: Optional[str] = None  # JSON {metric: reason}

    def __post_init__(self) -> None:
        # Clamp scores so malformed data never corrupts the calibration grid search.
        self.deficit_score = max(0.0, self.deficit_score)
        if self.ldr_score is not None:
            self.ldr_score = max(0.0, min(1.0, self.ldr_score))
        if self.inflation_score is not None:
            self.inflation_score = max(0.0, self.inflation_score)
        if self.ddc_usage_ratio is not None:
            self.ddc_usage_ratio = max(0.0, min(1.0, self.ddc_usage_ratio))
        self.n_critical_patterns = max(0, self.n_critical_patterns)
        self.pattern_count = max(0, self.pattern_count)
        if self.fired_rules is not None:
            try:
                json.loads(self.fired_rules)
            except (json.JSONDecodeError, ValueError) as exc:
                raise ValueError(f"HistoryEntry.fired_rules must be valid JSON: {exc}") from exc


@dataclass(frozen=True)
class MeasurementProvenance:
    """What measured a history row: two rows are comparable only if this matches."""

    detector_version: str
    measurement_fingerprint: str
    weights: Dict[str, float]
    project_root: Path


def measurement_provenance(config, project_root: Path) -> MeasurementProvenance:
    """Provenance of a scan with `config` under the canonical `project_root`.

    The fingerprint covers the detector version, the analysis engine version
    and the whole effective configuration (weights, thresholds, ignore rules,
    disabled patterns, runtime overrides): any of them can change a score.
    """
    from slop_detector import __version__
    from slop_detector.analysis_cache import CACHE_ENGINE_VERSION, fingerprint_config

    payload = json.dumps(
        {
            "detector": __version__,
            "engine": CACHE_ENGINE_VERSION,
            "config": fingerprint_config(config.config),
        },
        sort_keys=True,
    )
    return MeasurementProvenance(
        detector_version=__version__,
        measurement_fingerprint=hashlib.sha256(payload.encode("utf-8")).hexdigest(),
        weights=dict(config.get_weights()),
        project_root=Path(project_root).resolve(),
    )


def _withheld_json(file_analysis) -> Optional[str]:
    """withheld_evidence of one file result as JSON (calibration_evidence)."""
    from slop_detector.ml.calibration_evidence import withheld_evidence

    return json.dumps(withheld_evidence(file_analysis), sort_keys=True)


def history_project_root(path: str, is_project: bool) -> Path:
    """Canonical project root of a scan: the scanned directory for a project
    scan, the nearest project marker (else the parent) for a single file."""
    from slop_detector.project_resolution import find_project_root

    target = Path(path).resolve()
    if is_project:
        return target
    return find_project_root(target) or target.parent


class HistoryTracker:
    """Track slop detection results over time (SQLite, auto-migrated)."""

    DEFAULT_DB = Path.home() / ".slop-detector" / "history.db"

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = Path(db_path) if db_path else self.DEFAULT_DB
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_database()

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def _init_database(self) -> None:
        """Create or migrate the table in one transaction: a migration that
        fails leaves the database as it was. A database that needs the v7
        rebuild is first kept in a checked copy; a copy that no rebuild used
        (it failed, or another process rebuilt first) is removed again.

        Once the write lock is held and before any schema change, the database
        must still be the one the copy was taken from: a write by another
        process in between stops the upgrade (CONCURRENT_WRITE_DETECTED); the
        next run makes a new copy."""
        backup = _keep_pre_v7_copy(self.db_path)
        rebuilt = False
        try:
            with self._managed_conn() as conn:
                conn.isolation_level = None  # the transaction below is explicit
                conn.execute("BEGIN IMMEDIATE")
                try:
                    _check_still_copied(conn, backup)
                    conn.execute(_TABLE)
                    self._migrate(conn)
                    rebuilding = _rebuild_with_nullable_metrics(conn)
                    for ddl in _INDEXES:
                        conn.execute(ddl)
                    conn.execute("COMMIT")
                    rebuilt = rebuilding  # only a committed rebuild used the copy
                except BaseException:
                    conn.execute("ROLLBACK")
                    raise
        finally:
            if backup is not None and not rebuilt:
                _discard(backup.path)  # this attempt's copy only
        if backup is not None and rebuilt:
            logger.warning(UPGRADE_NOTICE.format(name=backup.path.name))
            logger.debug(
                "history upgrade: %s rebuilt; pre-upgrade copy %s", self.db_path, backup.path
            )

    def _migrate(self, conn: sqlite3.Connection) -> None:
        """Add columns introduced after initial schema if missing."""
        existing = {row[1] for row in conn.execute("PRAGMA table_info(history)")}
        migrations = {
            "inflation_score": "ALTER TABLE history ADD COLUMN inflation_score REAL NOT NULL DEFAULT 0.0",
            "pattern_count": "ALTER TABLE history ADD COLUMN pattern_count INTEGER NOT NULL DEFAULT 0",
            "ldr_score": "ALTER TABLE history ADD COLUMN ldr_score REAL NOT NULL DEFAULT 0.0",
            "ddc_usage_ratio": "ALTER TABLE history ADD COLUMN ddc_usage_ratio REAL NOT NULL DEFAULT 1.0",
            "grade": "ALTER TABLE history ADD COLUMN grade TEXT NOT NULL DEFAULT ''",
            "n_critical_patterns": "ALTER TABLE history ADD COLUMN n_critical_patterns INTEGER NOT NULL DEFAULT 0",
            "fired_rules": "ALTER TABLE history ADD COLUMN fired_rules TEXT DEFAULT NULL",
            "project_id": "ALTER TABLE history ADD COLUMN project_id TEXT DEFAULT NULL",
            "git_commit": "ALTER TABLE history ADD COLUMN git_commit TEXT DEFAULT NULL",
            "git_branch": "ALTER TABLE history ADD COLUMN git_branch TEXT DEFAULT NULL",
            "withheld_evidence": "ALTER TABLE history ADD COLUMN withheld_evidence TEXT DEFAULT NULL",
        }
        for columns in (_V6_COLUMNS, _V7_COLUMNS):
            for col, kind in columns.items():
                migrations[col] = f"ALTER TABLE history ADD COLUMN {col} {kind} DEFAULT NULL"
        for col, ddl in migrations.items():
            if col not in existing:
                conn.execute(ddl)

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _managed_conn(self):
        return closing(self._conn())

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def record(
        self,
        file_analysis,
        git_commit: Optional[str] = None,
        git_branch: Optional[str] = None,
        project_id: Optional[str] = None,
        provenance: Optional[MeasurementProvenance] = None,
    ) -> None:
        """Record a FileAnalysis result. Accepts the dataclass directly.

        git_commit / git_branch: captured once per CLI run and passed in (v3.2.1).
        project_id: sha256[:12] of resolved cwd (v3.5.0); kept for old readers.
        provenance: what measured the result (v6). Without it the row is
        recorded as legacy and is never calibration evidence.
        """
        file_path = _absolute(str(getattr(file_analysis, "file_path", "")))
        measured = _measurement(file_analysis)
        pattern_count, n_critical_patterns, fired_rules_json = _pattern_summary(
            measured["issues"]
        )

        status = getattr(file_analysis, "status", None)
        grade = status.value if status and hasattr(status, "value") else str(status or "")

        metrics = measured["metrics"]
        entry = HistoryEntry(
            timestamp=datetime.now().isoformat(),
            file_path=file_path,
            file_hash=_sha256(file_path),
            deficit_score=measured["deficit"],
            ldr_score=metrics.get("ldr"),
            inflation_score=metrics.get("inflation"),
            ddc_usage_ratio=metrics.get("ddc"),
            pattern_count=pattern_count,
            n_critical_patterns=n_critical_patterns,
            fired_rules=fired_rules_json,
            grade=grade,
            git_commit=git_commit,
            git_branch=git_branch,
            project_id=project_id,
            withheld_evidence=_withheld_json(file_analysis),
            language=measured["language"],
            parser_mode=measured["parser_mode"],
            unmeasured_metrics=json.dumps(measured["unmeasured"], sort_keys=True),
        )
        if provenance is not None:
            _apply_provenance(entry, provenance, file_analysis)
        self._insert(entry)

    def _insert(self, e: HistoryEntry) -> None:
        sql = """
        INSERT INTO history
            (timestamp, file_path, file_hash, deficit_score, ldr_score,
             inflation_score, ddc_usage_ratio, pattern_count, n_critical_patterns,
             fired_rules, grade, git_commit, git_branch, project_id,
             detector_version, measurement_fingerprint, weights_vector, project_root,
             file_rel_path, base_deficit, pattern_penalty, provenance_state, withheld_evidence,
             language, parser_mode, unmeasured_metrics)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        with self._managed_conn() as conn:
            conn.execute(
                sql,
                (
                    e.timestamp,
                    e.file_path,
                    e.file_hash,
                    e.deficit_score,
                    e.ldr_score,
                    e.inflation_score,
                    e.ddc_usage_ratio,
                    e.pattern_count,
                    e.n_critical_patterns,
                    e.fired_rules,
                    e.grade,
                    e.git_commit,
                    e.git_branch,
                    e.project_id,
                    e.detector_version,
                    e.measurement_fingerprint,
                    e.weights_vector,
                    e.project_root,
                    e.file_rel_path,
                    e.base_deficit,
                    e.pattern_penalty,
                    e.provenance_state,
                    e.withheld_evidence,
                    e.language,
                    e.parser_mode,
                    e.unmeasured_metrics,
                ),
            )
            conn.commit()

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def count_total_records(self) -> int:
        """Return total number of records in the history database."""
        with self._managed_conn() as conn:
            row = conn.execute("SELECT COUNT(*) FROM history").fetchone()
        return int(row[0]) if row else 0

    def count_files_with_multiple_runs(self, project_id: Optional[str] = None) -> int:
        """Return count of distinct files scanned at least twice (calibration readiness signal).

        v3.5.0: Replaces count_total_records() as the calibration trigger basis.
        A file scanned once contributes zero calibration events; only repeat scans can
        produce improvement/fp_candidate pairs. This prevents first-time large project
        scans from firing spurious calibration milestones.
        """
        if project_id is not None:
            sql = """
            SELECT COUNT(*) FROM (
                SELECT file_path FROM history WHERE project_id = ?
                GROUP BY file_path HAVING COUNT(*) >= 2
            )
            """
            with self._managed_conn() as conn:
                row = conn.execute(sql, (project_id,)).fetchone()
        else:
            sql = """
            SELECT COUNT(*) FROM (
                SELECT file_path FROM history GROUP BY file_path HAVING COUNT(*) >= 2
            )
            """
            with self._managed_conn() as conn:
                row = conn.execute(sql).fetchone()
        return int(row[0]) if row else 0

    def get_file_history(self, file_path: str, limit: int = 20) -> List[Dict[str, Any]]:
        """Return recent history for a specific file, newest first."""
        sql = """
        SELECT timestamp, file_hash, deficit_score, ldr_score,
               inflation_score, ddc_usage_ratio, pattern_count, grade
        FROM history
        WHERE file_path = ?
        ORDER BY timestamp DESC
        LIMIT ?
        """
        with self._managed_conn() as conn:
            rows = conn.execute(sql, (file_path, limit)).fetchall()

        return [
            {
                "timestamp": r[0],
                "file_hash": r[1],
                "deficit_score": r[2],
                "ldr_score": r[3],
                "inflation_score": r[4],
                "ddc_usage_ratio": r[5],
                "pattern_count": r[6],
                "grade": r[7],
            }
            for r in rows
        ]

    def detect_regression(self, file_path: str, current_score: float) -> Optional[Dict[str, Any]]:
        """Return regression info if current score is 10+ points worse than recent avg."""
        summary = self.get_file_drift_summary(file_path, current_score, limit=5)
        if summary is None:
            return None
        summary["is_regression"] = summary["delta"] >= 10.0
        return summary

    def get_file_drift_summary(
        self, file_path: str, current_score: float, limit: int = 5
    ) -> Optional[Dict[str, Any]]:
        """Return a temporal drift summary for a file.

        This is a read-only comparison surface over existing history records.
        It does not mutate policy or alter scoring.
        """
        history = self.get_file_history(file_path, limit=limit)
        if not history:
            return None

        recent_avg = sum(h["deficit_score"] for h in history) / len(history)
        delta = current_score - recent_avg
        direction = "improved" if delta < 0 else "degraded" if delta > 0 else "stable"

        return {
            "current_score": current_score,
            "recent_average": round(recent_avg, 2),
            "delta": round(delta, 2),
            "direction": direction,
            "history_count": len(history),
            "is_regression": delta >= 10.0,
        }

    def get_project_trends(self, days: int = 7) -> Dict[str, Any]:
        """Daily aggregate trends for the past N days."""
        sql = """
        SELECT
            DATE(timestamp)        AS date,
            AVG(deficit_score)     AS avg_deficit,
            AVG(ldr_score)         AS avg_ldr,
            AVG(inflation_score)   AS avg_inflation,
            AVG(ddc_usage_ratio)   AS avg_ddc,
            SUM(pattern_count)     AS total_patterns,
            COUNT(*)               AS file_count
        FROM history
        WHERE timestamp >= datetime('now', '-' || ? || ' days')
        GROUP BY DATE(timestamp)
        ORDER BY date DESC
        """
        with self._managed_conn() as conn:
            rows = conn.execute(sql, (days,)).fetchall()

        # AVG skips NULL: a day whose rows measured no LDR has no average (None).
        return {
            "period_days": days,
            "data_points": len(rows),
            "daily_trends": [
                {
                    "date": r[0],
                    "avg_deficit": round(r[1], 2),
                    "avg_ldr": _rounded(r[2], 3),
                    "avg_inflation": _rounded(r[3], 3),
                    "avg_ddc": _rounded(r[4], 3),
                    "total_patterns": r[5],
                    "files_analyzed": r[6],
                }
                for r in rows
            ],
        }

    def export_jsonl(self, output_path: str) -> int:
        """Export full history to JSONL — one record per line. Returns row count."""
        sql = """
        SELECT timestamp, file_path, file_hash, deficit_score, ldr_score,
               inflation_score, ddc_usage_ratio, pattern_count, grade,
               git_commit, git_branch, language, parser_mode, unmeasured_metrics
        FROM history ORDER BY timestamp DESC
        """
        with self._managed_conn() as conn:
            rows = conn.execute(sql).fetchall()

        with open(output_path, "w", encoding="utf-8") as f:
            for r in rows:
                rec = {
                    "timestamp": r[0],
                    "file_path": r[1],
                    "file_hash": r[2],
                    "deficit_score": r[3],
                    "ldr_score": r[4],
                    "inflation_score": r[5],
                    "ddc_usage_ratio": r[6],
                    "pattern_count": r[7],
                    "grade": r[8],
                    "git_commit": r[9],
                    "git_branch": r[10],
                    "language": r[11],
                    "parser_mode": r[12],
                    "unmeasured_metrics": json.loads(r[13]) if r[13] else None,
                }
                f.write(json.dumps(rec) + "\n")

        return len(rows)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _pattern_summary(pattern_issues: List[Any]):
    """(finding count, CRITICAL count, fired_rules JSON {pattern_id: count} or None).

    A Python issue's severity is an enum, an adapter issue's a string."""
    n_critical = sum(1 for issue in pattern_issues if _severity(issue) == "critical")
    rule_counts: Dict[str, int] = {}
    for issue in pattern_issues:
        pid = str(getattr(issue, "pattern_id", "unknown"))
        rule_counts[pid] = rule_counts.get(pid, 0) + 1
    fired_rules = json.dumps(rule_counts) if rule_counts else None
    return len(pattern_issues), n_critical, fired_rules


def _apply_provenance(
    entry: HistoryEntry, provenance: MeasurementProvenance, file_analysis
) -> None:
    """Fill the v6 columns: who measured the row, where, and how the score splits."""
    root = provenance.project_root
    try:
        rel: Optional[str] = Path(entry.file_path).resolve().relative_to(root).as_posix()
    except ValueError:
        rel = None
    entry.detector_version = provenance.detector_version
    entry.measurement_fingerprint = provenance.measurement_fingerprint
    entry.weights_vector = json.dumps(provenance.weights, sort_keys=True)
    entry.project_root = str(root)
    entry.file_rel_path = rel
    entry.provenance_state = PROVENANCE_V7
    if entry.language != "python":
        return  # an adapter's score has no weighted-metric part to split off
    breakdown = getattr(file_analysis, "deficit_breakdown", None) or {}
    penalty = float(breakdown.get("pattern_hits", 0.0))
    entry.base_deficit = max(0.0, entry.deficit_score - penalty)
    entry.pattern_penalty = penalty


def _severity(issue: Any) -> str:
    severity = getattr(issue, "severity", None)
    return str(getattr(severity, "value", severity) or "").lower()


def _measurement(file_analysis: Any) -> Dict[str, Any]:
    """What measured one file result: language, parser mode, the Python metrics
    that were measured and counted ({name: value}), the others with the reason
    ({name: reason}), the score and the findings."""
    from slop_detector.core_project import is_parse_error
    from slop_detector.language_registry import spec_for_suffix

    adapter = spec_for_suffix(Path(str(getattr(file_analysis, "file_path", ""))).suffix)
    if adapter is not None:
        ast = bool(getattr(file_analysis, "ast_mode", False))
        return {
            "language": adapter.name,
            "parser_mode": "tree_sitter_ast" if ast else adapter.fallback_mode,
            "metrics": {},
            "unmeasured": {name: "not_supported" for name, _, _, _ in PYTHON_METRICS},
            "deficit": float(getattr(file_analysis, "slop_score", 0.0)),
            "issues": list(getattr(file_analysis, "issues", None) or []),
        }
    skipped = set(getattr(file_analysis, "skipped_metrics", None) or ())
    parse_error = is_parse_error(file_analysis)
    metrics: Dict[str, float] = {}
    unmeasured: Dict[str, str] = {}
    for name, attribute, value_field, _ in PYTHON_METRICS:
        source = getattr(file_analysis, attribute, None)
        if parse_error:
            unmeasured[name] = "parse_error"
        elif name in skipped:
            unmeasured[name] = "skipped"
        elif source is None or getattr(source, value_field, None) is None:
            unmeasured[name] = "not_reported"
        else:
            metrics[name] = float(getattr(source, value_field))
    return {
        "language": "python",
        "parser_mode": "python_ast",
        "metrics": metrics,
        "unmeasured": unmeasured,
        "deficit": float(getattr(file_analysis, "deficit_score", 0.0)),
        "issues": list(getattr(file_analysis, "pattern_issues", None) or []),
    }


def _metrics_not_null(conn: sqlite3.Connection) -> bool:
    """Whether the history table is pre-v7: a metric column is NOT NULL."""
    info = conn.execute("PRAGMA table_info(history)").fetchall()
    return any(row[1] in _METRIC_COLUMNS and row[3] for row in info)


def _needs_v7_rebuild(conn: sqlite3.Connection) -> bool:
    """Whether opening this database will rebuild its table: a metric column
    is NOT NULL, or missing (the migration adds it NOT NULL, then rebuilds)."""
    columns = {row[1] for row in conn.execute("PRAGMA table_info(history)")}
    if not columns:
        return False  # no table yet: it is created on v7
    return _metrics_not_null(conn) or not set(_METRIC_COLUMNS) <= columns


def _keep_pre_v7_copy(db_path: Path) -> Optional[_PreV7Copy]:
    """Before a v7 rebuild, keep the database as it is: a SQLite backup made
    and checked inside one read transaction (one snapshot), then given the
    original's permission bits; returned with the snapshot's digest. None
    when no rebuild is needed. On any failure the copy is removed and
    HistoryBackupError (BACKUP_FAILED) stops the upgrade."""
    if not db_path.exists():
        return None
    with closing(sqlite3.connect(db_path)) as source:
        if not _needs_v7_rebuild(source):
            return None
        target_path = _free_backup_path(db_path)
        source.isolation_level = None
        source.execute("BEGIN")
        try:
            expected = _snapshot_digest(source)
            with closing(sqlite3.connect(target_path)) as target:
                _backup_copy(source, target)
                _check_copy(target, expected)
            _restrict_like(db_path, target_path)
        except (sqlite3.Error, OSError, HistoryBackupError) as exc:
            _discard(target_path)
            raise HistoryBackupError(
                f"history upgrade stopped, {db_path} was not changed: the copy to keep"
                f" before the v7 rebuild failed ({exc})"
            ) from exc
        finally:
            source.execute("ROLLBACK")
    return _PreV7Copy(target_path, expected)


def _check_still_copied(conn: sqlite3.Connection, backup: Optional[_PreV7Copy]) -> None:
    """Inside the upgrade's write transaction, before any schema change: the
    database must be the one the copy was taken from. Another process that
    already upgraded it is not an error (nothing is rebuilt, the copy is
    removed); a write since the copy is (CONCURRENT_WRITE_DETECTED)."""
    if backup is None or not _needs_v7_rebuild(conn):
        return
    if _snapshot_digest(conn) != backup.digest:
        raise HistoryBackupError(
            "the database changed after the pre-upgrade copy was taken; upgrade stopped,"
            " the next run makes a new copy",
            cause=CONCURRENT_WRITE_DETECTED,
        )


def _free_backup_path(db_path: Path) -> Path:
    """history.pre-v7.db, or a new name beside it: a copy is never overwritten."""
    path = db_path.with_name(PRE_V7_BACKUP)
    if path.exists():
        path = db_path.with_name(f"history.pre-v7-{datetime.now():%Y%m%dT%H%M%S%f}.db")
    return path


def _backup_copy(source: sqlite3.Connection, target: sqlite3.Connection) -> None:
    source.backup(target)


def _snapshot_digest(conn: sqlite3.Connection) -> str:
    """SHA-256 of the history table as it is: its schema, every row by id and
    its AUTOINCREMENT sequence."""
    digest = hashlib.sha256()
    for row in conn.execute(
        "SELECT type, name, sql FROM sqlite_master WHERE tbl_name = 'history' ORDER BY name"
    ):
        digest.update(repr(row).encode("utf-8"))
    for row in conn.execute("SELECT * FROM history ORDER BY id"):
        digest.update(repr(row).encode("utf-8"))
    digest.update(repr(_sequence(conn)).encode("utf-8"))
    return digest.hexdigest()


def _check_copy(target: sqlite3.Connection, expected: str) -> None:
    integrity = target.execute("PRAGMA integrity_check").fetchone()[0]
    if integrity != "ok":
        raise HistoryBackupError(f"the copy fails integrity_check: {integrity}")
    if _snapshot_digest(target) != expected:
        raise HistoryBackupError("the copy does not match the database")


def _restrict_like(original: Path, copy: Path) -> None:
    """The copy gets the original's permission bits (on Windows, read-only or
    not; the ACL is inherited from the folder both are in)."""
    shutil.copymode(original, copy)


def _discard(path: Path) -> None:
    path.unlink(missing_ok=True)  # a copy that failed early may not exist


def _rebuild_with_nullable_metrics(conn: sqlite3.Connection) -> bool:
    """Rebuild a pre-v7 table whose metric columns are NOT NULL, inside the
    caller's transaction: same columns (the metric ones now nullable), every
    row and id, and the AUTOINCREMENT sequence. True when it rebuilt."""
    if not _metrics_not_null(conn):
        return False
    info = conn.execute("PRAGMA table_info(history)").fetchall()
    definitions = []
    for _, name, kind, notnull, default, pk in info:
        if pk:
            definitions.append(f"{name} INTEGER PRIMARY KEY AUTOINCREMENT")
        elif name in _METRIC_COLUMNS:
            definitions.append(f"{name} REAL DEFAULT NULL")
        else:
            constraint = " NOT NULL" if notnull else ""
            fallback = f" DEFAULT {default}" if default is not None else ""
            definitions.append(f"{name} {kind}{constraint}{fallback}")
    sequence = _sequence(conn)
    conn.execute(f"CREATE TABLE history_v7 ({', '.join(definitions)})")
    _copy_rows(conn, [row[1] for row in info])
    conn.execute("DROP TABLE history")
    conn.execute("ALTER TABLE history_v7 RENAME TO history")
    if sequence is not None and (_sequence(conn) or 0) < sequence:
        conn.execute("DELETE FROM sqlite_sequence WHERE name = 'history'")
        conn.execute("INSERT INTO sqlite_sequence (name, seq) VALUES ('history', ?)", (sequence,))
    return True


def _sequence(conn: sqlite3.Connection) -> Optional[int]:
    """The table's AUTOINCREMENT high-water mark, if it has one."""
    has_table = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'sqlite_sequence'"
    ).fetchone()
    if not has_table:
        return None
    row = conn.execute("SELECT seq FROM sqlite_sequence WHERE name = 'history'").fetchone()
    return int(row[0]) if row else None


def _copy_rows(conn: sqlite3.Connection, columns: List[str]) -> None:
    names = ", ".join(columns)
    conn.execute(f"INSERT INTO history_v7 ({names}) SELECT {names} FROM history")


def _absolute(file_path: str) -> str:
    """The key history stores a file under: its absolute path. An adapter
    result carries the path as the scan was given it (relative to the working
    directory); an absolute path (every Python result) is kept as it is."""
    if not file_path or Path(file_path).is_absolute():
        return file_path
    return str(Path(file_path).resolve())


def _rounded(value: Optional[float], digits: int) -> Optional[float]:
    return None if value is None else round(value, digits)


def _sha256(file_path: str) -> str:
    try:
        with open(file_path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()[:16]
    except Exception:
        return ""
