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
"""

import hashlib
import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

PROVENANCE_V6 = "v6"

_SCHEMA_V2 = """
CREATE TABLE IF NOT EXISTS history (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp            TEXT    NOT NULL,
    file_path            TEXT    NOT NULL,
    file_hash            TEXT    NOT NULL,
    deficit_score        REAL    NOT NULL,
    ldr_score            REAL    NOT NULL DEFAULT 0.0,
    inflation_score      REAL    NOT NULL DEFAULT 0.0,
    ddc_usage_ratio      REAL    NOT NULL DEFAULT 1.0,
    pattern_count        INTEGER NOT NULL DEFAULT 0,
    n_critical_patterns  INTEGER NOT NULL DEFAULT 0,
    grade                TEXT    NOT NULL DEFAULT '',
    git_commit           TEXT,
    git_branch           TEXT
);
CREATE INDEX IF NOT EXISTS idx_file_path  ON history(file_path);
CREATE INDEX IF NOT EXISTS idx_timestamp  ON history(timestamp DESC);
"""

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


@dataclass
class HistoryEntry:
    """Single historical analysis record."""

    timestamp: str
    file_path: str
    file_hash: str
    deficit_score: float
    ldr_score: float
    inflation_score: float
    ddc_usage_ratio: float
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

    def __post_init__(self) -> None:
        # Clamp scores so malformed data never corrupts the LEDA calibration grid search.
        self.deficit_score = max(0.0, self.deficit_score)
        self.ldr_score = max(0.0, min(1.0, self.ldr_score))
        self.inflation_score = max(0.0, self.inflation_score)
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
        with self._managed_conn() as conn:
            conn.executescript(_SCHEMA_V2)
            self._migrate(conn)
            conn.commit()

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
        }
        for col in _V6_COLUMNS:
            migrations[col] = (
                f"ALTER TABLE history ADD COLUMN {col} {_V6_COLUMNS[col]} DEFAULT NULL"
            )
        for col, ddl in migrations.items():
            if col not in existing:
                conn.execute(ddl)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_v6_evidence"
            " ON history(project_root, file_rel_path, measurement_fingerprint, timestamp)"
        )

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
        file_path = str(getattr(file_analysis, "file_path", ""))
        deficit = float(getattr(file_analysis, "deficit_score", 0.0))

        ldr = getattr(file_analysis, "ldr", None)
        ldr_score = float(getattr(ldr, "ldr_score", 0.0)) if ldr else 0.0

        inflation = getattr(file_analysis, "inflation", None)
        inflation_score = float(getattr(inflation, "inflation_score", 0.0)) if inflation else 0.0

        ddc = getattr(file_analysis, "ddc", None)
        ddc_ratio = float(getattr(ddc, "usage_ratio", 1.0)) if ddc else 1.0

        pattern_count, n_critical_patterns, fired_rules_json = _pattern_summary(
            getattr(file_analysis, "pattern_issues", []) or []
        )

        status = getattr(file_analysis, "status", None)
        grade = status.value if status and hasattr(status, "value") else str(status or "")

        file_hash = _sha256(file_path)

        entry = HistoryEntry(
            timestamp=datetime.now().isoformat(),
            file_path=file_path,
            file_hash=file_hash,
            deficit_score=deficit,
            ldr_score=ldr_score,
            inflation_score=inflation_score,
            ddc_usage_ratio=ddc_ratio,
            pattern_count=pattern_count,
            n_critical_patterns=n_critical_patterns,
            fired_rules=fired_rules_json,
            grade=grade,
            git_commit=git_commit,
            git_branch=git_branch,
            project_id=project_id,
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
             file_rel_path, base_deficit, pattern_penalty, provenance_state)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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

        return {
            "period_days": days,
            "data_points": len(rows),
            "daily_trends": [
                {
                    "date": r[0],
                    "avg_deficit": round(r[1], 2),
                    "avg_ldr": round(r[2], 3),
                    "avg_inflation": round(r[3], 3),
                    "avg_ddc": round(r[4], 3),
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
               git_commit, git_branch
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
                }
                f.write(json.dumps(rec) + "\n")

        return len(rows)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _pattern_summary(pattern_issues: List[Any]):
    """(finding count, CRITICAL count, fired_rules JSON {pattern_id: count} or None)."""
    n_critical = sum(
        1
        for issue in pattern_issues
        if str(getattr(getattr(issue, "severity", None), "value", "")).lower() == "critical"
    )
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
    breakdown = getattr(file_analysis, "deficit_breakdown", None) or {}
    penalty = float(breakdown.get("pattern_hits", 0.0))
    entry.detector_version = provenance.detector_version
    entry.measurement_fingerprint = provenance.measurement_fingerprint
    entry.weights_vector = json.dumps(provenance.weights, sort_keys=True)
    entry.project_root = str(root)
    entry.file_rel_path = rel
    entry.base_deficit = max(0.0, entry.deficit_score - penalty)
    entry.pattern_penalty = penalty
    entry.provenance_state = PROVENANCE_V6


def _sha256(file_path: str) -> str:
    try:
        with open(file_path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()[:16]
    except Exception:
        return ""
