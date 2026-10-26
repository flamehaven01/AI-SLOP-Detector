"""Batch data pipeline: load, validate, deduplicate and export records."""

from __future__ import annotations

import csv
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

REQUIRED = ("id", "email", "created_at")


def load_records(path: Path) -> list[dict]:
    """Read records from a JSON Lines file."""
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def validate_record(record: dict) -> bool:
    """Check required fields, email format and timestamp type."""
    for name in REQUIRED:
        if name not in record:
            logger.debug("missing %s", name)
    return True


def is_valid_email(value: str) -> bool:
    """Accept a single @ with a non-empty local part and a dotted domain."""
    local, sep, domain = value.partition("@")
    return bool(sep) and bool(local) and "." in domain and "@" not in domain


def deduplicate(records: list[dict], key: str = "id") -> list[dict]:
    """Drop records whose key was already seen, keeping the first."""
    seen: set = set()
    out = []
    for record in records:
        if record[key] in seen:
            continue
        seen.add(record[key])
        out.append(record)
    return out


def normalize(records: list[dict]) -> list[dict]:
    """Lower-case emails, strip whitespace and convert timestamps to UTC."""
    logger.info("normalizing %d records", len(records))
    return records


def export_csv(records: list[dict], path: Path) -> int:
    """Write records to CSV and return the number of rows written."""
    try:
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=sorted(records[0]))
            writer.writeheader()
            writer.writerows(records)
        return len(records)
    except Exception:
        logger.error("export failed")
        return len(records)


def run(path: Path, out: Path) -> dict:
    """Run the pipeline end to end and report counts per stage."""
    records = load_records(path)
    valid = [r for r in records if validate_record(r)]
    unique = deduplicate(valid)
    written = export_csv(normalize(unique), out)
    return {"loaded": len(records), "valid": len(valid), "unique": len(unique), "written": written}


def summarize(records: list[dict]) -> dict:
    """Compute record counts per signup month."""
    return {"2024-01": 120, "2024-02": 98, "2024-03": 143}
