"""
Historical trend tracking for slop detection.
Stores analysis results in SQLite and provides trend analysis.
"""

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class HistoryEntry:
    """Single historical analysis record"""

    timestamp: str
    file_path: str
    file_hash: str
    slop_score: float
    ldr_score: float
    bcr_score: float
    ddc_usage_ratio: float
    grade: str
    git_commit: Optional[str] = None
    git_branch: Optional[str] = None


class HistoryTracker:
    """Track and analyze slop detection history"""

    def __init__(self, db_path: str = ".slop_history.db"):
        self.db_path = Path(db_path)
        self._init_database()

    def _init_database(self):
        """Initialize SQLite database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                file_path TEXT NOT NULL,
                file_hash TEXT NOT NULL,
                slop_score REAL NOT NULL,
                ldr_score REAL NOT NULL,
                bcr_score REAL NOT NULL,
                ddc_usage_ratio REAL NOT NULL,
                grade TEXT NOT NULL,
                git_commit TEXT,
                git_branch TEXT,
                UNIQUE(timestamp, file_path)
            )
        """
        )

        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_file_path
            ON history(file_path)
        """
        )

        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_timestamp
            ON history(timestamp DESC)
        """
        )

        conn.commit()
        conn.close()

    def record(self, result: Dict[str, Any], git_info: Optional[Dict[str, str]] = None):
        """Record analysis result"""
        file_path = result.get("file_path", "")

        # Calculate file hash
        file_hash = self._calculate_file_hash(file_path) if Path(file_path).exists() else ""

        entry = HistoryEntry(
            timestamp=datetime.now().isoformat(),
            file_path=file_path,
            file_hash=file_hash,
            slop_score=result.get("slop_score", 0.0),
            ldr_score=result.get("ldr", {}).get("ldr_score", 0.0),
            bcr_score=result.get("bcr", {}).get("bcr_score", 0.0),
            ddc_usage_ratio=result.get("ddc", {}).get("usage_ratio", 0.0),
            grade=result.get("grade", "Unknown"),
            git_commit=git_info.get("commit") if git_info else None,
            git_branch=git_info.get("branch") if git_info else None,
        )

        self._insert_entry(entry)

    def _calculate_file_hash(self, file_path: str) -> str:
        """Calculate SHA256 hash of file content"""
        try:
            with open(file_path, "rb") as f:
                return hashlib.sha256(f.read()).hexdigest()
        except Exception:
            return ""

    def _insert_entry(self, entry: HistoryEntry):
        """Insert entry into database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute(
            """
            INSERT OR REPLACE INTO history
            (timestamp, file_path, file_hash, slop_score, ldr_score,
             bcr_score, ddc_usage_ratio, grade, git_commit, git_branch)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                entry.timestamp,
                entry.file_path,
                entry.file_hash,
                entry.slop_score,
                entry.ldr_score,
                entry.bcr_score,
                entry.ddc_usage_ratio,
                entry.grade,
                entry.git_commit,
                entry.git_branch,
            ),
        )

        conn.commit()
        conn.close()

    def get_file_history(self, file_path: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Get history for specific file"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT timestamp, file_hash, slop_score, ldr_score,
                   bcr_score, ddc_usage_ratio, grade, git_commit, git_branch
            FROM history
            WHERE file_path = ?
            ORDER BY timestamp DESC
            LIMIT ?
        """,
            (file_path, limit),
        )

        rows = cursor.fetchall()
        conn.close()

        return [
            {
                "timestamp": row[0],
                "file_hash": row[1],
                "slop_score": row[2],
                "ldr_score": row[3],
                "bcr_score": row[4],
                "ddc_usage_ratio": row[5],
                "grade": row[6],
                "git_commit": row[7],
                "git_branch": row[8],
            }
            for row in rows
        ]

    def detect_regression(self, file_path: str, current_score: float) -> Optional[Dict[str, Any]]:
        """Detect if current score is worse than recent history"""
        history = self.get_file_history(file_path, limit=5)

        if not history:
            return None

        # Calculate average of last 5 scores
        recent_avg = sum(h["slop_score"] for h in history) / len(history)

        # Regression detected if current score is 10+ points worse
        if current_score - recent_avg >= 10.0:
            return {
                "is_regression": True,
                "current_score": current_score,
                "recent_average": recent_avg,
                "delta": current_score - recent_avg,
                "history_count": len(history),
            }

        return {
            "is_regression": False,
            "current_score": current_score,
            "recent_average": recent_avg,
            "delta": current_score - recent_avg,
        }

    def get_project_trends(self, days: int = 7) -> Dict[str, Any]:
        """Get project-wide trends over time"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT
                DATE(timestamp) as date,
                AVG(slop_score) as avg_slop,
                AVG(ldr_score) as avg_ldr,
                AVG(bcr_score) as avg_bcr,
                AVG(ddc_usage_ratio) as avg_ddc,
                COUNT(*) as file_count
            FROM history
            WHERE timestamp >= datetime('now', '-' || ? || ' days')
            GROUP BY DATE(timestamp)
            ORDER BY date DESC
        """,
            (days,),
        )

        rows = cursor.fetchall()
        conn.close()

        return {
            "period_days": days,
            "data_points": len(rows),
            "daily_trends": [
                {
                    "date": row[0],
                    "avg_slop_score": round(row[1], 2),
                    "avg_ldr_score": round(row[2], 3),
                    "avg_bcr_score": round(row[3], 3),
                    "avg_ddc_usage_ratio": round(row[4], 3),
                    "files_analyzed": row[5],
                }
                for row in rows
            ],
        }

    def export_history(self, output_path: str, format: str = "json"):
        """Export history to file"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT timestamp, file_path, file_hash, slop_score,
                   ldr_score, bcr_score, ddc_usage_ratio, grade,
                   git_commit, git_branch
            FROM history
            ORDER BY timestamp DESC
        """
        )

        rows = cursor.fetchall()
        conn.close()

        data = [
            {
                "timestamp": row[0],
                "file_path": row[1],
                "file_hash": row[2],
                "slop_score": row[3],
                "ldr_score": row[4],
                "bcr_score": row[5],
                "ddc_usage_ratio": row[6],
                "grade": row[7],
                "git_commit": row[8],
                "git_branch": row[9],
            }
            for row in rows
        ]

        if format == "json":
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        else:
            raise ValueError(f"Unsupported format: {format}")
