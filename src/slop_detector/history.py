"""
Historical trend tracking for slop detection.

Stores analysis results in SQLite and provides per-file trend analysis.
Auto-recorded on every CLI run; opt-out with --no-history.

Schema v2 (v2.9.0):
  - inflation_score replaces bcr_score (v2.8.0 rename)
  - pattern_count added
"""

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


_SCHEMA_V2 = """
CREATE TABLE IF NOT EXISTS history (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp        TEXT    NOT NULL,
    file_path        TEXT    NOT NULL,
    file_hash        TEXT    NOT NULL,
    deficit_score    REAL    NOT NULL,
    ldr_score        REAL    NOT NULL DEFAULT 0.0,
    inflation_score  REAL    NOT NULL DEFAULT 0.0,
    ddc_usage_ratio  REAL    NOT NULL DEFAULT 1.0,
    pattern_count    INTEGER NOT NULL DEFAULT 0,
    grade            TEXT    NOT NULL DEFAULT '',
    git_commit       TEXT,
    git_branch       TEXT
);
CREATE INDEX IF NOT EXISTS idx_file_path  ON history(file_path);
CREATE INDEX IF NOT EXISTS idx_timestamp  ON history(timestamp DESC);
"""


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
    grade: str
    git_commit: Optional[str] = None
    git_branch: Optional[str] = None


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
        with self._conn() as conn:
            conn.executescript(_SCHEMA_V2)
            self._migrate(conn)

    def _migrate(self, conn: sqlite3.Connection) -> None:
        """Add columns introduced after initial schema if missing."""
        existing = {row[1] for row in conn.execute("PRAGMA table_info(history)")}
        migrations = {
            "inflation_score": "ALTER TABLE history ADD COLUMN inflation_score REAL NOT NULL DEFAULT 0.0",
            "pattern_count":   "ALTER TABLE history ADD COLUMN pattern_count INTEGER NOT NULL DEFAULT 0",
            "ldr_score":       "ALTER TABLE history ADD COLUMN ldr_score REAL NOT NULL DEFAULT 0.0",
            "ddc_usage_ratio": "ALTER TABLE history ADD COLUMN ddc_usage_ratio REAL NOT NULL DEFAULT 1.0",
            "grade":           "ALTER TABLE history ADD COLUMN grade TEXT NOT NULL DEFAULT ''",
        }
        for col, ddl in migrations.items():
            if col not in existing:
                conn.execute(ddl)

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def record(self, file_analysis) -> None:
        """Record a FileAnalysis result. Accepts the dataclass directly."""
        file_path = str(getattr(file_analysis, "file_path", ""))
        deficit = float(getattr(file_analysis, "deficit_score", 0.0))

        ldr = getattr(file_analysis, "ldr", None)
        ldr_score = float(getattr(ldr, "ldr_score", 0.0)) if ldr else 0.0

        inflation = getattr(file_analysis, "inflation", None)
        inflation_score = float(getattr(inflation, "inflation_score", 0.0)) if inflation else 0.0

        ddc = getattr(file_analysis, "ddc", None)
        ddc_ratio = float(getattr(ddc, "usage_ratio", 1.0)) if ddc else 1.0

        pattern_issues = getattr(file_analysis, "pattern_issues", [])
        pattern_count = len(pattern_issues) if pattern_issues else 0

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
            grade=grade,
        )
        self._insert(entry)

    def _insert(self, e: HistoryEntry) -> None:
        sql = """
        INSERT INTO history
            (timestamp, file_path, file_hash, deficit_score, ldr_score,
             inflation_score, ddc_usage_ratio, pattern_count, grade, git_commit, git_branch)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        with self._conn() as conn:
            conn.execute(sql, (
                e.timestamp, e.file_path, e.file_hash, e.deficit_score,
                e.ldr_score, e.inflation_score, e.ddc_usage_ratio,
                e.pattern_count, e.grade, e.git_commit, e.git_branch,
            ))

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

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
        with self._conn() as conn:
            rows = conn.execute(sql, (file_path, limit)).fetchall()

        return [
            {
                "timestamp":       r[0],
                "file_hash":       r[1],
                "deficit_score":   r[2],
                "ldr_score":       r[3],
                "inflation_score": r[4],
                "ddc_usage_ratio": r[5],
                "pattern_count":   r[6],
                "grade":           r[7],
            }
            for r in rows
        ]

    def detect_regression(self, file_path: str, current_score: float) -> Optional[Dict[str, Any]]:
        """Return regression info if current score is 10+ points worse than recent avg."""
        history = self.get_file_history(file_path, limit=5)
        if not history:
            return None

        recent_avg = sum(h["deficit_score"] for h in history) / len(history)
        delta = current_score - recent_avg

        return {
            "is_regression":   delta >= 10.0,
            "current_score":   current_score,
            "recent_average":  round(recent_avg, 2),
            "delta":           round(delta, 2),
            "history_count":   len(history),
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
        with self._conn() as conn:
            rows = conn.execute(sql, (days,)).fetchall()

        return {
            "period_days": days,
            "data_points": len(rows),
            "daily_trends": [
                {
                    "date":            r[0],
                    "avg_deficit":     round(r[1], 2),
                    "avg_ldr":         round(r[2], 3),
                    "avg_inflation":   round(r[3], 3),
                    "avg_ddc":         round(r[4], 3),
                    "total_patterns":  r[5],
                    "files_analyzed":  r[6],
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
        with self._conn() as conn:
            rows = conn.execute(sql).fetchall()

        with open(output_path, "w", encoding="utf-8") as f:
            for r in rows:
                rec = {
                    "timestamp":       r[0],
                    "file_path":       r[1],
                    "file_hash":       r[2],
                    "deficit_score":   r[3],
                    "ldr_score":       r[4],
                    "inflation_score": r[5],
                    "ddc_usage_ratio": r[6],
                    "pattern_count":   r[7],
                    "grade":           r[8],
                    "git_commit":      r[9],
                    "git_branch":      r[10],
                }
                f.write(json.dumps(rec) + "\n")

        return len(rows)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _sha256(file_path: str) -> str:
    try:
        with open(file_path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()[:16]
    except Exception:
        return ""
