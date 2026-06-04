"""SQLite-backed repeated-run cache for Python file analysis."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict, is_dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, Dict, Iterator, Optional, cast

from slop_detector.metrics.context_jargon import ContextJargonResult, JargonEvidence
from slop_detector.metrics.docstring_inflation import (
    DocstringInflationDetail,
    DocstringInflationResult,
)
from slop_detector.metrics.hallucination_deps import (
    CategoryUsage,
    HallucinatedDependency,
    HallucinationDepsResult,
)
from slop_detector.models import (
    DDCResult,
    FileAnalysis,
    IgnoredFunction,
    InflationResult,
    LDRResult,
    MaskedIssue,
    SlopStatus,
    SuppressionDirective,
    SuppressionLedgerEntry,
)
from slop_detector.patterns.base import Axis, Issue, Severity

CACHE_ENGINE_VERSION = "analysis-cache-v1"
DEFAULT_CACHE_DB = Path.home() / ".slop-detector" / "analysis_cache.db"


class FileAnalysisCache:
    """Persistent cache keyed by path, file metadata, and analyzer/config fingerprint."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = Path(db_path) if db_path else DEFAULT_CACHE_DB
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS file_analysis_cache (
                    file_path TEXT PRIMARY KEY,
                    file_size INTEGER NOT NULL,
                    mtime_ns INTEGER NOT NULL,
                    sha256 TEXT NOT NULL,
                    engine_version TEXT NOT NULL,
                    config_fingerprint TEXT NOT NULL,
                    result_json TEXT NOT NULL
                )
                """
            )

    def get(
        self,
        file_path: str,
        file_size: int,
        mtime_ns: int,
        content_hash: str,
        config_fingerprint: str,
        engine_version: str = CACHE_ENGINE_VERSION,
    ) -> Optional[FileAnalysis]:
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT result_json
                FROM file_analysis_cache
                WHERE file_path = ?
                  AND file_size = ?
                  AND mtime_ns = ?
                  AND sha256 = ?
                  AND engine_version = ?
                  AND config_fingerprint = ?
                """,
                (file_path, file_size, mtime_ns, content_hash, engine_version, config_fingerprint),
            ).fetchone()
        if row is None:
            return None
        return deserialize_file_analysis(row[0])

    def put(
        self,
        file_path: str,
        file_size: int,
        mtime_ns: int,
        content_hash: str,
        config_fingerprint: str,
        result: FileAnalysis,
        engine_version: str = CACHE_ENGINE_VERSION,
    ) -> None:
        payload = serialize_file_analysis(result)
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO file_analysis_cache (
                    file_path, file_size, mtime_ns, sha256,
                    engine_version, config_fingerprint, result_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(file_path) DO UPDATE SET
                    file_size = excluded.file_size,
                    mtime_ns = excluded.mtime_ns,
                    sha256 = excluded.sha256,
                    engine_version = excluded.engine_version,
                    config_fingerprint = excluded.config_fingerprint,
                    result_json = excluded.result_json
                """,
                (
                    file_path,
                    file_size,
                    mtime_ns,
                    content_hash,
                    engine_version,
                    config_fingerprint,
                    payload,
                ),
            )


def fingerprint_config(config_dict: Dict[str, Any]) -> str:
    """Stable fingerprint for cache invalidation on config drift."""

    def _normalize(value: Any) -> Any:
        if is_dataclass(value) and not isinstance(value, type):
            return asdict(cast(Any, value))
        if isinstance(value, dict):
            return {k: _normalize(v) for k, v in sorted(value.items())}
        if isinstance(value, list):
            return [_normalize(v) for v in value]
        return value

    canonical = json.dumps(_normalize(config_dict), sort_keys=True, separators=(",", ":"))
    return sha256(canonical.encode("utf-8")).hexdigest()


def serialize_file_analysis(result: FileAnalysis) -> str:
    return json.dumps(result.to_dict(), sort_keys=True, separators=(",", ":"))


def deserialize_file_analysis(payload: str) -> FileAnalysis:
    data = json.loads(payload)
    return FileAnalysis(
        file_path=data["file_path"],
        ldr=LDRResult(**data["ldr"]),
        inflation=InflationResult(**data["inflation"]),
        ddc=DDCResult(**data["ddc"]),
        deficit_score=data["deficit_score"],
        status=SlopStatus(data["status"]),
        warnings=data.get("warnings", []),
        pattern_issues=[_restore_issue(item) for item in data.get("pattern_issues", [])],
        docstring_inflation=_restore_docstring_inflation(data.get("docstring_inflation")),
        hallucination_deps=_restore_hallucination_deps(data.get("hallucination_deps")),
        context_jargon=_restore_context_jargon(data.get("context_jargon")),
        ignored_functions=[IgnoredFunction(**item) for item in data.get("ignored_functions", [])],
        suppression_directives=[
            SuppressionDirective(**item) for item in data.get("suppression_directives", [])
        ],
        suppression_ledger=[
            SuppressionLedgerEntry(**item) for item in data.get("suppression_ledger", [])
        ],
        masked_issues=[MaskedIssue(**item) for item in data.get("masked_issues", [])],
        ml_score=_restore_ml_score(data.get("ml_score")),
        dcf=data.get("dcf", {}),
        deficit_breakdown=data.get("deficit_breakdown", {}),
    )


def _restore_issue(item: Dict[str, Any]) -> Issue:
    return Issue(
        pattern_id=item["pattern_id"],
        severity=Severity(item["severity"]),
        axis=Axis(item["axis"]),
        file=Path(item["file"]),
        line=item["line"],
        column=item.get("column", 0),
        message=item["message"],
        code=item.get("code"),
        suggestion=item.get("suggestion"),
    )


def _restore_docstring_inflation(data: Optional[Dict[str, Any]]) -> Any:
    if not data:
        return None
    return DocstringInflationResult(
        total_docstrings=data["total_docstrings"],
        inflated_count=data["inflated_count"],
        avg_inflation_ratio=data["avg_inflation_ratio"],
        max_inflation_ratio=data["max_inflation_ratio"],
        total_docstring_lines=data["total_docstring_lines"],
        total_implementation_lines=data["total_implementation_lines"],
        overall_ratio=data["overall_ratio"],
        status=data["status"],
        details=[DocstringInflationDetail(**detail) for detail in data.get("details", [])],
    )


def _restore_hallucination_deps(data: Optional[Dict[str, Any]]) -> Any:
    if not data:
        return None
    return HallucinationDepsResult(
        total_hallucinated=data["total_hallucinated"],
        category_usage=[CategoryUsage(**item) for item in data.get("category_usage", [])],
        hallucinated_deps=[
            HallucinatedDependency(**item) for item in data.get("hallucinated_deps", [])
        ],
        worst_category=data["worst_category"],
        status=data["status"],
    )


def _restore_context_jargon(data: Optional[Dict[str, Any]]) -> Any:
    if not data:
        return None
    return ContextJargonResult(
        total_jargon=data["total_jargon"],
        justified_jargon=data["justified_jargon"],
        unjustified_jargon=data["unjustified_jargon"],
        evidence_details=[JargonEvidence(**item) for item in data.get("evidence_details", [])],
        worst_offenders=data.get("worst_offenders", []),
        justification_ratio=data["justification_ratio"],
        status=data["status"],
    )


def _restore_ml_score(data: Optional[Dict[str, Any]]) -> Any:
    if not data:
        return None
    from slop_detector.ml.scorer import MLScore

    return MLScore(
        slop_probability=data["slop_probability"],
        confidence=data["confidence"],
        model_type=data["model_type"],
        agreement=data["agreement"],
        features_used=data["features_used"],
    )
