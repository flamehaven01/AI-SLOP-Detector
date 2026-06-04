"""Verification helpers for CR-EP governance artifacts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Tuple


class GovernanceVerificationError(RuntimeError):
    """Raised when a governance artifact fails verification."""


def _load_governance_record(record_path: Path) -> Dict[str, Any]:
    if not record_path.exists():
        raise GovernanceVerificationError(f"governance record not found: {record_path}")
    try:
        return json.loads(record_path.read_text(encoding="utf-8"))
    except Exception as exc:  # pragma: no cover - defensive I/O wrapper
        raise GovernanceVerificationError(f"failed to read governance record: {exc}") from exc


def _compute_record_hash(record: Dict[str, Any]) -> str:
    payload = dict(record)
    payload.pop("record_hash", None)
    payload.pop("generated_at_utc", None)
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def verify_governance_record(record_path: Path) -> Tuple[Dict[str, Any], str]:
    """Verify integrity and policy constraints for a governance record.

    Returns:
        (record, computed_hash)

    Raises:
        GovernanceVerificationError: on tamper detection, missing record, or policy violation.
    """
    record = _load_governance_record(record_path)
    expected = str(record.get("record_hash", ""))
    computed = _compute_record_hash(record)

    if not expected:
        raise GovernanceVerificationError("missing record_hash")
    if expected != computed:
        raise GovernanceVerificationError("record_hash mismatch (tampering detected)")

    counts = record.get("counts", {})
    halt_count = int(counts.get("halt_count", 0) or 0)
    trust_tier = str(record.get("trust_tier", "")).upper()
    if halt_count > 0:
        raise GovernanceVerificationError(f"policy violation: halt_count={halt_count} > 0")
    if trust_tier == "UNTRUSTED":
        raise GovernanceVerificationError("policy violation: trust_tier == UNTRUSTED")

    return record, computed
